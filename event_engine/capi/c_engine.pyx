from threading import Thread

from cpython.datetime cimport datetime, timedelta
from cpython.object cimport PyObject
from cpython.ref cimport Py_INCREF, Py_XDECREF
from libc.stdlib cimport free

from .c_event cimport MessagePayload, EMPTY_ARGS, c_evt_payload_new, c_evt_payload_free, evt_py_payload, c_evt_hook_invoke
from .c_topic cimport c_topic_match_bool, HEAP_ALLOCATOR
from ..base import LOGGER
from ..base.c_strmap cimport StrMap

LOGGER = LOGGER.getChild('Engine')


class Full(Exception):
    pass


class Empty(Exception):
    pass


cdef class EventEngine:
    def __cinit__(self, size_t capacity=DEFAULT_MQ_CAPACITY, object logger=None):
        self.logger = LOGGER.getChild(f'EventEngine') if logger is None else logger
        cdef heap_allocator* allocator = HEAP_ALLOCATOR

        self.mq = c_mq_new(capacity, NULL, allocator)
        if not self.mq:
            raise MemoryError(f'Failed to allocate MessageQueue for {self.__class__.__name__}.')

        self.exact_topic_hooks = c_strmap_new(0, NULL, 0)
        if not self.exact_topic_hooks:
            c_mq_free(self.mq, 1)
            self.mq = NULL
            raise MemoryError(f'Failed to allocate MessageQueue for {self.__class__.__name__}.')

        self.generic_topic_hooks = c_strmap_new(0, NULL, 0)
        if not self.generic_topic_hooks:
            c_mq_free(self.mq, 1)
            c_strmap_free(self.exact_topic_hooks, 1, 1)
            self.mq = NULL
            raise MemoryError(f'Failed to allocate MessageQueue for {self.__class__.__name__}.')

        self.payload_allocator = c_heap_allocator_new()
        if not self.payload_allocator:
            c_mq_free(self.mq, 1)
            c_strmap_free(self.exact_topic_hooks, 1, 1)
            c_strmap_free(self.generic_topic_hooks, 1, 1)
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
            c_strmap_free(self.exact_topic_hooks, 1, 1)
            self.exact_topic_hooks = NULL

        if self.generic_topic_hooks:
            c_strmap_free(self.generic_topic_hooks, 1, 1)
            self.generic_topic_hooks = NULL

        if self.payload_allocator:
            c_heap_allocator_free(self.payload_allocator)
            self.payload_allocator = NULL

    cdef inline void c_loop(self):
        if not self.mq:
            raise RuntimeError('Not initialized!')

        cdef evt_message_payload* msg = NULL
        cdef evt_py_payload* py_payload = NULL
        cdef message_queue* mq = self.mq
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
            c_evt_payload_free(msg, 1)

    cdef inline evt_message_payload* c_get(self, bint block, size_t max_spin, double timeout):
        cdef evt_message_payload* msg = NULL
        cdef int ret_code
        if block:
            ret_code = c_mq_get_hybrid(self.mq, &msg, max_spin, timeout)
        else:
            ret_code = c_mq_get(self.mq, &msg)

        if ret_code != 0:
            return NULL
        return msg

    cdef inline int c_publish(self, Topic topic, tuple args, dict kwargs, bint block, size_t max_spin, double timeout):
        if not topic.header.is_exact:
            raise ValueError('Topic must be all of exact parts')

        # Step 0: Request payload buffer (MUST be done with GIL held - allocator is NOT thread-safe)
        cdef evt_message_payload* payload = c_evt_payload_new(self.payload_allocator, topic, args, kwargs, 1)

        # Step 1: Assembling payload (MUST be done with GIL held - touching Python objects)
        payload.seq_id = self.seq_id
        self.seq_id += 1

        # Step 2: Send the payload (can be done without GIL - queue is thread-safe)
        cdef int ret_code
        with nogil:
            if block:
                ret_code = c_mq_put_hybrid(self.mq, payload, max_spin, timeout)
            else:
                ret_code = c_mq_put(self.mq, payload)

        # Step 4: Handle failure case (undo increfs and free payload)
        if not ret_code:
            return ret_code

        self.seq_id -= 1
        c_evt_payload_free(payload, 1)
        return ret_code

    cdef inline void c_trigger(self, evt_message_payload* msg):
        cdef evt_topic* msg_topic = msg.topic
        # Step 1: Match exact_topic_hooks
        cdef PyObject* hook_ptr = NULL
        cdef EventHook event_hook

        cdef int ret_code = c_strmap_get(self.exact_topic_hooks, msg_topic.key, msg_topic.key_len, <void**> &hook_ptr)
        if hook_ptr:
            event_hook = <EventHook> hook_ptr
            c_evt_hook_invoke(event_hook.header, msg)

        # Step 2: Match generic_topic_hooks
        cdef strmap_entry* entry = self.generic_topic_hooks.first
        cdef int is_matched
        while entry:
            hook_ptr = <PyObject*> entry.value
            if not hook_ptr:
                continue
            event_hook = <EventHook> <PyObject*> hook_ptr
            is_matched = c_topic_match_bool(event_hook.topic.header, msg_topic)
            if is_matched:
                c_evt_hook_invoke(event_hook.header, msg)
            entry = entry.next

    cdef inline void c_register_hook(self, EventHook hook):
        cdef evt_topic* topic_ptr = hook.topic.header
        cdef PyObject* existing_hook_ptr = NULL
        cdef strmap* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks

        cdef int ret_code = c_strmap_get(hook_map, topic_ptr.key, topic_ptr.key_len, <void**> &existing_hook_ptr)
        if existing_hook_ptr and existing_hook_ptr != <PyObject*> hook:
            raise KeyError(f'Another EventHook already registered for {hook.topic.value}')
        ret_code = c_strmap_set(hook_map, topic_ptr.key, topic_ptr.key_len, <void*> <PyObject*> hook, NULL, 0)
        Py_INCREF(hook)

    cdef inline EventHook c_unregister_hook(self, Topic topic):
        cdef evt_topic* topic_ptr = topic.header
        cdef PyObject* existing_hook_ptr = NULL
        cdef strmap* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks
        cdef int ret_code = c_strmap_pop(hook_map, <char*> topic_ptr.key, topic_ptr.key_len, <void**> &existing_hook_ptr, 0)
        if not existing_hook_ptr:
            raise KeyError(f'No EventHook registered for {topic.value}')
        cdef EventHook hook = <EventHook> existing_hook_ptr
        Py_XDECREF(<PyObject*> hook)
        return hook

    cdef inline void c_register_handler(self, Topic topic, object py_callable, bint deduplicate):
        cdef evt_topic* topic_ptr = topic.header
        cdef PyObject* hook_ptr = NULL
        cdef EventHook event_hook
        cdef strmap* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks

        cdef int ret_code = c_strmap_get(hook_map, topic_ptr.key, topic_ptr.key_len, <void**> &hook_ptr)
        if ret_code == STRMAP_ERR_NOT_FOUND:
            event_hook = EventHook.__new__(EventHook, topic, self.logger)
            c_strmap_set(hook_map, topic_ptr.key, topic_ptr.key_len, <void*> <PyObject*> event_hook, NULL, 0)
            Py_INCREF(event_hook)
        elif not hook_ptr:
            raise BufferError(f'Corrected buffer, invalid registered event hook.')
        else:
            event_hook = <EventHook> hook_ptr
        event_hook.add_handler(py_callable, deduplicate)

    cdef inline void c_unregister_handler(self, Topic topic, object py_callable):
        cdef evt_topic* topic_ptr = topic.header
        cdef PyObject* hook_ptr = NULL
        cdef EventHook event_hook
        cdef strmap* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks

        cdef int ret_code = c_strmap_get(hook_map, topic_ptr.key, topic_ptr.key_len, <void**> &hook_ptr)
        if ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError(f'No EventHook registered for {topic.value}')
        event_hook = <EventHook> hook_ptr
        event_hook.remove_handler(py_callable)
        if len(event_hook) == 0:
            c_strmap_pop(hook_map, topic_ptr.key, topic_ptr.key_len, NULL, 0)
            Py_XDECREF(<PyObject*> event_hook)

    cdef inline void c_clear(self):
        cdef strmap_entry* entry
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
        c_strmap_clear(self.exact_topic_hooks, 0)

        # Clear generic_topic_hooks
        entry = self.generic_topic_hooks.first
        while entry:
            if entry.value:
                event_hook = <EventHook> <PyObject*> entry.value
                event_hook.clear()
                entry.value = NULL
                Py_XDECREF(<PyObject*> event_hook)
            entry = entry.next
        c_strmap_clear(self.generic_topic_hooks, 0)

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

    def get(self, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0) -> MessagePayload:
        cdef evt_message_payload* msg = self.c_get(block, max_spin, timeout)
        if not msg:
            raise Empty()
        cdef MessagePayload payload = MessagePayload.c_from_header(msg, True)
        return payload

    def put(self, Topic topic, *args, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0, **kwargs):
        cdef int ret_code = self.c_publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code:
            raise Full()

    def publish(self, Topic topic, tuple args, dict kwargs, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0):
        cdef int ret_code = self.c_publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code:
            raise Full()

    def register_hook(self, EventHook hook):
        self.c_register_hook(hook)

    def unregister_hook(self, Topic topic) -> EventHook:
        return self.c_unregister_hook(topic)

    def register_handler(self, Topic topic, object handler, bint deduplicate=False):
        self.c_register_handler(topic, handler, deduplicate)

    def unregister_handler(self, Topic topic, object handler):
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
            return StrMap.c_from_header(self.exact_topic_hooks, 0)

    property generic_topic_hook_map:
        def __get__(self):
            return StrMap.c_from_header(self.generic_topic_hooks, 0)


