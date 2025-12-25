from cpython.object cimport PyObject
from libc.stdint cimport uint64_t

from .c_topic cimport evt_topic, Topic


cdef extern from "pthread.h":
    ctypedef struct pthread_mutex_t:
        pass


cdef extern from "Python.h":
    PyObject* PyObject_Call(PyObject* callable_object, PyObject* args, PyObject* kwargs)
    PyObject* PyObject_CallObject(PyObject* callable_object, PyObject* args)

    PyObject* PyDict_New()
    PyObject* PyDict_Copy(PyObject* p)
    int PyDict_Contains(PyObject* p, PyObject* key)
    PyObject* PyDict_SetDefault(PyObject* p, PyObject* key, PyObject* defaultobj)
    int PyDict_Pop(PyObject* p, PyObject* key, PyObject** result)
    Py_ssize_t PyDict_Size(PyObject* p)


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

    ctypedef void (*evt_callback_bare)()
    ctypedef void (*evt_callback_with_topic)(evt_topic* topic)
    ctypedef void (*evt_callback_with_args)(void* args, void* kwargs, uint64_t seq_id)
    ctypedef void (*evt_callback_with_topic_args)(evt_topic* topic, void* args, void* kwargs, uint64_t seq_id)
    ctypedef void (*evt_callback_with_payload)(evt_message_payload* payload)
    ctypedef void (*evt_callback_with_userdata)(evt_message_payload* payload, void* user_data)

    ctypedef enum evt_callback_type:
        EVT_CALLBACK_BARE
        EVT_CALLBACK_WITH_TOPIC
        EVT_CALLBACK_WITH_ARGS
        EVT_CALLBACK_WITH_TOPIC_ARGS
        EVT_CALLBACK_WITH_PAYLOAD
        EVT_CALLBACK_WITH_USERDATA

    ctypedef union evt_callback_variants:
        evt_callback_bare               bare
        evt_callback_with_topic         with_topic
        evt_callback_with_args          with_args
        evt_callback_with_topic_args    with_topic_args
        evt_callback_with_payload       with_payload
        evt_callback_with_userdata      with_userdata

    ctypedef struct evt_callback:
        evt_callback_type type
        evt_callback_variants fn
        void* user_data

    ctypedef struct evt_hook:
        evt_topic* topic
        evt_callback* callbacks
        size_t n_callbacks

    ctypedef enum evt_hook_error:
        EVT_HOOK_OK
        EVT_HOOK_ERR_INVALID_INPUT
        EVT_HOOK_ERR_OOM
        EVT_HOOK_ERR_DUPLICATE

    void c_evt_callback_invoke(const evt_callback* callback, evt_message_payload* payload)
    evt_hook* c_evt_hook_new(evt_topic* topic)
    void c_evt_hook_free(evt_hook* hook)
    int c_evt_hook_register_callback(evt_hook* hook, const void* fn, evt_callback_type ftype, void* user_data, int deduplicate)
    int c_evt_hook_invoke_callbacks(evt_hook* hook, evt_message_payload* payload)


cdef class MessagePayload:
    cdef evt_message_payload* header

    cdef readonly bint owner
    cdef public bint args_owner
    cdef public bint kwargs_owner

    @staticmethod
    cdef MessagePayload c_from_header(evt_message_payload* header, bint owner=*, bint args_owner=?, bint kwargs_owner=?)


cdef struct EventHandler:
    PyObject* fn
    PyObject* logger
    PyObject* topic
    bint with_topic
    EventHandler* next


cdef tuple C_INTERNAL_EMPTY_ARGS

cdef dict C_INTERNAL_EMPTY_KWARGS

cdef str TOPIC_FIELD_NAME

cdef str TOPIC_UNEXPECTED_ERROR


cdef class EventHook:
    cdef readonly Topic topic
    cdef readonly object logger
    cdef public bint retry_on_unexpected_topic
    cdef evt_hook* header
    cdef EventHandler* handlers_no_topic
    cdef EventHandler* handlers_with_topic

    @staticmethod
    cdef inline void c_free_handlers(EventHandler* handlers)

    @staticmethod
    cdef void c_evt_pycallback_adapter(evt_message_payload* payload, void* user_data)

    cdef void c_safe_call_no_topic(self, EventHandler* handler, PyObject* args, PyObject* kwargs)

    cdef void c_safe_call_with_topic(self, EventHandler* handler, PyObject* args, PyObject* kwargs)

    cdef inline void c_trigger_no_topic(self, evt_message_payload* msg)

    cdef inline void c_trigger_with_topic(self, evt_message_payload* msg)

    cdef EventHandler* c_add_handler(self, object py_callable, bint with_topic, bint deduplicate)

    cdef EventHandler* c_remove_handler(self, object py_callable)


cdef struct HandlerStats:
    size_t calls
    double total_time


cdef class EventHookEx(EventHook):
    cdef strmap* stats_mapping
