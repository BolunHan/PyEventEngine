from cpython.datetime cimport datetime
from libc.stdint cimport uint64_t

from .c_event cimport evt_message_payload, EventHook
from .c_topic cimport evt_topic, Topic


cdef extern from "<pthread.h>":
    ctypedef struct pthread_mutex_t:
        pass

    ctypedef struct pthread_cond_t:
        pass


cdef extern from "c_heap_allocator.h":
    ctypedef struct heap_allocator:
        pass

    heap_allocator* c_heap_allocator_new()
    void c_heap_allocator_free(heap_allocator* allocator)
    void c_heap_free(void* ptr, pthread_mutex_t* lock)
    void* c_heap_request(heap_allocator* allocator, size_t size, int scan_all_pages, pthread_mutex_t* lock)
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
    void c_strmap_clear(strmap* map, int with_lock) noexcept nogil
    void c_strmap_free(strmap* map, int free_self, int with_lock) noexcept nogil
    int c_strmap_get(strmap* map, const char* key, size_t key_len, void** out) noexcept nogil
    int c_strmap_contains(strmap* map, const char* key, size_t key_len) noexcept nogil
    int c_strmap_rehash(strmap* map, size_t new_capacity, int with_lock) noexcept nogil
    int c_strmap_set(strmap* map, const char* key, size_t key_len, void* value, strmap_entry** out_entry, int with_lock) noexcept nogil
    int c_strmap_pop(strmap* map, const char* key, size_t key_len, void** out, int with_lock) noexcept nogil


cdef extern from "c_engine.h":
    const size_t DEFAULT_MQ_CAPACITY
    const size_t DEFAULT_MQ_SPIN_LIMIT
    const double DEFAULT_MQ_TIMEOUT_SECONDS

    ctypedef struct message_queue:
        heap_allocator* allocator
        size_t capacity
        size_t head
        size_t tail
        size_t count
        evt_topic* topic
        pthread_mutex_t mutex
        pthread_cond_t not_empty
        pthread_cond_t not_full
        evt_message_payload* buf[]

    message_queue* c_mq_new(size_t capacity, evt_topic* topic, heap_allocator* allocator) except NULL
    int c_mq_free(message_queue* mq, int free_self) except -1
    int c_mq_put(message_queue* mq, evt_message_payload* msg) noexcept nogil
    int c_mq_get(message_queue* mq, evt_message_payload** out_msg) noexcept nogil
    int c_mq_put_await(message_queue* mq, evt_message_payload* msg, double timeout_seconds) noexcept nogil
    int c_mq_get_await(message_queue* mq, evt_message_payload** out_msg, double timeout_seconds) noexcept nogil
    int c_mq_put_busy(message_queue* mq, evt_message_payload* msg, size_t max_spin) noexcept nogil
    int c_mq_get_busy(message_queue* mq, evt_message_payload** out_msg, size_t max_spin) noexcept nogil
    int c_mq_put_hybrid(message_queue* mq, evt_message_payload* msg, size_t max_spin, double timeout_seconds) noexcept nogil
    int c_mq_get_hybrid(message_queue* mq, evt_message_payload** out_msg, size_t max_spin, double timeout_seconds) noexcept nogil
    size_t c_mq_occupied(message_queue* mq) noexcept nogil


cdef class EventEngine:
    cdef message_queue* mq
    cdef strmap* exact_topic_hooks
    cdef strmap* generic_topic_hooks
    cdef heap_allocator* payload_allocator

    cdef readonly bint active
    cdef readonly object engine
    cdef public object logger
    cdef readonly uint64_t seq_id

    cdef inline void c_loop(self)

    cdef inline evt_message_payload* c_get(self, bint block, size_t max_spin, double timeout)

    cdef inline int c_publish(self, Topic topic, tuple args, dict kwargs, bint block, size_t max_spin, double timeout)

    cdef inline void c_trigger(self, evt_message_payload* msg)

    cdef inline void c_register_hook(self, EventHook hook)

    cdef inline EventHook c_unregister_hook(self, Topic topic)

    cdef inline void c_register_handler(self, Topic topic, object py_callable, bint deduplicate)

    cdef inline void c_unregister_handler(self, Topic topic, object py_callable)

    cdef inline void c_clear(self)


cdef class EventEngineEx(EventEngine):
    cdef readonly dict timer

    cdef inline void c_timer_loop(self, double interval, Topic topic, datetime activate_time)

    cdef inline void c_minute_timer_loop(self, Topic topic)

    cdef inline void c_second_timer_loop(self, Topic topic)
