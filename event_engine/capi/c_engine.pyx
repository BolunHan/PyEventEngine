from threading import Thread

from cpython.datetime cimport datetime, timedelta
from cpython.object cimport PyObject
from cpython.ref cimport Py_INCREF, Py_XDECREF
from libc.stdlib cimport free

from .c_allocator cimport c_heap_new, c_heap_free, c_heap_request, c_heap_recycle, DEFAULT_ALLOC_PAGE
from .c_bytemap cimport MapEntry, ByteMap, c_bytemap_new, c_bytemap_free, c_bytemap_set, c_bytemap_get, c_bytemap_pop, c_bytemap_clear, DEFAULT_BYTEMAP_CAPACITY, C_BYTEMAP_NOT_FOUND
from .c_event cimport PyMessagePayload, C_INTERNAL_EMPTY_ARGS
from .c_topic cimport c_topic_match_bool, C_ALLOCATOR
from ..base import LOGGER

LOGGER = LOGGER.getChild('Engine')


class Full(Exception):
    pass


class Empty(Exception):
    pass


cdef class EventEngine:
    def __cinit__(self, size_t capacity=DEFAULT_MQ_CAPACITY, object logger=None):
        self.logger = LOGGER.getChild(f'EventEngine') if logger is None else logger
        cdef MemoryAllocator* allocator = NULL if C_ALLOCATOR is None else C_ALLOCATOR.allocator

        self.mq = c_mq_new(capacity, NULL, allocator)
        if not self.mq:
            raise MemoryError(f'Failed to allocate MessageQueue for {self.__class__.__name__}.')

        self.exact_topic_hooks = c_bytemap_new(DEFAULT_BYTEMAP_CAPACITY, NULL)
        if not self.exact_topic_hooks:
            c_mq_free(self.mq, 1)
            self.mq = NULL
            raise MemoryError(f'Failed to allocate MessageQueue for {self.__class__.__name__}.')

        self.generic_topic_hooks = c_bytemap_new(DEFAULT_BYTEMAP_CAPACITY, NULL)
        if not self.generic_topic_hooks:
            c_mq_free(self.mq, 1)
            c_bytemap_free(self.exact_topic_hooks, 1)
            self.mq = NULL
            raise MemoryError(f'Failed to allocate MessageQueue for {self.__class__.__name__}.')

        self.payload_allocator = c_heap_new(DEFAULT_ALLOC_PAGE)
        if not self.payload_allocator:
            c_mq_free(self.mq, 1)
            c_bytemap_free(self.exact_topic_hooks, 1)
            c_bytemap_free(self.generic_topic_hooks, 1)
            self.mq = NULL
            self.exact_topic_hooks = NULL
            self.generic_topic_hooks = NULL
            raise MemoryError(f'Failed to allocate MemoryAllocator for {self.__class__.__name__}.')

        self.seq_id = 0

    def __dealloc__(self):
        if self.mq:
            c_mq_free(self.mq, 1)
            self.mq = NULL

        if self.exact_topic_hooks:
            c_bytemap_free(self.exact_topic_hooks, 1)
            self.exact_topic_hooks = NULL

        if self.generic_topic_hooks:
            c_bytemap_free(self.generic_topic_hooks, 1)
            self.generic_topic_hooks = NULL

        if self.payload_allocator:
            c_heap_free(self.payload_allocator)
            self.payload_allocator = NULL

    cdef inline void c_loop(self):
        if not self.mq:
            raise RuntimeError('Not initialized!')

        cdef MessagePayload* msg = NULL
        cdef MessageQueue* mq = self.mq
        cdef int ret_code

        while self.active:
            # Step 1: Await message
            with nogil:
                ret_code = c_mq_get_hybrid(mq, &msg, DEFAULT_MQ_SPIN_LIMIT, DEFAULT_MQ_TIMEOUT_SECONDS)
                # ret_code = c_mq_get_await(mq, &msg, DEFAULT_MQ_TIMEOUT_SECONDS)
                if ret_code != 0:
                    continue

            # Trigger message callbacks
            self.c_trigger(msg)

            # Clean up the message payload
            if msg.args:
                Py_XDECREF(<PyObject*> msg.args)
            if msg.kwargs:
                Py_XDECREF(<PyObject*> msg.kwargs)
            if msg.allocator and msg.allocator.active:
                c_heap_recycle(msg.allocator, <void*> msg)
            else:
                free(msg)

    cdef inline MessagePayload* c_get(self, bint block, size_t max_spin, double timeout):
        cdef MessagePayload* msg = NULL
        cdef int ret_code
        if block:
            ret_code = c_mq_get_hybrid(self.mq, &msg, max_spin, timeout)
        else:
            ret_code = c_mq_get(self.mq, &msg)

        if ret_code != 0:
            return NULL
        return msg

    cdef inline int c_publish(self, PyTopic topic, tuple args, dict kwargs, bint block, size_t max_spin, double timeout):
        if not topic.header.is_exact:
            raise ValueError('Topic must be all of exact parts')

        # Step 0: Request payload buffer (MUST be done with GIL held - allocator is NOT thread-safe)
        cdef MessagePayload* payload = <MessagePayload*> c_heap_request(self.payload_allocator, sizeof(MessagePayload))

        # Step 1: Assembling payload (MUST be done with GIL held - touching Python objects)
        payload.topic = topic.header
        payload.args = <PyObject*> args
        payload.kwargs = <PyObject*> kwargs
        payload.seq_id = self.seq_id
        payload.allocator = self.payload_allocator

        # Step 2: Update reference count BEFORE sending (ensure objects stay alive)
        Py_INCREF(args)
        Py_INCREF(kwargs)
        self.seq_id += 1

        # Step 3: Send the payload (can be done without GIL - queue is thread-safe)
        cdef int ret_code
        with nogil:
            if block:
                ret_code = c_mq_put_hybrid(self.mq, payload, max_spin, timeout)
            else:
                ret_code = c_mq_put(self.mq, payload)

        # Step 4: Handle failure case (undo increfs and free payload)
        if ret_code:
            self.seq_id -= 1
            Py_XDECREF(<PyObject*> args)
            Py_XDECREF(<PyObject*> kwargs)
            if payload.allocator and payload.allocator.active:
                c_heap_recycle(payload.allocator, <void*> payload)
            else:
                free(payload)

        return ret_code

    cdef inline void c_trigger(self, MessagePayload* msg):
        cdef Topic* msg_topic = msg.topic
        # Step 1: Match exact_topic_hooks
        cdef void* hook_ptr
        cdef EventHook event_hook

        hook_ptr = c_bytemap_get(self.exact_topic_hooks, msg_topic.key, msg_topic.key_len)
        if hook_ptr and hook_ptr != C_BYTEMAP_NOT_FOUND:
            event_hook = <EventHook> <PyObject*> hook_ptr
            event_hook.c_trigger_no_topic(msg)
            event_hook.c_trigger_with_topic(msg)

        # Step 2: Match generic_topic_hooks
        cdef MapEntry* entry = self.generic_topic_hooks.first
        cdef int is_matched
        while entry:
            hook_ptr = entry.value
            if not hook_ptr:
                continue
            event_hook = <EventHook> <PyObject*> hook_ptr
            is_matched = c_topic_match_bool(event_hook.topic.header, msg_topic)
            if is_matched:
                event_hook.c_trigger_no_topic(msg)
                event_hook.c_trigger_with_topic(msg)
            entry = entry.next

    cdef inline void c_register_hook(self, EventHook hook):
        cdef Topic* topic_ptr = hook.topic.header
        cdef void* existing_hook_ptr
        cdef ByteMapHeader* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks

        existing_hook_ptr = c_bytemap_get(hook_map, topic_ptr.key, topic_ptr.key_len)
        if existing_hook_ptr and existing_hook_ptr != C_BYTEMAP_NOT_FOUND and existing_hook_ptr != <void*> <PyObject*> hook:
            raise KeyError(f'Another EventHook already registered for {hook.topic.value}')
        c_bytemap_set(hook_map, topic_ptr.key, topic_ptr.key_len, <void*> <PyObject*> hook)
        Py_INCREF(hook)

    cdef inline EventHook c_unregister_hook(self, PyTopic topic):
        cdef Topic* topic_ptr = topic.header
        cdef void* existing_hook_ptr = <void*> C_BYTEMAP_NOT_FOUND
        cdef ByteMapHeader* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks
        cdef int ret_code = c_bytemap_pop(hook_map, <char*> topic_ptr.key, topic_ptr.key_len, &existing_hook_ptr)
        if existing_hook_ptr == C_BYTEMAP_NOT_FOUND:
            raise KeyError(f'No EventHook registered for {topic.value}')
        cdef EventHook hook = <EventHook> <PyObject*> existing_hook_ptr
        Py_XDECREF(<PyObject*> hook)
        return hook

    cdef inline void c_register_handler(self, PyTopic topic, object py_callable, bint deduplicate):
        cdef Topic* topic_ptr = topic.header
        cdef void* hook_ptr
        cdef EventHook event_hook
        cdef ByteMapHeader* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks

        hook_ptr = c_bytemap_get(hook_map, topic_ptr.key, topic_ptr.key_len)
        if hook_ptr and hook_ptr == C_BYTEMAP_NOT_FOUND:
            event_hook = EventHook.__new__(EventHook, topic, self.logger)
            hook_ptr = <void*> <PyObject*> event_hook
            c_bytemap_set(hook_map, topic_ptr.key, topic_ptr.key_len, hook_ptr)
            Py_INCREF(event_hook)
        else:
            event_hook = <EventHook> <PyObject*> hook_ptr
        event_hook.add_handler(py_callable, deduplicate)

    cdef inline void c_unregister_handler(self, PyTopic topic, object py_callable):
        cdef Topic* topic_ptr = topic.header
        cdef void* hook_ptr
        cdef EventHook event_hook
        cdef ByteMapHeader* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks

        hook_ptr = c_bytemap_get(hook_map, topic_ptr.key, topic_ptr.key_len)
        if hook_ptr and hook_ptr == C_BYTEMAP_NOT_FOUND:
            raise KeyError(f'No EventHook registered for {topic.value}')
        event_hook = <EventHook> <PyObject*> hook_ptr
        event_hook.remove_handler(py_callable)
        if len(event_hook) == 0:
            c_bytemap_pop(hook_map, topic_ptr.key, topic_ptr.key_len, NULL)
            Py_XDECREF(<PyObject*> event_hook)

    cdef inline void c_clear(self):
        cdef MapEntry* entry
        cdef EventHook event_hook

        # Clear exact_topic_hooks
        entry = self.exact_topic_hooks.first
        while entry:
            if entry.value:
                event_hook = <EventHook> <PyObject*> entry.value
                event_hook.clear()
                entry.value = NULL
                Py_XDECREF(<PyObject*> event_hook)
            entry = entry.next
        c_bytemap_clear(self.exact_topic_hooks)

        # Clear generic_topic_hooks
        entry = self.generic_topic_hooks.first
        while entry:
            if entry.value:
                event_hook = <EventHook> <PyObject*> entry.value
                event_hook.clear()
                entry.value = NULL
                Py_XDECREF(<PyObject*> event_hook)
            entry = entry.next
        c_bytemap_clear(self.generic_topic_hooks)

    # --- Python Interfaces---

    def __len__(self):
        count = 0
        entry = self.exact_topic_hooks.first
        while entry:
            if entry.value:
                count += 1
            entry = entry.next
        entry = self.generic_topic_hooks.first
        while entry:
            if entry.value:
                count += 1
            entry = entry.next
        return count

    def __repr__(self):
        return f'<{self.__class__.__name__} {"active" if self.active else "idle"}>(capacity={self.capacity})'

    def activate(self):
        self.active = True

    def deactivate(self):
        self.active = False

    def run(self):
        self.c_loop()

    def start(self):
        if self.active:
            self.logger.warning(f'{self} already started!')
            return
        self.active = True
        self.engine = Thread(target=self.run, name='EventEngine')
        self.engine.start()
        self.logger.info(f'{self} started.')

    def stop(self) -> None:
        if not self.active:
            self.logger.warning('EventEngine already stopped!')
            return

        self.active = False
        self.engine.join()

    def clear(self) -> None:
        if self.active:
            self.logger.error('EventEngine must be stopped before cleared!')
            return

        self.c_clear()

    def get(self, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0) -> PyMessagePayload:
        cdef MessagePayload* msg = self.c_get(block, max_spin, timeout)
        if not msg:
            raise Empty()
        cdef PyMessagePayload payload = PyMessagePayload.c_from_header(msg, owner=True, args_owner=True, kwargs_owner=True)
        return payload

    def put(self, PyTopic topic, *args, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0, **kwargs):
        cdef int ret_code = self.c_publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code:
            raise Full()

    def publish(self, PyTopic topic, tuple args, dict kwargs, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0):
        cdef int ret_code = self.c_publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code:
            raise Full()

    def register_hook(self, EventHook hook):
        self.c_register_hook(hook)

    def unregister_hook(self, PyTopic topic) -> EventHook:
        return self.c_unregister_hook(topic)

    def register_handler(self, PyTopic topic, object handler, bint deduplicate=False):
        self.c_register_handler(topic, handler, deduplicate)

    def unregister_handler(self, PyTopic topic, object handler):
        self.c_unregister_handler(topic, handler)

    def event_hooks(self):
        entry = self.exact_topic_hooks.first
        while entry:
            if entry.value:
                yield <EventHook> <PyObject*> entry.value
            entry = entry.next
        entry = self.generic_topic_hooks.first
        while entry:
            if entry.value:
                yield <EventHook> <PyObject*> entry.value
            entry = entry.next

    def topics(self):
        entry = self.exact_topic_hooks.first
        while entry:
            if entry.value:
                yield (<EventHook> <PyObject*> entry.value).topic
            entry = entry.next
        entry = self.generic_topic_hooks.first
        while entry:
            if entry.value:
                yield (<EventHook> <PyObject*> entry.value).topic
            entry = entry.next

    def items(self):
        entry = self.exact_topic_hooks.first
        while entry:
            if entry.value:
                hook = <EventHook> <PyObject*> entry.value
                yield (hook.topic, hook)
            entry = entry.next
        entry = self.generic_topic_hooks.first
        while entry:
            if entry.value:
                hook = <EventHook> <PyObject*> entry.value
                yield (hook.topic, hook)
            entry = entry.next

    property capacity:
        def __get__(self):
            return self.mq.capacity

    property occupied:
        def __get__(self):
            return c_mq_occupied(self.mq)

    property exact_topic_hook_map:
        def __get__(self):
            return ByteMap.c_from_header(self.exact_topic_hooks, 0)

    property generic_topic_hook_map:
        def __get__(self):
            return ByteMap.c_from_header(self.generic_topic_hooks, 0)


