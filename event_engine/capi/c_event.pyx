import inspect
import traceback

from cpython.exc cimport PyErr_Clear, PyErr_Fetch, PyErr_GivenExceptionMatches
from cpython.object cimport PyCallable_Check
from cpython.ref cimport Py_INCREF, Py_XDECREF
from cpython.time cimport perf_counter
from libc.stdlib cimport calloc, free

from ..base import LOGGER

LOGGER = LOGGER.getChild('Event')


cdef class MessagePayload:
    def __cinit__(self, bint alloc=False):
        if not alloc:
            return

        self.header = <evt_message_payload*> calloc(1, sizeof(evt_message_payload))
        if not self.header:
            raise MemoryError('Failed to allocate memory')
        self.header.topic = NULL
        self.header.args = NULL
        self.header.kwargs = NULL
        self.header.seq_id = 0
        self.header.allocator = NULL

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

        cdef heap_allocator* allocator = self.header.allocator
        if self.owner and self.header:
            if allocator:
                c_heap_free(self.header, <pthread_mutex_t*> &allocator.lock)
            else:
                free(self.header)
            self.header = NULL

    def __repr__(self):
        if not self.header:
            return '<MessagePayload uninitialized>'
        if self.header.topic:
            return f'<MessagePayload "{self.topic.value}">(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'
        return f'<MessagePayload NO_TOPIC>(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'

    @staticmethod
    cdef MessagePayload c_from_header(evt_message_payload* header, bint owner=False, bint args_owner=False, bint kwargs_owner=False):
        # Create a wrapper around an existing header pointer.
        cdef MessagePayload instance = MessagePayload.__new__(MessagePayload, alloc=False)
        instance.header = header
        instance.owner = owner
        instance.args_owner = args_owner
        instance.kwargs_owner = kwargs_owner
        return instance

    property topic:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef evt_topic* topic = self.header.topic
            if not topic:
                return None
            return Topic.c_from_header(topic, False)

        def __set__(self, Topic topic):
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
            Py_INCREF(kwargs)
            self.header.kwargs = <void*> <PyObject*> kwargs

    property seq_id:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Not initialized!')
            return self.header.seq_id

        def __set__(self, uint64_t seq_id):
            if not self.header:
                raise RuntimeError('Not initialized!')
            self.header.seq_id = seq_id


cdef tuple C_INTERNAL_EMPTY_ARGS = ()

cdef dict C_INTERNAL_EMPTY_KWARGS = {}

cdef str TOPIC_FIELD_NAME = 'topic'

cdef str TOPIC_UNEXPECTED_ERROR = f"an unexpected keyword argument '{TOPIC_FIELD_NAME}'"


