from cpython.datetime cimport datetime
from libc.stdint cimport uint64_t

from .c_allocator cimport MemoryAllocator
from .c_bytemap cimport ByteMapHeader
from .c_event cimport MessagePayload, EventHook
from .c_topic cimport Topic, PyTopic


cdef extern from "<pthread.h>":
    ctypedef struct pthread_mutex_t:
        pass

    ctypedef struct pthread_cond_t:
        pass


cdef extern from "c_engine.h":
    const size_t DEFAULT_MQ_CAPACITY
    const size_t DEFAULT_MQ_SPIN_LIMIT
    const double DEFAULT_MQ_TIMEOUT_SECONDS

    ctypedef struct MessageQueue:
        MemoryAllocator* allocator
        size_t capacity
        size_t head
        size_t tail
        size_t count
        Topic* topic
        pthread_mutex_t mutex
        pthread_cond_t not_empty
        pthread_cond_t not_full
        MessagePayload* buf[]

    MessageQueue* c_mq_new(size_t capacity, Topic* topic, MemoryAllocator* allocator) except NULL
    int c_mq_free(MessageQueue* mq, int free_self) except -1
    int c_mq_put(MessageQueue* mq, MessagePayload* msg) noexcept nogil
    int c_mq_get(MessageQueue* mq, MessagePayload** out_msg) noexcept nogil
    int c_mq_put_await(MessageQueue* mq, MessagePayload* msg, double timeout_seconds) noexcept nogil
    int c_mq_get_await(MessageQueue* mq, MessagePayload** out_msg, double timeout_seconds) noexcept nogil
    int c_mq_put_busy(MessageQueue* mq, MessagePayload* msg, size_t max_spin) noexcept nogil
    int c_mq_get_busy(MessageQueue* mq, MessagePayload** out_msg, size_t max_spin) noexcept nogil
    int c_mq_put_hybrid(MessageQueue* mq, MessagePayload* msg, size_t max_spin, double timeout_seconds) noexcept nogil
    int c_mq_get_hybrid(MessageQueue* mq, MessagePayload** out_msg, size_t max_spin, double timeout_seconds) noexcept nogil
    size_t c_mq_occupied(MessageQueue* mq) noexcept nogil


cdef class EventEngine:
    cdef MessageQueue* mq
    cdef ByteMapHeader* exact_topic_hooks
    cdef ByteMapHeader* generic_topic_hooks
    cdef MemoryAllocator* payload_allocator

    cdef readonly bint active
    cdef readonly object engine
    cdef public object logger
    cdef readonly uint64_t seq_id

    cdef inline void c_loop(self)

    cdef inline MessagePayload* c_get(self, bint block, size_t max_spin, double timeout)

    cdef inline int c_publish(self, PyTopic topic, tuple args, dict kwargs, bint block, size_t max_spin, double timeout)

    cdef inline void c_trigger(self, MessagePayload* msg)

    cdef inline void c_register_hook(self, EventHook hook)

    cdef inline EventHook c_unregister_hook(self, PyTopic topic)

    cdef inline void c_register_handler(self, PyTopic topic, object py_callable, bint deduplicate)

    cdef inline void c_unregister_handler(self, PyTopic topic, object py_callable)

    cdef inline void c_clear(self)


cdef class EventEngineEx(EventEngine):
    cdef readonly dict timer

    cdef inline void c_timer_loop(self, double interval, PyTopic topic, datetime activate_time)

    cdef inline void c_minute_timer_loop(self, PyTopic topic)

    cdef inline void c_second_timer_loop(self, PyTopic topic)