cdef class EventEngineEx(EventEngine):
    def __cinit__(self, size_t capacity=DEFAULT_MQ_CAPACITY, object logger=None):
        self.timer = {}

    cdef inline void c_timer_loop(self, double interval, Topic topic, datetime activate_time):
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
            self.c_publish(topic, EMPTY_ARGS, kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

            while scheduled_time < datetime.now():
                scheduled_time += timedelta(seconds=interval)
            kwargs['trigger_time'] = scheduled_time

    cdef inline void c_minute_timer_loop(self, Topic topic):
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
            self.c_publish(topic, EMPTY_ARGS, kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

    cdef inline void c_second_timer_loop(self, Topic topic):
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
            self.c_publish(topic, EMPTY_ARGS, kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

    # --- Python Interfaces ---

    def __repr__(self):
        return f'<{self.__class__.__name__} {"active" if self.active else "idle"}>(capacity={self.capacity}, timers={list(self.timer.keys())})'

    def run_timer(self, double interval, Topic topic, datetime activate_time=None):
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self.c_timer_loop(interval, topic, activate_time)

    def minute_timer(self, Topic topic):
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self.c_minute_timer_loop(topic)

    def second_timer(self, Topic topic):
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self.c_second_timer_loop(topic)

    def get_timer(self, double interval, datetime activate_time=None) -> Topic:
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')

        if interval == 1:
            topic = Topic('EventEngine.Internal.Timer.Second')
            timer = Thread(target=self.second_timer, kwargs={'topic': topic})
        elif interval == 60:
            topic = Topic('EventEngine.Internal.Timer.Minute')
            timer = Thread(target=self.minute_timer, kwargs={'topic': topic})
        else:
            topic = Topic.join(['EventEngine', 'Internal', 'Timer', str(interval)])
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
