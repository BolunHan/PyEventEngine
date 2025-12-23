from cpython.object cimport PyObject
from libc.stdint cimport uint64_t

from .c_topic cimport evt_topic, Topic


cdef extern from "Python.h":
    PyObject* PyObject_Call(object callable_object, object args, object kw)


cdef extern from "pthread.h":
    ctypedef struct pthread_mutex_t:
        pass


cdef extern from "c_heap_allocator.h":
    ctypedef struct heap_allocator:
        pthread_mutex_t lock;

    void c_heap_free(void* ptr, pthread_mutex_t* lock)


cdef extern from "c_strmap.h":
    const int STRMAP_OK
    const int STRMAP_ERR_NOT_FOUND

    ctypedef struct strmap_entry:
        const char* key
        size_t key_length
        void* value
        uint64_t hash
        int occupied
        int removed
        strmap_entry* prev
        strmap_entry* next

    ctypedef struct strmap:
        heap_allocator* heap_allocator
        strmap_entry* tabl
        size_t capacity
        size_t size
        size_t occupied
        strmap_entry* first
        strmap_entry* last
        uint64_t salt

    strmap* c_strmap_new(size_t capacity, heap_allocator* heap_allocator, int with_lock) noexcept nogil
    void c_strmap_free(strmap* map, int free_self, int with_lock) noexcept nogil
    int c_strmap_get(strmap* map, const char* key, size_t key_len, void** out) noexcept nogil
    int c_strmap_set(strmap* map, const char* key, size_t key_len, void* value, strmap_entry** out_entry, int with_lock) noexcept nogil
    int c_strmap_pop(strmap* map, const char* key, size_t key_len, void** out, int with_lock) noexcept nogil


cdef extern from "c_event.h":
    ctypedef struct evt_message_payload:
        evt_topic* topic
        void* args
        void* kwargs
        uint64_t seq_id
        heap_allocator* allocator


cdef class MessagePayload:
    cdef evt_message_payload* header

    cdef readonly bint owner
    cdef public bint args_owner
    cdef public bint kwargs_owner

    @staticmethod
    cdef MessagePayload c_from_header(evt_message_payload* header, bint owner=*, bint args_owner=?, bint kwargs_owner=?)


cdef struct EventHandler:
    PyObject* handler
    EventHandler* next


cdef tuple C_INTERNAL_EMPTY_ARGS

cdef dict C_INTERNAL_EMPTY_KWARGS

cdef str TOPIC_FIELD_NAME

cdef str TOPIC_UNEXPECTED_ERROR


cdef class EventHook:
    cdef readonly Topic topic
    cdef readonly object logger
    cdef public bint retry_on_unexpected_topic
    cdef EventHandler* handlers_no_topic
    cdef EventHandler* handlers_with_topic

    @staticmethod
    cdef inline void c_free_handlers(EventHandler* handlers)

    cdef void c_safe_call_no_topic(self, EventHandler* handler, tuple args, dict kwargs)

    cdef void c_safe_call_with_topic(self, EventHandler* handler, tuple args, dict kwargs)

    cdef inline void c_trigger_no_topic(self, evt_message_payload* msg)

    cdef inline void c_trigger_with_topic(self, evt_message_payload* msg)

    cdef EventHandler* c_add_handler(self, object py_callable, bint with_topic, bint deduplicate)

    cdef EventHandler* c_remove_handler(self, object py_callable)


cdef struct HandlerStats:
    size_t calls
    double total_time


cdef class EventHookEx(EventHook):
    cdef strmap* stats_mapping
