import inspect
import traceback

from cpython.datetime cimport datetime, timedelta
from cpython.exc cimport PyErr_Clear, PyErr_Fetch, PyErr_ExceptionMatches
from cpython.object cimport PyCallable_Check
from cpython.ref cimport Py_INCREF, Py_XDECREF
from cpython.time cimport perf_counter
from libc.stdlib cimport calloc, free

from .c_allocator cimport c_heap_new, c_heap_free, c_heap_request, c_heap_recycle, DEFAULT_ALLOC_PAGE
from .c_bytemap cimport MapEntry, c_bytemap_new, c_bytemap_free, c_bytemap_set, c_bytemap_get, c_bytemap_pop, c_bytemap_clear, DEFAULT_BYTEMAP_CAPACITY, C_BYTEMAP_NOT_FOUND
from .c_topic cimport c_topic_match_bool, C_ALLOCATOR
from ..native import LOGGER

LOGGER = LOGGER.getChild('Event')


cdef class PyMessagePayload:
    def __cinit__(self, bint alloc=False):
        if not alloc:
            return

        self.header = <MessagePayload*> calloc(1, sizeof(MessagePayload))
        if not self.header:
            raise MemoryError('Failed to allocate memory')
        self.header.topic = NULL
        self.header.args = NULL
        self.header.kwargs = NULL
        self.header.seq_id = 0

        self.owner = True
        self.args_owner = False
        self.kwargs_owner = False

    def __dealloc__(self):
        cdef PyObject* args
        cdef PyObject* kwargs

        if self.args_owner and self.header and self.header.args:
            args = <PyObject*> self.header.args
            self.header.args = NULL
            Py_XDECREF(args)

        if self.kwargs_owner and self.header and self.header.kwargs:
            kwargs = <PyObject*> self.header.kwargs
            self.header.kwargs = NULL
            Py_XDECREF(kwargs)

        if self.owner and self.header:
            free(self.header)
            self.header = NULL

    def __repr__(self):
        if not self.header:
            return '<PyMessagePayload uninitialized>'
        if self.header.topic:
            return f'<PyMessagePayload "{self.topic.value}">(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'
        return f'<PyMessagePayload NO_TOPIC>(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'

    @staticmethod
    cdef PyMessagePayload c_from_header(MessagePayload* header, bint owner=False, bint args_owner=False, bint kwargs_owner=False):
        # Create a wrapper around an existing header pointer.
        cdef PyMessagePayload instance = PyMessagePayload.__new__(PyMessagePayload, alloc=False)
        instance.header = header
        instance.owner = owner
        instance.args_owner = args_owner
        instance.kwargs_owner = kwargs_owner
        return instance

    property topic:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef Topic* topic = self.header.topic
            if not topic:
                return None
            return PyTopic.c_from_header(topic)

        def __set__(self, PyTopic topic):
            LOGGER.warning(f'[debug-only] Setting topic {topic}, This WILL causes memory leak!')
            topic.owner = False
            self.header.topic = topic.header

    property args:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef PyObject* args = <PyObject*> self.header.args
            if not args:
                return None
            return <object> args

        def __set__(self, tuple args):
            LOGGER.warning(f'[debug-only] Setting args to payload. This WILL causes memory leak!')
            Py_INCREF(args)
            self.header.args = <void*> <PyObject*> args

    property kwargs:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef PyObject* kwargs = <PyObject*> self.header.kwargs
            if not kwargs:
                return None
            return <object> kwargs

        def __set__(self, dict kwargs):
            LOGGER.warning(f'[debug-only] Setting kwargs to payload. This WILL causes memory leak!')
            Py_INCREF(kwargs)
            self.header.kwargs = <void*> <PyObject*> kwargs

    property seq_id:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Not initialized!')

            return self.header.seq_id


cdef tuple C_INTERNAL_EMPTY_ARGS = ()

