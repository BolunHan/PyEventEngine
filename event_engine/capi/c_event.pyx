import inspect
import traceback

from cpython.exc cimport PyErr_Clear, PyErr_Fetch
from cpython.ref cimport Py_XINCREF, Py_XDECREF
from cpython.time cimport perf_counter
from libc.stdlib cimport calloc, free

from ..base import LOGGER

LOGGER = LOGGER.getChild('Event')


cdef tuple EMPTY_ARGS = ()
cdef str TOPIC_FIELD_NAME = 'topic'


cdef inline evt_message_payload* c_evt_payload_new(heap_allocator* allocator, Topic topic, tuple args, dict kwargs, int with_lock):
    cdef evt_message_payload* c_payload
    cdef size_t payload_size = sizeof(evt_message_payload) + sizeof(evt_py_payload)

    if allocator:
        c_payload = <evt_message_payload*> c_heap_request(allocator, payload_size, 1, &allocator.lock if with_lock else NULL)
    else:
        c_payload = <evt_message_payload*> calloc(1, payload_size)

    if not c_payload:
        return NULL

    cdef evt_py_payload* py_payload = <evt_py_payload*> (c_payload + 1)
    cdef PyObject* kwargs_aggregated = PyDict_Copy(<PyObject*> kwargs)
    PyDict_SetDefault(kwargs_aggregated, <PyObject*> TOPIC_FIELD_NAME, <PyObject*> topic)

    py_payload.py_topic = <PyObject*> topic
    py_payload.py_args = <PyObject*> args
    py_payload.py_kwargs = <PyObject*> kwargs
    py_payload.py_kwargs_aggregated = kwargs_aggregated

    Py_XINCREF(<PyObject*> topic)
    Py_XINCREF(<PyObject*> args)
    Py_XINCREF(<PyObject*> kwargs)
    # Py_XINCREF(<PyObject*> kwargs_aggregated)

    c_payload.args = py_payload
    c_payload.topic = topic.header
    c_payload.allocator = allocator
    return c_payload


cdef inline void c_evt_payload_free(evt_message_payload* payload, int with_lock):
    cdef heap_allocator* allocator = payload.allocator
    cdef evt_py_payload* py_payload = <evt_py_payload*> (payload + 1)

    Py_XDECREF(py_payload.py_topic)
    Py_XDECREF(py_payload.py_args)
    Py_XDECREF(py_payload.py_kwargs)
    Py_XDECREF(py_payload.py_kwargs_aggregated)

    if allocator:
        c_heap_free(payload, &allocator.lock if with_lock else NULL)
    else:
        free(payload)


cdef class MessagePayload:
    def __init__(self, Topic topic, tuple args, dict kwargs):
        self.header = c_evt_payload_new(NULL, topic, args, kwargs, 1)
        if not self.header:
            raise MemoryError('Failed to allocate memory for evt_message_payload')
        self.owner = True

    def __dealloc__(self):
        if not self.owner:
            return

        if self.header:
            c_evt_payload_free(self.header, 1)

    @staticmethod
    cdef MessagePayload c_from_header(evt_message_payload* payload, bint owner=False):
        cdef MessagePayload instance = MessagePayload.__new__(MessagePayload)
        instance.header = payload
        instance.owner = owner
        return instance

    def __repr__(self):
        if not self.header:
            return '<MessagePayload uninitialized>'
        if self.header.topic:
            return f'<MessagePayload "{self.topic.value}">(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'
        return f'<MessagePayload NO_TOPIC>(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'

    property topic:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Uninitialized c payload')
            if not self.header.args:
                raise RuntimeError('Uninitialized python payload')
            cdef evt_py_payload* py_payload = <evt_py_payload*> self.header.args
            cdef PyObject* py_topic = py_payload.py_topic
            if py_topic:
                Py_XINCREF(py_topic)
                return <Topic> py_topic
            cdef evt_topic* topic = self.header.topic
            if topic:
                return Topic.c_from_header(topic, False)
            return None

    property args:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Uninitialized c payload')
            if not self.header.args:
                raise RuntimeError('Uninitialized python payload')
            cdef evt_py_payload* py_payload = <evt_py_payload*> self.header.args
            cdef PyObject* py_args = py_payload.py_args
            if py_args:
                Py_XINCREF(py_args)
                return <tuple> py_args
            return None

    property kwargs:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Uninitialized c payload')
            if not self.header.args:
                raise RuntimeError('Uninitialized python payload')
            cdef evt_py_payload* py_payload = <evt_py_payload*> self.header.args
            cdef PyObject* py_kwargs = py_payload.py_kwargs
            if py_kwargs:
                Py_XINCREF(py_kwargs)
                return <dict> py_kwargs
            return None

    property kwargs_with_topic:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Uninitialized c payload')
            if not self.header.args:
                raise RuntimeError('Uninitialized python payload')
            cdef evt_py_payload* py_payload = <evt_py_payload*> self.header.args
            cdef PyObject* py_kwargs_aggregated = py_payload.py_kwargs_aggregated
            if py_kwargs_aggregated:
                Py_XINCREF(py_kwargs_aggregated)
                return <dict> py_kwargs_aggregated
            return None

    property seq_id:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Uninitialized c payload')
            return self.header.seq_id

        def __set__(self, uint64_t seq_id):
            if not self.header:
                raise RuntimeError('Uninitialized c payload')
            self.header.seq_id = seq_id


