from threading import Thread

from cpython.datetime cimport datetime, timedelta
from cpython.object cimport PyObject
from cpython.ref cimport Py_INCREF, Py_XDECREF
from cpython.time cimport perf_counter

from cbase.bytemap.c_bytemap cimport BoundByteMap, bytemap, c_bytemap_gen_seq_id

from .c_engine cimport DEFAULT_MQ_CAPACITY, DEFAULT_MQ_SPIN_LIMIT, DEFAULT_MQ_TIMEOUT_SECONDS, message_queue, c_mq_free, c_mq_get, c_mq_new, c_mq_occupied, c_mq_put
from .c_event cimport EMPTY_ARGS, MessagePayload, EventHook, c_evt_pypayload_free, c_evt_pypayload_new, evt_hook, evt_message_payload, evt_py_payload, evt_py_topic
from .c_ret_code cimport evt_ret_code
from .c_topic cimport Topic, c_topic_match_bool
from ..base.c_allocator_protocol cimport EE_HEAP_ALLOCATOR
from ..base import LOGGER

LOGGER = LOGGER.getChild('Engine')


class Full(Exception):
    pass


class Empty(Exception):
    pass


cdef class EventHookMap(BoundByteMap):
    """Synchronized topic → EventHook mapping backed by a C bytemap.

    The C bytemap stores the raw ``evt_hook*`` pointer as the value, so the
    C engine's trigger can dispatch entries directly while this dict keeps
    the Python-facing EventHook object identity.
    """

    @staticmethod
    cdef EventHookMap c_from_header(bytemap* header, bint owner=False):
        cdef EventHookMap instance = EventHookMap.__new__(EventHookMap)
        instance.seq_id = c_bytemap_gen_seq_id(<void*> instance)
        instance.c_bind(header)
        instance.owner = owner
        return instance

    cdef object c_deserialize_value(self, const char* value, size_t value_len):
        cdef void** vp = <void**> value
        cdef evt_hook* hook = <evt_hook*> vp[0]
        return EventHook.c_from_header(hook, False)

    cdef const char* c_serialize_value(self, object obj, size_t* value_len):
        cdef EventHook hook = <EventHook> obj
        self._ws_ptr = <void*> hook.header
        if value_len:
            value_len[0] = sizeof(void*)
        return <const char*> &self._ws_ptr