cdef class EventHook:
    def __cinit__(self, Topic topic, object logger=None, bint retry_on_unexpected_topic=False):
        self.topic = topic
        self.logger = LOGGER.getChild(f'EventHook.{topic}') if logger is None else logger
        self.retry_on_unexpected_topic = retry_on_unexpected_topic
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
        formatted = traceback.format_exception(<object> etype, (<object> evalue) if evalue else None, (<object> etrace) if etrace else None)
        if (self.retry_on_unexpected_topic
                and evalue is not NULL
                and PyErr_GivenExceptionMatches(<object> evalue, TypeError)
                and str(<object> evalue).endswith(TOPIC_UNEXPECTED_ERROR)
                and kwargs and TOPIC_FIELD_NAME in kwargs):
            LOGGER.warning("".join(formatted))
            LOGGER.warning(f'Retrying without {TOPIC_FIELD_NAME} kwargs...')
            # Retry without the topic kwarg
            Py_XDECREF(etype)
            Py_XDECREF(evalue)
            Py_XDECREF(etrace)
            PyErr_Clear()
            kwargs.pop(TOPIC_FIELD_NAME)
            EventHook.c_safe_call_no_topic(self, handler, args, kwargs)
            return

        self.logger.error("".join(formatted))
        Py_XDECREF(etype)
        Py_XDECREF(evalue)
        Py_XDECREF(etrace)
        PyErr_Clear()

    cdef inline void c_trigger_no_topic(self, evt_message_payload* msg):
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

    cdef inline void c_trigger_with_topic(self, evt_message_payload* msg):
        cdef PyObject* args_ptr = <PyObject*> msg.args
        cdef PyObject* kwargs_ptr = <PyObject*> msg.kwargs
        cdef evt_topic* topic = msg.topic
        cdef EventHandler* handler = self.handlers_with_topic

        cdef tuple args
        if not args_ptr:
            args = C_INTERNAL_EMPTY_ARGS
        else:
            args = <tuple> args_ptr

        cdef dict kwargs
        if not kwargs_ptr:
            kwargs = {TOPIC_FIELD_NAME: Topic.c_from_header(topic, False)}
        else:
            kwargs = (<dict> kwargs_ptr).copy()
            if TOPIC_FIELD_NAME not in kwargs:
                kwargs[TOPIC_FIELD_NAME] = Topic.c_from_header(topic, False)

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

    def __call__(self, MessagePayload msg):
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

    def trigger(self, MessagePayload msg):
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
    def __cinit__(self, Topic topic, object logger=None, bint retry_on_unexpected_topic=False):
        self.stats_mapping = c_strmap_new(0, NULL, 0)
        if not self.stats_mapping:
            raise MemoryError(f'Failed to allocate ByteMap for {self.__class__.__name__} stats mapping.')

    def __dealloc__(self):
        cdef strmap_entry* entry
        if self.stats_mapping:
            entry = self.stats_mapping.first
            while entry:
                if entry.value:
                    free(entry.value)
                    entry.value = NULL
                entry = entry.next
            c_strmap_free(self.stats_mapping, 1, 1)

    cdef EventHandler* c_add_handler(self, object py_callable, bint with_topic, bint deduplicate):
        cdef EventHandler* node = EventHook.c_add_handler(self, py_callable, with_topic, deduplicate)
        if not node:
            return node
        cdef HandlerStats* stats = <HandlerStats*> calloc(1, sizeof(HandlerStats))
        c_strmap_set(self.stats_mapping, <char*> node, sizeof(EventHandler), <void*> stats, NULL, 1)
        return node

    cdef EventHandler* c_remove_handler(self, object py_callable):
        cdef EventHandler* node = EventHook.c_remove_handler(self, py_callable)
        if not node:
            return node
        c_strmap_pop(self.stats_mapping, <char*> node, sizeof(EventHandler), NULL, 1)
        return node

    cdef void c_safe_call_no_topic(self, EventHandler* handler, tuple args, dict kwargs):
        cdef HandlerStats* handler_stats = NULL
        cdef int ret_code = c_strmap_get(self.stats_mapping, <char*> handler, sizeof(EventHandler), <void**> &handler_stats)
        if not handler_stats:
            EventHook.c_safe_call_no_topic(self, handler, args, kwargs)
        cdef double start_time = perf_counter()
        EventHook.c_safe_call_no_topic(self, handler, args, kwargs)
        handler_stats.calls += 1
        handler_stats.total_time += perf_counter() - start_time

    cdef void c_safe_call_with_topic(self, EventHandler* handler, tuple args, dict kwargs):
        cdef HandlerStats* handler_stats = NULL
        cdef int ret_code = c_strmap_get(self.stats_mapping, <char*> handler, sizeof(EventHandler), <void**> &handler_stats)
        if not handler_stats:
            EventHook.c_safe_call_with_topic(self, handler, args, kwargs)
        cdef double start_time = perf_counter()
        EventHook.c_safe_call_with_topic(self, handler, args, kwargs)
        handler_stats.calls += 1
        handler_stats.total_time += perf_counter() - start_time

    def get_stats(self, object py_callable):
        """
        Return a dict with stats for the given handler, or None if not found.
        """
        cdef EventHandler* node = self.handlers_no_topic
        cdef HandlerStats* handler_stats = NULL
        while node:
            if node.handler == <PyObject*> py_callable:
                c_strmap_get(self.stats_mapping, <char*> node, sizeof(EventHandler), <void**> &handler_stats)
                if not handler_stats:
                    return None
                return {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next
        node = self.handlers_with_topic
        while node:
            if node.handler == <PyObject*> py_callable:
                c_strmap_get(self.stats_mapping, <char*> node, sizeof(EventHandler), <void**> &handler_stats)
                if not handler_stats:
                    return None
                return {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next
        return None

    @property
    def stats(self):
        """
        Yields (py_callable, dict) for all handlers.
        """
        cdef EventHandler* node
        cdef HandlerStats* handler_stats
        cdef int ret_code

        # no_topic handlers
        node = self.handlers_no_topic
        while node:
            if node.handler:
                ret_code = c_strmap_get(self.stats_mapping, <char*> node, sizeof(EventHandler), <void**> &handler_stats)
                if ret_code == STRMAP_OK and handler_stats:
                    yield <object> node.handler, {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next

        # with_topic handlers
        node = self.handlers_with_topic
        while node:
            if node.handler:
                ret_code = c_strmap_get(self.stats_mapping, <char*> node, sizeof(EventHandler), <void**> &handler_stats)
                if ret_code == STRMAP_OK and handler_stats:
                    yield <object> node.handler, {'calls': handler_stats.calls, 'total_time': handler_stats.total_time}
            node = node.next