cdef class EventHook:
    def __cinit__(self, Topic topic, object logger=None):
        self.header = c_evt_hook_new(topic.header)
        if not self.header:
            raise MemoryError(f'Failed to allocate memory for {self.__class__.__name__}')
        self.callables = NULL
        self.topic = topic
        self.logger = LOGGER.getChild(f'EventHook.{topic}') if logger is None else logger

    def __dealloc__(self):
        self.c_free_py_callable()
        if self.header:
            c_evt_hook_free(self.header)

    @staticmethod
    cdef inline void c_invoke_py_callable(evt_message_payload* payload, void* user_data) with gil:
        cdef evt_py_callable* ctx = <evt_py_callable*> user_data
        cdef bint with_topic = ctx.with_topic
        cdef evt_py_payload* py_payload = <evt_py_payload*> payload.args

        cdef PyObject* fn = ctx.fn
        cdef PyObject* args = py_payload.py_args
        cdef PyObject* kwargs = py_payload.py_kwargs_aggregated if with_topic else py_payload.py_kwargs
        cdef PyObject* res = PyObject_Call(fn, args, kwargs)

        if res:
            Py_XDECREF(res)
            return

        # Fetch the current Python exception (steals references; clears the indicator)
        cdef PyObject* etype = NULL
        cdef PyObject* evalue = NULL
        cdef PyObject* etrace = NULL
        cdef object logger = <object> ctx.logger
        cdef object formatted

        PyErr_Fetch(&etype, &evalue, &etrace)
        formatted = traceback.format_exception(<object> etype, (<object> evalue) if evalue else None, (<object> etrace) if etrace else None)
        logger.error("".join(formatted))
        Py_XDECREF(etype)
        Py_XDECREF(evalue)
        Py_XDECREF(etrace)
        PyErr_Clear()

    cdef inline evt_py_callable* c_add_py_callable(self, PyObject* py_callable, PyObject* logger, bint with_topic, bint deduplicate):
        if not PyCallable_Check(py_callable):
            raise ValueError('Callback handler must be callable')

        cdef evt_py_callable* callable_frame = self.callables

        # Walk list to detect duplicates and position at tail
        cdef evt_py_callable* tail = NULL
        while callable_frame:
            if callable_frame.fn == py_callable:
                if deduplicate:
                    return callable_frame
                else:
                    self.logger.warning(f'Handler {<object> py_callable} already registered in {self}. Adding again will be called multiple times when triggered.')
            tail = callable_frame
            callable_frame = callable_frame.next

        # Allocate new node
        callable_frame = <evt_py_callable*> calloc(1, sizeof(evt_py_callable))
        if not callable_frame:
            raise MemoryError('Failed to allocate memory for new evt_py_callable')

        Py_XINCREF(logger)
        Py_XINCREF(py_callable)

        callable_frame.fn = py_callable
        callable_frame.logger = logger
        callable_frame.idx = self.header.n_callbacks
        callable_frame.with_topic = with_topic

        if tail:
            tail.next = callable_frame
        else:
            self.callables = callable_frame

        c_evt_hook_register_callback(
            self.header,
            <const void*> EventHook.c_invoke_py_callable,
            evt_callback_type.EVT_CALLBACK_WITH_PAYLOAD_USERDATA,
            <void*> callable_frame,
            0
        )
        return callable_frame

    cdef inline int c_remove_py_callable(self, PyObject* py_callable):
        cdef evt_py_callable* curr = self.callables
        cdef evt_py_callable* prior = NULL

        while curr:
            if curr.fn == py_callable:
                Py_XDECREF(curr.fn)
                Py_XDECREF(curr.logger)
                if prior:
                    prior.next = curr.next
                else:
                    self.callables = curr.next
                c_evt_hook_pop_callback(self.header, curr.idx)
                prior = curr.next
                while prior:
                    prior.idx -= 1
                    prior = prior.next
                free(curr)
                return 1
            prior = curr
            curr = curr.next
        return 0

    cdef inline bint c_contains_py_callable(self, PyObject* py_callable):
        cdef evt_py_callable* curr = self.callables

        while curr:
            if curr.fn == py_callable:
                return True
            curr = curr.next
        return False

    cdef void c_free_py_callable(self):
        cdef evt_py_callable* curr = self.callables
        cdef evt_py_callable* next
        while curr:
            next = curr.next
            Py_XDECREF(curr.fn)
            Py_XDECREF(curr.logger)
            c_evt_hook_pop_callback(self.header, 0)
            free(curr)
            curr = next
        self.callables = NULL

    def __call__(self, MessagePayload msg):
        c_evt_hook_invoke(self.header, msg.header)

    def __iadd__(self, object py_callable):
        self.add_handler(py_callable, None, True)
        return self

    def __isub__(self, object py_callable):
        self.c_remove_py_callable(<PyObject*> py_callable)
        return self

    def __len__(self):
        return self.header.n_callbacks

    def __repr__(self):
        if self.topic:
            return f'<{self.__class__.__name__} "{self.topic.value}">(n={len(self)})'
        return f'<{self.__class__.__name__} NO_TOPIC>(n={len(self)})'

    def __iter__(self):
        return self.handlers.__iter__()

    def __contains__(self, object py_callable):
        return self.c_contains_py_callable(<PyObject*> py_callable)

    def trigger(self, MessagePayload msg):
        c_evt_hook_invoke(self.header, msg.header)

    def add_handler(self, object py_callable, object logger=None, bint deduplicate=False):
        cdef object sig = inspect.signature(py_callable)
        cdef object param
        cdef bint with_topic = False

        for param in sig.parameters.values():
            if param.name == TOPIC_FIELD_NAME or param.kind == inspect.Parameter.VAR_KEYWORD:
                with_topic = True
                break

        if logger is None:
            logger = self.logger

        self.c_add_py_callable(<PyObject*> py_callable, <PyObject*> logger, with_topic, deduplicate)

    def remove_handler(self, object py_callable):
        cdef int removed = self.c_remove_py_callable(<PyObject*> py_callable)
        if not removed:
            LOGGER.warning(f'{py_callable} not exist in {self} call stacks')

    def clear(self):
        self.c_free_py_callable()

    property handlers:
        def __get__(self):
            cdef evt_py_callable* curr = self.callables
            cdef list out = []
            while curr:
                out.append(dict(
                    fn = <object> curr.fn,
                    logger = <object> curr.logger,
                    idx = curr.idx,
                    with_topic = curr.with_topic
                ))
                Py_XINCREF(curr.fn)
                Py_XINCREF(curr.logger)
                curr = curr.next
            return out


