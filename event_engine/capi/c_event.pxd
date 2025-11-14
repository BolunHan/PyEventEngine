from cpython.object cimport PyObject
from libc.stdint cimport uint64_t

from .c_allocator cimport MemoryAllocator
from .c_bytemap cimport ByteMapHeader
from .c_topic cimport Topic, PyTopic


cdef extern from "Python.h":
    PyObject* PyObject_Call(object callable_object, object args, object kw)


cdef extern from "c_event.h":
    ctypedef struct MessagePayload:
        Topic* topic
        void* args
        void* kwargs
        uint64_t seq_id
        MemoryAllocator* allocator


cdef class PyMessagePayload:
    cdef MessagePayload* header

    cdef readonly bint owner
    cdef public bint args_owner
    cdef public bint kwargs_owner

    @staticmethod
    cdef PyMessagePayload c_from_header(MessagePayload* header, bint owner=*, bint args_owner=*, bint kwargs_owner=*)


cdef struct EventHandler:
    PyObject* handler
    EventHandler* next


cdef tuple C_INTERNAL_EMPTY_ARGS

cdef dict C_INTERNAL_EMPTY_KWARGS

cdef str TOPIC_FIELD_NAME

cdef str TOPIC_UNEXPECTED_ERROR


cdef class EventHook:
    cdef readonly PyTopic topic
    cdef readonly object logger
    cdef public bint retry_on_unexpected_topic
    cdef EventHandler* handlers_no_topic
    cdef EventHandler* handlers_with_topic

    @staticmethod
    cdef inline void c_free_handlers(EventHandler* handlers)

    cdef void c_safe_call_no_topic(self, EventHandler* handler, tuple args, dict kwargs)

    cdef void c_safe_call_with_topic(self, EventHandler* handler, tuple args, dict kwargs)

    cdef inline void c_trigger_no_topic(self, MessagePayload* msg)

    cdef inline void c_trigger_with_topic(self, MessagePayload* msg)

    cdef EventHandler* c_add_handler(self, object py_callable, bint with_topic, bint deduplicate)

    cdef EventHandler* c_remove_handler(self, object py_callable)


cdef struct HandlerStats:
    size_t calls
    double total_time


cdef class EventHookEx(EventHook):
    cdef ByteMapHeader* stats_mapping