cdef class EventEngineEx(EventEngine):
    def __cinit__(self, size_t capacity=DEFAULT_MQ_CAPACITY, object logger=None):
        self.timer = {}

    cdef inline void c_timer_loop(self, double interval, PyTopic topic, datetime activate_time):
        from time import sleep
        cdef datetime scheduled_time

        if activate_time is None:
            scheduled_time = datetime.now()
        else:
            scheduled_time = activate_time

        cdef dict kwargs = {'interval': interval, 'trigger_time': scheduled_time}

        while self.active:
            sleep_time = (scheduled_time - datetime.now()).total_seconds()

            if sleep_time > 0:
                sleep(sleep_time)
            self.c_publish(topic, C_INTERNAL_EMPTY_ARGS, kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

            while scheduled_time < datetime.now():
                scheduled_time += timedelta(seconds=interval)
            kwargs['trigger_time'] = scheduled_time

    cdef inline void c_minute_timer_loop(self, PyTopic topic):
        from time import time, sleep
        cdef double t, scheduled_time, next_time, sleep_time
        cdef dict kwargs = {'interval': 60}

        while self.active:
            t = time()
            scheduled_time = t // 60 * 60
            next_time = scheduled_time + 60
            sleep_time = next_time - t
            sleep(sleep_time)
            kwargs['timestamp'] = scheduled_time
            self.c_publish(topic, C_INTERNAL_EMPTY_ARGS, kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

    cdef inline void c_second_timer_loop(self, PyTopic topic):
        from time import time, sleep
        cdef double t, scheduled_time, next_time, sleep_time
        cdef dict kwargs = {'interval': 60}

        while self.active:
            t = time()
            scheduled_time = t // 1
            next_time = scheduled_time + 1
            sleep_time = next_time - t
            sleep(sleep_time)
            kwargs['timestamp'] = scheduled_time
            self.c_publish(topic, C_INTERNAL_EMPTY_ARGS, kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

    # --- Python Interfaces ---

    def __repr__(self):
        return f'<{self.__class__.__name__} {"active" if self.active else "idle"}>(capacity={self.capacity}, timers={list(self.timer.keys())})'

    def run_timer(self, double interval, PyTopic topic, datetime activate_time=None):
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self.c_timer_loop(interval, topic, activate_time)

    def minute_timer(self, PyTopic topic):
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self.c_minute_timer_loop(topic)

    def second_timer(self, PyTopic topic):
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self.c_second_timer_loop(topic)

    def get_timer(self, double interval, datetime activate_time=None) -> PyTopic:
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')

        if interval == 1:
            topic = PyTopic('EventEngine.Internal.Timer.Second')
            timer = Thread(target=self.second_timer, kwargs={'topic': topic})
        elif interval == 60:
            topic = PyTopic('EventEngine.Internal.Timer.Minute')
            timer = Thread(target=self.minute_timer, kwargs={'topic': topic})
        else:
            topic = PyTopic.join(['EventEngine', 'Internal', 'Timer', str(interval)])
            timer = Thread(target=self.run_timer, kwargs={'interval': interval, 'topic': topic, 'activate_time': activate_time})

        if interval not in self.timer:
            self.timer[interval] = timer
            timer.start()
        else:
            if activate_time is not None:
                self.logger.debug(f'Timer thread with interval [{timedelta(seconds=interval)}] already initialized! Argument [activate_time] takes no effect!')

        return topic

    def stop(self) -> None:
        super().stop()

        for timer in self.timer.values():
            timer.join()

    def clear(self) -> None:
        super().clear()

        for t in self.timer.values():
            t.join(timeout=0)
        self.timer.clear()