cdef dict C_INTERNAL_EMPTY_KWARGS = {}

cdef str TOPIC_FIELD_NAME = 'topic'

cdef str TOPIC_UNEXPECTED_ERROR = f"an unexpected keyword argument '{TOPIC_FIELD_NAME}'"


cdef class EventHook:
    def __cinit__(self, PyTopic topic, object logger=None):
        self.topic = topic
        self.logger = LOGGER.getChild(f'EventHook.{topic}') if logger is None else logger
        self.handlers_no_topic = NULL
        self.handlers_with_topic = NULL

    def __dealloc__(self):
        EventHook.c_free_handlers(self.handlers_no_topic)
        self.handlers_no_topic = NULL

        EventHook.c_free_handlers(self.handlers_with_topic)
        self.handlers_with_topic = NULL

    @staticmethod
    cdef inline void c_free_handlers(EventHandler* handlers):
        cdef EventHandler* handler = handlers
        cdef EventHandler* next_handler
        while handler:
            next_handler = handler.next
            if handler.handler:
                Py_XDECREF(handler.handler)
                handler.handler = NULL
            free(handler)
            handler = next_handler

    cdef void c_safe_call_no_topic(self, EventHandler* handler, tuple args, dict kwargs):
        cdef object py_callable = <object> handler.handler
        cdef PyObject* res = PyObject_Call(py_callable, args, kwargs)
        if res:
            Py_XDECREF(res)
            return

        # Fetch the current Python exception (steals references; clears the indicator)
        cdef PyObject* etype = NULL
        cdef PyObject* evalue = NULL
        cdef PyObject* etrace = NULL
        cdef object formatted

        PyErr_Fetch(&etype, &evalue, &etrace)
        formatted = traceback.format_exception(<object> etype, (<object> evalue) if evalue else None, (<object> etrace) if etrace else None)
        self.logger.error("".join(formatted))
        Py_XDECREF(etype)
        Py_XDECREF(evalue)
        Py_XDECREF(etrace)
        PyErr_Clear()

    cdef void c_safe_call_with_topic(self, EventHandler* handler, tuple args, dict kwargs):
        cdef object py_callable = <object> handler.handler
        cdef PyObject* res = PyObject_Call(py_callable, args, kwargs)

        if res:
            Py_XDECREF(res)
            return
        cdef PyObject* etype = NULL
        cdef PyObject* evalue = NULL
        cdef PyObject* etrace = NULL
        cdef object formatted

        PyErr_Fetch(&etype, &evalue, &etrace)
        if (PyErr_ExceptionMatches(TypeError)
                and isinstance(<object> evalue, str)
                and (<str> evalue).endswith(TOPIC_UNEXPECTED_ERROR)
                and kwargs and TOPIC_FIELD_NAME in kwargs):
            # Retry without the topic kwarg
            Py_XDECREF(etype)
            Py_XDECREF(evalue)
            Py_XDECREF(etrace)
            PyErr_Clear()
            kwargs.pop(TOPIC_FIELD_NAME)
            EventHook.c_safe_call_no_topic(self, handler, args, kwargs)
            return

        formatted = traceback.format_exception(<object> etype, (<object> evalue) if evalue else None, (<object> etrace) if etrace else None)
        self.logger.error("".join(formatted))
        Py_XDECREF(etype)
        Py_XDECREF(evalue)
        Py_XDECREF(etrace)
        PyErr_Clear()

    cdef inline void c_trigger_no_topic(self, MessagePayload* msg):
        cdef PyObject* args_ptr = <PyObject*> msg.args
        cdef PyObject* kwargs_ptr = <PyObject*> msg.kwargs
        cdef EventHandler* handler = self.handlers_no_topic

        cdef tuple args
        if not args_ptr:
            args = C_INTERNAL_EMPTY_ARGS
        else:
            args = <tuple> args_ptr

        cdef dict kwargs
        if not kwargs_ptr:
            kwargs = C_INTERNAL_EMPTY_KWARGS
        else:
            kwargs = <dict> kwargs_ptr

        while handler:
            self.c_safe_call_no_topic(handler, args, kwargs)
            handler = handler.next

    cdef inline void c_trigger_with_topic(self, MessagePayload* msg):
        cdef PyObject* args_ptr = <PyObject*> msg.args
        cdef PyObject* kwargs_ptr = <PyObject*> msg.kwargs
        cdef Topic* topic = msg.topic
        cdef EventHandler* handler = self.handlers_with_topic

        cdef tuple args
        if not args_ptr:
            args = C_INTERNAL_EMPTY_ARGS
        else:
            args = <tuple> args_ptr

        cdef dict kwargs
        if not kwargs_ptr:
            kwargs = {TOPIC_FIELD_NAME: PyTopic.c_from_header(topic, False)}
        else:
            kwargs = <dict> kwargs_ptr
            if TOPIC_FIELD_NAME not in kwargs:
                kwargs[TOPIC_FIELD_NAME] = PyTopic.c_from_header(topic, False)

        while handler:
            self.c_safe_call_with_topic(handler, args, kwargs)
            handler = handler.next

    cdef EventHandler* c_add_handler(self, object py_callable, bint with_topic, bint deduplicate):
        if not PyCallable_Check(py_callable):
            raise ValueError('Callback handler must be callable')

        cdef PyObject* handler = <PyObject*> py_callable
        cdef EventHandler* node = self.handlers_with_topic if with_topic else self.handlers_no_topic
        cdef EventHandler* prev = NULL
        cdef bint found = False

        # Walk list to detect duplicates and position at tail
        while node:
            if node.handler == handler:
                found = True
                if deduplicate:
                    return NULL
                else:
                    try:
                        self.logger.warning(f'Handler {py_callable} already registered in {self}. Adding again will be called multiple times when triggered.')
                    except Exception:
                        pass
            prev = node
            node = node.next

        # Allocate new node
        node = <EventHandler*> calloc(1, sizeof(EventHandler))
        if not node:
            raise MemoryError('Failed to allocate EventHandler')
        Py_INCREF(<object> handler)  # hold a reference from the list
        node.handler = handler
        node.next = NULL

        if prev == NULL:
            if with_topic:
                self.handlers_with_topic = node
            else:
                self.handlers_no_topic = node
        else:
            prev.next = node
        return node

    cdef EventHandler* c_remove_handler(self, object py_callable):
        cdef PyObject* handler = <PyObject*> py_callable
        cdef EventHandler* node = self.handlers_no_topic
        cdef EventHandler* prev = NULL

        while node:
            if node.handler == handler:
                # unlink node
                if prev:
                    prev.next = node.next
                else:
                    self.handlers_no_topic = node.next

                if node.handler:
                    Py_XDECREF(node.handler)  # drop the list's reference
                    node.handler = NULL
                # free(node)
                return node
            prev = node
            node = node.next

        node = self.handlers_with_topic
        prev = NULL
        while node:
            if node.handler == handler:
                # unlink node
                if prev:
                    prev.next = node.next
                else:
                    self.handlers_with_topic = node.next

                if node.handler:
                    Py_XDECREF(node.handler)
                    node.handler = NULL
                # free(node)
                return node
            prev = node
            node = node.next
        return NULL

    def __call__(self, PyMessagePayload msg):
        self.c_trigger_no_topic(msg.header)
        self.c_trigger_with_topic(msg.header)

    def __iadd__(self, object py_callable):
        self.add_handler(py_callable, True)
        return self

    def __isub__(self, object py_callable):
        cdef EventHandler* node = self.c_remove_handler(py_callable)
        if node:
            free(node)
        return self

    def __len__(self):
        cdef int count = 0
        cdef EventHandler* node = self.handlers_no_topic
        while node:
            count += 1
            node = node.next

        node = self.handlers_with_topic
        while node:
            count += 1
            node = node.next
        return count

    def __repr__(self):
        if self.topic:
            return f'<{self.__class__.__name__} "{self.topic.value}">(handlers={len(self)})'
        return f'<{self.__class__.__name__} NO_TOPIC>(handlers={len(self)})'

    def __iter__(self):
        return self.handlers.__iter__()

    def __contains__(self, object py_callable):
        cdef PyObject* target = <PyObject*> py_callable
        cdef EventHandler* node = self.handlers_no_topic
        while node:
            if node.handler == target:
                return True
            node = node.next

        node = self.handlers_with_topic
        while node:
            if node.handler == target:
                return True
            node = node.next
        return False

    def trigger(self, PyMessagePayload msg):
        self.c_trigger_no_topic(msg.header)
        self.c_trigger_with_topic(msg.header)

    def add_handler(self, object py_callable, bint deduplicate=False):
        cdef object sig = inspect.signature(py_callable)
        cdef object param
        cdef bint with_topic = False

        for param in sig.parameters.values():
            if param.name == TOPIC_FIELD_NAME or param.kind == inspect.Parameter.VAR_KEYWORD:
                with_topic = True
                break

        self.c_add_handler(py_callable, with_topic, deduplicate)

    def remove_handler(self, object py_callable):
        cdef EventHandler* node = self.c_remove_handler(py_callable)
        if node:
            free(node)
        return self

    def clear(self):
        EventHook.c_free_handlers(self.handlers_no_topic)
        self.handlers_no_topic = NULL

        EventHook.c_free_handlers(self.handlers_with_topic)
        self.handlers_with_topic = NULL

    property handlers:
        def __get__(self):
            cdef EventHandler* node = self.handlers_no_topic
            cdef list out = []
            while node:
                if node.handler:
                    out.append(<object> node.handler)
                node = node.next

            node = self.handlers_with_topic
            while node:
                if node.handler:
                    out.append(<object> node.handler)
                node = node.next
            return out


