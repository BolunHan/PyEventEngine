from cpython.datetime cimport datetime
from libc.stdint cimport uint64_t

from cbase.allocator_protocol.c_allocator_protocol cimport allocator_protocol
from cbase.bytemap.c_bytemap cimport bytemap

from .c_event cimport EventHook, evt_message_payload
from .c_topic cimport Topic, evt_topic


cdef extern from "event_engine/capi/c_engine.h":
    const size_t DEFAULT_MQ_CAPACITY
    const size_t DEFAULT_MQ_SPIN_LIMIT
    const double DEFAULT_MQ_TIMEOUT_SECONDS

    ctypedef struct pthread_mutex_t:
        pass

    ctypedef struct pthread_cond_t:
        pass

    ctypedef struct message_queue:
        size_t capacity
        size_t head
        size_t tail
        size_t count
        evt_topic* topic
        pthread_mutex_t mutex
        pthread_cond_t not_empty
        pthread_cond_t not_full
        evt_message_payload* buf[]

    message_queue* c_mq_new(size_t capacity, evt_topic* topic, allocator_protocol* allocator) except NULL
    int c_mq_free(message_queue* mq) except -1
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
    cdef bytemap* exact_topic_hooks
    cdef bytemap* generic_topic_hooks

    cdef readonly bint active
    cdef readonly object engine
    cdef public object logger
    cdef readonly uint64_t seq_id

    cdef inline void c_loop(self)

    cdef inline evt_message_payload* c_get(self, bint block, size_t max_spin, double timeout)

    cdef inline int c_publish(self, Topic topic, tuple args, dict kwargs, bint block, size_t max_spin, double timeout)

    cdef inline void c_trigger(self, evt_message_payload* msg)

    cdef inline EventHook c_get_hook(self, Topic topic)

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