cdef inline void c_hook_enter(evt_hook* hook, evt_hook_watcher_type watcher_type, evt_message_payload* payload, void* user_data) noexcept nogil:
    cdef evt_hook_stats* stats = <evt_hook_stats*> user_data
    stats.n_calls += 1
    stats.ts_call_start = perf_counter()


cdef inline void c_hook_exit(evt_hook* hook, evt_hook_watcher_type watcher_type, evt_message_payload* payload, void* user_data) noexcept nogil:
    cdef evt_hook_stats* stats = <evt_hook_stats*> user_data
    stats.ts_call_complete = perf_counter()
    stats.elapsed_seconds += stats.ts_call_complete - stats.ts_call_start


cdef class EventHookEx(EventHook):
    def __cinit__(self, Topic topic, object logger=None):
        c_evt_hook_add_watcher(self.header, c_hook_enter, <void*> &self.hook_stats, evt_hook_watcher_type.EVT_HOOK_WATCHER_PRE_INVOKED)
        c_evt_hook_add_watcher(self.header, c_hook_exit, <void*> &self.hook_stats, evt_hook_watcher_type.EVT_HOOK_WATCHER_POST_INVOKED)

    property stats:
        def __get__(self):
            cdef dict stats = {
                'n_calls': self.hook_stats.n_calls,
                'last_call_start': self.hook_stats.ts_call_start,
                'last_call_complete': self.hook_stats.ts_call_complete,
                'elapsed_seconds': self.hook_stats.elapsed_seconds
            }
            return stats