cdef class EventEngineEx:
    def __cinit__(self, size_t capacity=DEFAULT_MQ_CAPACITY, object logger=None):
        self.logger = LOGGER.getChild(f'EventEngineEx') if logger is None else logger

        self.engine_c = c_evt_engine_new(EE_HEAP_ALLOCATOR)
        if not self.engine_c:
            raise MemoryError(f'Failed to allocate engine for {self.__class__.__name__}.')

        if capacity != DEFAULT_MQ_CAPACITY:
            c_mq_free(self.engine_c.mq)
            self.engine_c.mq = c_mq_new(capacity, NULL, EE_HEAP_ALLOCATOR)
            if not self.engine_c.mq:
                c_evt_engine_free(self.engine_c)
                self.engine_c = NULL
                raise MemoryError(f'Failed to allocate MessageQueue for {self.__class__.__name__}.')

        self.exact_hook_map = EventHookMap.c_from_header(self.engine_c.exact_topic_hooks, False)
        self.generic_hook_map = EventHookMap.c_from_header(self.engine_c.generic_topic_hooks, False)
        self.timer = {}
        self.timer_payloads = {}

    def __dealloc__(self):
        if self.engine_c:
            c_evt_engine_free(self.engine_c)
            self.engine_c = NULL

    cdef inline void c_loop(self):
        if not self.engine_c:
            raise RuntimeError('Not initialized!')

        # GIL-aware loop — runs with the GIL held; the C layer releases it
        # only around the blocking queue wait, so every dispatch runs under
        # the GIL.
        c_evt_engine_loop_gil(self.engine_c)

    cdef inline evt_message_payload* c_get(self, bint block, size_t max_spin, double timeout):
        return c_evt_engine_get(self.engine_c, block, max_spin, timeout)

    cdef inline int c_publish(self, Topic topic, tuple args, dict kwargs, bint block, size_t max_spin, double timeout):
        if not topic.header.is_exact:
            raise ValueError('Topic must be all of exact parts')

        # Request payload buffer (MUST be done with GIL held - allocator is NOT thread-safe)
        cdef PyObject* py_topic = <PyObject*> topic
        cdef evt_message_payload* payload = c_evt_pypayload_new(
            <evt_py_topic*> py_topic,
            <PyObject*> args,
            <PyObject*> kwargs,
            EE_HEAP_ALLOCATOR
        )
        if not payload:
            raise MemoryError('Failed to allocate message payload')

        # The C engine assigns seq_id and frees the payload on failure
        return c_evt_engine_publish_gil(self.engine_c, payload, block, max_spin, timeout)

    # --- Python Interfaces (Engine Core) ---

    def __len__(self):
        return len(self.exact_hook_map) + len(self.generic_hook_map)

    def __repr__(self):
        return f'<{self.__class__.__name__} {"active" if c_evt_engine_is_active(self.engine_c) else "idle"}>(capacity={self.capacity}, timers={list(self.timer.keys())})'

    def __getitem__(self, Topic topic) -> list[EventHook]:
        cdef list out = []
        cdef evt_topic* topic_ptr = topic.header
        cdef EventHook hook
        for hook in self.exact_hook_map.values():
            if c_topic_match_bool(hook.topic.header, topic_ptr):
                out.append(hook)
        for hook in self.generic_hook_map.values():
            if c_topic_match_bool(hook.topic.header, topic_ptr):
                out.append(hook)
        return out

    def activate(self):
        c_evt_engine_set_active(self.engine_c, True)

    def deactivate(self):
        c_evt_engine_set_active(self.engine_c, False)

    def run(self):
        self.c_loop()

    def start(self):
        if c_evt_engine_is_active(self.engine_c):
            self.logger.warning(f'{self} already started!')
            return
        c_evt_engine_set_active(self.engine_c, True)
        self.engine = Thread(target=self.run, name='EventEngine')
        self.engine.start()
        self.logger.info(f'{self} started.')

    def stop(self) -> None:
        if not c_evt_engine_is_active(self.engine_c):
            self.logger.warning('EventEngine already stopped!')
            return

        c_evt_engine_set_active(self.engine_c, False)
        self.engine.join()

    def clear(self) -> None:
        if c_evt_engine_is_active(self.engine_c):
            self.logger.error('EventEngine must be stopped before cleared!')
            return

        # Unregister the engine timer tasks and release the py payload wrappers
        cdef Topic timer_topic
        for timer_topic in list(self.timer.values()):
            c_evt_engine_unregister_timer(self.engine_c, timer_topic.header)
        self.timer_payloads.clear()
        self.timer.clear()

        cdef EventHook hook
        for hook in list(self.exact_hook_map.values()):
            hook.clear()
        for hook in list(self.generic_hook_map.values()):
            hook.clear()
        self.exact_hook_map.clear()
        self.generic_hook_map.clear()

    def get(self, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0) -> MessagePayload:
        cdef evt_message_payload* msg = self.c_get(block, max_spin, timeout)
        if not msg:
            raise Empty()
        return MessagePayload.c_from_header(msg, True)

    def put(self, Topic topic, *args, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0, **kwargs):
        cdef int ret_code = self.c_publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code != evt_ret_code.EVT_RET_OK:
            raise Full()

    def publish(self, Topic topic, tuple args, dict kwargs, bint block=True, size_t max_spin=DEFAULT_MQ_SPIN_LIMIT, double timeout=0.0):
        cdef int ret_code = self.c_publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code != evt_ret_code.EVT_RET_OK:
            raise Full()

    def get_hook(self, Topic topic):
        cdef str key = topic.value
        cdef EventHook hook
        if topic.header.is_exact:
            hook = self.exact_hook_map.get(key)
        else:
            hook = self.generic_hook_map.get(key)
        if hook is None:
            raise KeyError(f'No EventHook registered for {topic.value}')
        return hook

    def register_hook(self, EventHook hook):
        cdef str key = hook.topic.value
        cdef EventHook existing
        if hook.topic.header.is_exact:
            existing = self.exact_hook_map.get(key)
            if existing is not None and existing is not hook:
                raise KeyError(f'Another EventHook already registered for {key}')
            self.exact_hook_map[key] = hook
        else:
            existing = self.generic_hook_map.get(key)
            if existing is not None and existing is not hook:
                raise KeyError(f'Another EventHook already registered for {key}')
            self.generic_hook_map[key] = hook

    def unregister_hook(self, Topic topic) -> EventHook:
        if topic.header.is_exact:
            return self.exact_hook_map.pop(topic.value)
        return self.generic_hook_map.pop(topic.value)

    def register_handler(self, Topic topic, object handler, bint deduplicate=False):
        cdef str key = topic.value
        cdef EventHook hook
        if topic.header.is_exact:
            hook = self.exact_hook_map.get(key)
            if hook is None:
                hook = EventHook(topic, self.logger)
                self.exact_hook_map[key] = hook
        else:
            hook = self.generic_hook_map.get(key)
            if hook is None:
                hook = EventHook(topic, self.logger)
                self.generic_hook_map[key] = hook
        hook.add_handler(handler, None, deduplicate)

    def unregister_handler(self, Topic topic, object handler):
        cdef str key = topic.value
        cdef EventHook hook
        if topic.header.is_exact:
            hook = self.exact_hook_map.get(key)
        else:
            hook = self.generic_hook_map.get(key)
        if hook is None:
            LOGGER.error(f'No EventHook registered for "{topic.value}"')
            return
        hook.remove_handler(handler)
        if len(hook) == 0:
            if topic.header.is_exact:
                self.exact_hook_map.pop(key)
            else:
                self.generic_hook_map.pop(key)

    def event_hooks(self):
        cdef EventHook hook
        for hook in self.exact_hook_map.values():
            yield hook
        for hook in self.generic_hook_map.values():
            yield hook

    def topics(self):
        cdef EventHook hook
        for hook in self.exact_hook_map.values():
            yield hook.topic
        for hook in self.generic_hook_map.values():
            yield hook.topic

    def items(self):
        cdef EventHook hook
        for hook in self.exact_hook_map.values():
            yield (hook.topic, hook)
        for hook in self.generic_hook_map.values():
            yield (hook.topic, hook)

    property capacity:
        def __get__(self):
            return self.engine_c.mq.capacity

    property occupied:
        def __get__(self):
            return c_mq_occupied(self.engine_c.mq)

    property seq_id:
        def __get__(self):
            return c_evt_engine_get_seq_id(self.engine_c)

    property active:
        def __get__(self):
            return c_evt_engine_is_active(self.engine_c)

    property exact_topic_hooks:
        def __get__(self):
            return self.exact_hook_map

    property generic_topic_hooks:
        def __get__(self):
            return self.generic_hook_map

    property exact_topic_hook_map:
        def __get__(self):
            cdef dict out = {}
            cdef EventHook hook
            for hook in self.exact_hook_map.values():
                out[hook.topic] = hook
            return out

    property generic_topic_hook_map:
        def __get__(self):
            cdef dict out = {}
            cdef EventHook hook
            for hook in self.generic_hook_map.values():
                out[hook.topic] = hook
            return out

    # --- Python Interfaces (Timers, backed by the C timer ctx) ---

    def get_timer(self, double interval, datetime activate_time=None) -> Topic:
        cdef Topic topic
        cdef Topic old_topic
        cdef dict kwargs
        cdef datetime trigger_time
        cdef int ret_code

        if not c_evt_engine_is_active(self.engine_c):
            raise RuntimeError('EventEngine must be started before getting timer!')

        if interval in self.timer:
            if activate_time is not None:
                self.logger.debug(f'Timer with interval [{timedelta(seconds=interval)}] already initialized! Argument [activate_time] takes no effect!')
            return self.timer[interval]

        # A different interval replaces the previous timer task
        if self.timer:
            for old_topic in list(self.timer.values()):
                c_evt_engine_unregister_timer(self.engine_c, old_topic.header)
            self.timer_payloads.clear()
            self.timer.clear()

        if interval == 1:
            topic = Topic('EventEngine.Internal.Timer.Second')
        elif interval == 60:
            topic = Topic('EventEngine.Internal.Timer.Minute')
        else:
            topic = Topic.join(['EventEngine', 'Internal', 'Timer', str(interval)])

        kwargs = {'interval': interval}
        if interval not in (1, 60):
            trigger_time = activate_time if activate_time is not None else datetime.now()
            kwargs['trigger_time'] = trigger_time

        # 1. Create the pypayload and pytopic (the py side keeps the payload
        #    alive; the C task only borrows the tail pointer).
        cdef PyObject* py_topic = <PyObject*> topic
        cdef evt_message_payload* payload = c_evt_pypayload_new(<evt_py_topic*> py_topic, NULL, <PyObject*> kwargs, EE_HEAP_ALLOCATOR)
        if not payload:
            raise MemoryError('Failed to allocate timer payload')

        # 2. Remove the self-destruct hook — the C engine must not free it.
        payload.fn_dealloc = NULL

        # 3. Register through the C interface.
        ret_code = c_evt_engine_register_timer(self.engine_c, topic.header, interval, payload.args)
        if ret_code != evt_ret_code.EVT_RET_OK:
            c_evt_pypayload_free(payload)
            raise RuntimeError(f'Failed to register timer with interval [{timedelta(seconds=interval)}]')

        self.timer[interval] = topic
        self.timer_payloads[interval] = MessagePayload.c_from_header(payload, True)

        # 4. Return the pytopic.
        return topic


