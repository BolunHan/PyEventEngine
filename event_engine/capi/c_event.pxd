from cpython.object cimport PyObject
from libc.stdint cimport uint64_t

from .c_topic cimport evt_topic, Topic


cdef extern from "pthread.h":
    ctypedef struct pthread_mutex_t:
        pass


cdef extern from "Python.h":
    PyObject* PyDict_Copy(PyObject* p)
    PyObject* PyDict_SetDefault(PyObject* p, PyObject* key, PyObject* defaultobj)
    PyObject* PyObject_Call(PyObject* callable_object, PyObject* args, PyObject* kwargs)
    PyObject* PyObject_CallObject(PyObject* callable_object, PyObject* args)
    int PyCallable_Check(PyObject* o)


cdef extern from "c_heap_allocator.h":
    ctypedef struct heap_allocator:
        pthread_mutex_t lock

    void* c_heap_request(heap_allocator* allocator, size_t size, int scan_all_pages, pthread_mutex_t* lock) noexcept nogil
    void c_heap_free(void* ptr, pthread_mutex_t* lock) noexcept nogil


cdef extern from "c_event.h":
    ctypedef struct evt_message_payload:
        void* args
        evt_topic* topic
        uint64_t seq_id
        heap_allocator* allocator

    ctypedef void (*evt_callback_bare)()
    ctypedef void (*evt_callback_with_args)(void* args)
    ctypedef void (*evt_callback_with_topic)(evt_topic* topic)
    ctypedef void (*evt_callback_with_userdata)(void* user_data)
    ctypedef void (*evt_callback_with_args_topic)(void* args, evt_topic* topic)
    ctypedef void (*evt_callback_with_args_userdata)(void* args, void* user_data)
    ctypedef void (*evt_callback_with_topic_userdata)(evt_topic* topic, void* user_data)
    ctypedef void (*evt_callback_with_args_topic_userdata)(void* args, evt_topic* topic, void* user_data)
    ctypedef void (*evt_callback_with_payload)(evt_message_payload* payload)
    ctypedef void (*evt_callback_with_payload_userdata)(evt_message_payload* payload, void* user_data)

    ctypedef enum evt_callback_type:
        EVT_CALLBACK_BARE
        EVT_CALLBACK_WITH_ARGS
        EVT_CALLBACK_WITH_TOPIC
        EVT_CALLBACK_WITH_USERDATA
        EVT_CALLBACK_WITH_ARGS_TOPIC
        EVT_CALLBACK_WITH_ARGS_USERDATA
        EVT_CALLBACK_WITH_TOPIC_USERDATA
        EVT_CALLBACK_WITH_ARGS_TOPIC_USERDATA
        EVT_CALLBACK_WITH_PAYLOAD
        EVT_CALLBACK_WITH_PAYLOAD_USERDATA

    ctypedef union evt_callback_variants:
        evt_callback_bare                       bare
        evt_callback_with_args                  with_args
        evt_callback_with_topic                 with_topic
        evt_callback_with_userdata              with_userdata
        evt_callback_with_args_topic            with_args_topic
        evt_callback_with_args_userdata         with_args_userdata
        evt_callback_with_topic_userdata        with_topic_userdata
        evt_callback_with_args_topic_userdata   with_args_topic_userdata
        evt_callback_with_payload               with_payload
        evt_callback_with_payload_userdata      with_payload_userdata

    ctypedef struct evt_callback:
        evt_callback_type type
        evt_callback_variants fn
        void* user_data

    ctypedef enum evt_hook_watcher_type:
        EVT_HOOK_WATCHER_PRE_INVOKED
        EVT_HOOK_WATCHER_POST_INVOKED

    ctypedef void (*evt_hook_watcher_fn)(evt_hook* hook, evt_hook_watcher_type watcher_type, evt_message_payload* payload, void* user_data)

    ctypedef struct evt_hook_watcher:
        evt_hook_watcher_fn fn
        void* user_data

    ctypedef enum evt_hook_ret_code:
        EVT_HOOK_OK
        EVT_HOOK_ERR_INVALID_INPUT
        EVT_HOOK_ERR_OOM
        EVT_HOOK_ERR_DUPLICATE

    ctypedef struct evt_hook:
        evt_topic* topic
        evt_callback* callbacks
        size_t n_callbacks
        evt_hook_watcher* pre_watchers
        size_t n_pre_watchers
        evt_hook_watcher* post_watchers
        size_t n_post_watchers

    void c_evt_callback_invoke(const evt_callback* callback, evt_message_payload* payload) noexcept nogil
    evt_hook* c_evt_hook_new(evt_topic* topic) noexcept nogil
    void c_evt_hook_free(evt_hook* hook) noexcept nogil
    int c_evt_hook_add_watcher(evt_hook* hook, evt_hook_watcher_fn fn, void* user_data, evt_hook_watcher_type type) noexcept nogil
    int c_evt_hook_register_callback(evt_hook* hook, const void* fn, evt_callback_type ftype, void* user_data, int deduplicate) noexcept nogil
    int c_evt_hook_pop_callback(evt_hook* hook, size_t idx) noexcept nogil
    int c_evt_hook_invoke(evt_hook* hook, evt_message_payload* payload) noexcept nogil

cdef struct evt_py_payload:
    PyObject* py_topic
    PyObject* py_args
    PyObject* py_kwargs
    PyObject* py_kwargs_aggregated

cdef tuple EMPTY_ARGS

cdef str TOPIC_FIELD_NAME

cdef evt_message_payload* c_evt_payload_new(heap_allocator* allocator, Topic topic, tuple args, dict kwargs, int with_lock)

cdef void c_evt_payload_free(evt_message_payload* payload, int with_lock)


cdef class MessagePayload:
    cdef evt_message_payload* header
    cdef readonly bint owner

    @staticmethod
    cdef MessagePayload c_from_header(evt_message_payload* header, bint owner=?)


cdef struct evt_py_callable:
    PyObject* fn
    PyObject* logger
    size_t idx
    bint with_topic
    evt_py_callable* next


cdef class EventHook:
    cdef evt_hook* header
    cdef evt_py_callable* callables
    cdef readonly Topic topic
    cdef readonly object logger

    @staticmethod
    cdef inline void c_invoke_py_callable(evt_message_payload* payload, void* user_data) with gil

    cdef inline evt_py_callable* c_add_py_callable(self, PyObject* py_callable, PyObject* logger, bint with_topic, bint deduplicate)

    cdef inline int c_remove_py_callable(self, PyObject* py_callable)

    cdef inline bint c_contains_py_callable(self, PyObject* py_callable)

    cdef void c_free_py_callable(self)


cdef struct evt_hook_stats:
    size_t n_calls
    double ts_call_start
    double ts_call_complete
    double elapsed_seconds

cdef void c_hook_enter(evt_hook* hook, evt_hook_watcher_type watcher_type, evt_message_payload* payload, void* user_data) noexcept nogil

cdef void c_hook_exit(evt_hook* hook, evt_hook_watcher_type watcher_type, evt_message_payload* payload, void* user_data) noexcept nogil

cdef class EventHookEx(EventHook):
    cdef evt_hook_stats hook_stats