cdef class EventHookEx(EventHook):
    def __cinit__(self, PyTopic topic, object logger=None):
        self.stats_mapping = c_bytemap_new(DEFAULT_BYTEMAP_CAPACITY, NULL)
        if not self.stats_mapping:
            raise MemoryError(f'Failed to allocate ByteMap for {self.__class__.__name__} stats mapping.')

    def __dealloc__(self):
        cdef MapEntry* entry
        if self.stats_mapping:
            entry = self.stats_mapping.first
            while entry:
                if entry.value:
                    free(entry.value)
                    entry.value = NULL
                entry = entry.next
            c_bytemap_free(self.stats_mapping, 1)

    cdef EventHandler* c_add_handler(self, object py_callable, bint with_topic, bint deduplicate):
        cdef EventHandler* node = EventHook.c_add_handler(self, py_callable, with_topic, deduplicate)
        if not node:
            return node
        cdef HandlerStats* stats = <HandlerStats*> calloc(1, sizeof(HandlerStats))
        c_bytemap_set(self.stats_mapping, <char*> node, sizeof(EventHandler), <void*> stats)
        return node

    cdef EventHandler* c_remove_handler(self, object py_callable):
        cdef EventHandler* node = EventHook.c_remove_handler(self, py_callable)
        if not node:
            return node
        c_bytemap_pop(self.stats_mapping, <char*> node, sizeof(EventHandler), NULL)
        return node

    cdef void c_safe_call_no_topic(self, EventHandler* handler, tuple args, dict kwargs):
        cdef void* stats = c_bytemap_get(self.stats_mapping, <char*> handler, sizeof(EventHandler))
        if stats == C_BYTEMAP_NOT_FOUND or not stats:
            EventHook.c_safe_call_no_topic(self, handler, args, kwargs)
            return
        cdef HandlerStats* handler_stats = <HandlerStats*> stats
        cdef double start_time = perf_counter()
        EventHook.c_safe_call_no_topic(self, handler, args, kwargs)
        handler_stats.calls += 1
        handler_stats.total_time += perf_counter() - start_time

    cdef void c_safe_call_with_topic(self, EventHandler* handler, tuple args, dict kwargs):
        cdef void* stats = c_bytemap_get(self.stats_mapping, <char*> handler, sizeof(EventHandler))
        if stats == C_BYTEMAP_NOT_FOUND or not stats:
            EventHook.c_safe_call_with_topic(self, handler, args, kwargs)
            return
        cdef HandlerStats* handler_stats = <HandlerStats*> stats
        cdef double start_time = perf_counter()
        EventHook.c_safe_call_with_topic(self, handler, args, kwargs)
        handler_stats.calls += 1
        handler_stats.total_time += perf_counter() - start_time

    def get_stats(self, object py_callable):
        """
        Return a dict with stats for the given handler, or None if not found.
        """
        cdef EventHandler* node = self.handlers_no_topic
        cdef void* stats
        cdef HandlerStats* handler_stats
        while node:
            if node.handler == <PyObject*> py_callable:
                stats = c_bytemap_get(self.stats_mapping, <char*> node, sizeof(EventHandler))
                if stats == C_BYTEMAP_NOT_FOUND or not stats:
                    return None
                handler_stats = <HandlerStats*> stats
                return {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next
        node = self.handlers_with_topic
        while node:
            if node.handler == <PyObject*> py_callable:
                stats = c_bytemap_get(self.stats_mapping, <char*> node, sizeof(EventHandler))
                if stats == C_BYTEMAP_NOT_FOUND or not stats:
                    return None
                handler_stats = <HandlerStats*> stats
                return {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next
        return None

    @property
    def stats(self):
        """
        Yields (py_callable, dict) for all handlers.
        """
        cdef EventHandler* node
        cdef void* stats
        cdef HandlerStats* handler_stats

        # no_topic handlers
        node = self.handlers_no_topic
        while node:
            if node.handler:
                stats = c_bytemap_get(self.stats_mapping, <char*> node, sizeof(EventHandler))
                if stats != C_BYTEMAP_NOT_FOUND and stats:
                    handler_stats = <HandlerStats*> stats
                    yield <object> node.handler, {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next

        # with_topic handlers
        node = self.handlers_with_topic
        while node:
            if node.handler:
                stats = c_bytemap_get(self.stats_mapping, <char*> node, sizeof(EventHandler))
                if stats != C_BYTEMAP_NOT_FOUND and stats:
                    handler_stats = <HandlerStats*> stats
                    yield <object> node.handler, {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next


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
        self.timer = {}

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
            ret_code = c_mq_get_hybrid(mq, &msg, DEFAULT_MQ_SPIN_LIMIT, DEFAULT_MQ_TIMEOUT_SECONDS)
            if ret_code != 0:
                continue
            self.c_trigger(msg)
            c_heap_recycle(self.payload_allocator, <void*> msg)

    cdef inline void c_timer(self, double interval, PyTopic topic, datetime activate_time):
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
            self.c_publish(topic, C_INTERNAL_EMPTY_ARGS, kwargs, True, 0.0)

            while scheduled_time < datetime.now():
                scheduled_time += timedelta(seconds=interval)
            kwargs['trigger_time'] = scheduled_time

    cdef inline void c_publish(self, PyTopic topic, tuple args, dict kwargs, bint block, double timeout):
        # Step 0: Request payload buffer
        cdef MessagePayload* payload = <MessagePayload*> c_heap_request(self.payload_allocator, sizeof(MessagePayload))

        # Step 1: Assembling payload
        payload.topic = topic.header
        payload.args = <PyObject*> args
        payload.kwargs = <PyObject*> kwargs
        payload.seq_id = self.seq_id

        # Step 2: Send the payload
        if block:
            c_mq_put_hybrid(self.mq, payload, DEFAULT_MQ_SPIN_LIMIT, timeout)
        else:
            c_mq_put(self.mq, payload)

        # Step 3: Update reference count
        self.seq_id += 1
        Py_INCREF(args)
        Py_INCREF(kwargs)

    cdef inline void c_trigger(self, MessagePayload* msg):
        cdef Topic* msg_topic = msg.topic
        # Step 1: Match exact_topic_hooks
        cdef void* hook_ptr
        cdef EventHook event_hook

        hook_ptr = c_bytemap_get(self.exact_topic_hooks, msg_topic.key, msg_topic.key_len)
        if hook_ptr:
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

        # Step 3: Decrease ref counts of args and kwargs
        if msg.args:
            Py_XDECREF(<PyObject*> msg.args)
            msg.args = NULL
        if msg.kwargs:
            Py_XDECREF(<PyObject*> msg.kwargs)
            msg.kwargs = NULL

    cdef inline void c_register_hook(self, EventHook hook):
        cdef Topic* topic_ptr = hook.topic.header
        cdef void* existing_hook_ptr
        cdef ByteMapHeader* hook_map

        if topic_ptr.is_exact:
            hook_map = self.exact_topic_hooks
        else:
            hook_map = self.generic_topic_hooks

        existing_hook_ptr = c_bytemap_get(hook_map, topic_ptr.key, topic_ptr.key_len)
        if existing_hook_ptr != C_BYTEMAP_NOT_FOUND and existing_hook_ptr != <void*> <PyObject*> hook:
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

        c_bytemap_pop(hook_map, <char*> topic_ptr.key, topic_ptr.key_len, &existing_hook_ptr)
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
        if hook_ptr == C_BYTEMAP_NOT_FOUND:
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
        if hook_ptr == C_BYTEMAP_NOT_FOUND:
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

    def run(self):
        self.c_loop()

    def run_timer(self, double interval, PyTopic topic, datetime activate_time=None):
        self.c_timer(interval, topic, activate_time)

    def minute_timer(self, PyTopic topic):
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
            self.c_publish(topic, C_INTERNAL_EMPTY_ARGS, kwargs, True, 0.0)

    def second_timer(self, PyTopic topic):
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
            self.c_publish(topic, C_INTERNAL_EMPTY_ARGS, kwargs, True, 0.0)

    def start(self):
        from threading import Thread

        if self.active:
            self.logger.warning(f'{self} already started!')
            return

        self.active = True
        self.engine = Thread(target=self.run, name='EventEngine')
        self.engine.start()

    def get_timer(self, double interval, datetime activate_time=None) -> PyTopic:
        from threading import Thread

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
        if not self.active:
            self.logger.warning('EventEngine already stopped!')
            return

        self.active = False
        self.engine.join()

        for timer in self.timer.values():
            timer.join()

    def clear(self) -> None:
        if self.active:
            self.logger.error('EventEngine must be stopped before cleared!')
            return

        self.c_clear()

        for t in self.timer.values():
            t.join(timeout=0)
        self.timer.clear()

    def put(self, PyTopic topic, *args, bint block=True, double timeout=0.0, **kwargs):
        self.publish(topic, args, kwargs, block, timeout)

    def publish(self, PyTopic topic, tuple args, dict kwargs, bint block=True, double timeout=0.0):
        self.c_publish(topic, args, kwargs, block, timeout)

    def register_hook(self, EventHook hook):
        self.c_register_hook(hook)

    def unregister_hook(self, PyTopic topic) -> EventHook:
        return self.c_unregister_hook(topic)

    def register_handler(self, PyTopic topic, object py_callable, bint deduplicate=False):
        self.c_register_handler(topic, py_callable, deduplicate)

    def unregister_handler(self, PyTopic topic, object py_callable):
        self.c_unregister_handler(topic, py_callable)

    property capacity:
        def __get__(self):
            return self.mq.capacity