cdef class EngineTestToolkit:
    """Relays internal C engine / hook-map / timer state to Python for test validation.

    Test-only class. Not declared in any ``.pxd``; not part of the
    public package API.
    """

    @staticmethod
    def get_mq_capacity(EventEngineEx engine):
        """Capacity of the engine's C message queue."""
        return engine.engine_c.mq.capacity

    @staticmethod
    def get_mq_head(EventEngineEx engine):
        """Head index of the engine's C message queue."""
        return engine.engine_c.mq.head

    @staticmethod
    def get_mq_tail(EventEngineEx engine):
        """Tail index of the engine's C message queue."""
        return engine.engine_c.mq.tail

    @staticmethod
    def get_mq_count(EventEngineEx engine):
        """Occupancy counter of the engine's C message queue."""
        return engine.engine_c.mq.count

    @staticmethod
    def get_exact_hook_map_size(EventEngineEx engine):
        """Number of entries in the exact-topic hook map."""
        return len(engine.exact_hook_map)

    @staticmethod
    def get_generic_hook_map_size(EventEngineEx engine):
        """Number of entries in the generic-topic hook map."""
        return len(engine.generic_hook_map)

    @staticmethod
    def get_exact_hook_map_keys(EventEngineEx engine) -> list:
        """Keys of all entries in the exact-topic hook map."""
        return list(engine.exact_hook_map.keys())

    @staticmethod
    def get_generic_hook_map_keys(EventEngineEx engine) -> list:
        """Keys of all entries in the generic-topic hook map."""
        return list(engine.generic_hook_map.keys())

    @staticmethod
    def get_timer_interval(EventEngineEx engine):
        """Interval of the head timer ctx, 0 when none."""
        if not engine.engine_c.timer:
            return 0
        return engine.engine_c.timer.interval_seconds

    @staticmethod
    def get_timer_intervals(EventEngineEx engine) -> list:
        """Intervals of all timer ctxs, in next-due (linked list) order."""
        cdef list out = []
        cdef evt_engine_timer_ctx* ctx = engine.engine_c.timer
        while ctx:
            out.append(ctx.interval_seconds)
            ctx = ctx.next
        return out

    @staticmethod
    def get_timer_task_count(EventEngineEx engine):
        """Number of registered C timer tasks."""
        return engine.engine_c.n_timer

    @staticmethod
    def get_timer_payload_topic(EventEngineEx engine):
        """Topic of the first registered C timer task payload, None when none."""
        if not engine.engine_c.timer or not engine.engine_c.n_timer:
            return None
        return Topic.c_from_header(engine.engine_c.timer.task[0].payload.topic, False)

    @staticmethod
    def register_raw_timer(EventEngineEx engine, Topic topic, double interval) -> MessagePayload:
        """Register a timer task directly on the C engine, bypassing get_timer.

        Test-only: unlike ``get_timer`` this does not replace existing timer
        tasks, enabling multi-timer scenarios. Follows the same pypayload flow
        as ``get_timer`` — on success the returned wrapper keeps the payload
        alive on the Python side (the C task borrows it, fn_dealloc removed);
        on rejection (e.g. duplicate topic) the payload is freed and None
        returned.
        """
        cdef PyObject* py_topic = <PyObject*> topic
        cdef evt_message_payload* payload = c_evt_pypayload_new(<evt_py_topic*> py_topic, NULL, NULL, EE_HEAP_ALLOCATOR)
        if not payload:
            raise MemoryError('Failed to allocate raw timer payload')

        payload.fn_dealloc = NULL
        cdef int ret_code = c_evt_engine_register_timer(engine.engine_c, topic.header, interval, payload.args)
        if ret_code != evt_ret_code.EVT_RET_OK:
            c_evt_pypayload_free(payload)
            return None
        return MessagePayload.c_from_header(payload, True)

    @staticmethod
    def bench_mq_put_get(size_t n, size_t capacity=DEFAULT_MQ_CAPACITY) -> float:
        """Average seconds per put/get round trip on a raw C message queue."""
        cdef message_queue* mq = c_mq_new(capacity, NULL, EE_HEAP_ALLOCATOR)
        if not mq:
            raise MemoryError('Failed to allocate message queue for benchmark')

        cdef Topic topic = Topic('bench.mq.topic')
        cdef PyObject* py_topic = <PyObject*> topic
        cdef evt_message_payload* payload = c_evt_pypayload_new(<evt_py_topic*> py_topic, NULL, NULL, EE_HEAP_ALLOCATOR)
        if not payload:
            c_mq_free(mq)
            raise MemoryError('Failed to allocate payload for benchmark')

        cdef double t0 = perf_counter()
        cdef size_t i
        cdef evt_message_payload* out = NULL
        for i in range(n):
            c_mq_put(mq, payload)
            c_mq_get(mq, &out)
        cdef double elapsed = perf_counter() - t0

        c_evt_pypayload_free(payload)
        c_mq_free(mq)
        return elapsed / n
