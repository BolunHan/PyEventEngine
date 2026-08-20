from libc.stdint cimport uint64_t
from libcpp cimport bool as c_bool

from cbase.allocator_protocol.c_allocator_protocol cimport allocator_protocol
from cbase.bytemap.c_bytemap cimport BoundByteMap, bytemap

from .c_engine cimport message_queue
from .c_event cimport evt_message_payload
from .c_topic cimport Topic, evt_topic


cdef extern from "event_engine/capi/c_engine.h":
    ctypedef struct evt_engine_task:
        evt_topic*          topic
        evt_message_payload payload

    ctypedef struct evt_engine_timer_ctx:
        evt_engine_timer_ctx* next
        double                interval_seconds
        double                next_due
        size_t                capacity
        size_t                n_task
        evt_engine_task*      task

    ctypedef struct evt_engine:
        message_queue*        mq
        bytemap*              exact_topic_hooks
        bytemap*              generic_topic_hooks
        double                mq_timeout_seconds
        uint64_t              mq_spin_limit
        evt_engine_timer_ctx* timer
        size_t                n_timer
        double                next_timer_due

    evt_engine* c_evt_engine_new(allocator_protocol* allocator) except NULL
    void c_evt_engine_free(evt_engine* engine)

    evt_message_payload* c_evt_engine_get(evt_engine* engine, c_bool block, size_t max_spin, double timeout)
    void c_evt_engine_trigger(evt_engine* engine, evt_message_payload* msg)

    c_bool c_evt_engine_is_active(const evt_engine* engine) noexcept nogil
    void c_evt_engine_set_active(evt_engine* engine, c_bool active) noexcept nogil
    uint64_t c_evt_engine_get_seq_id(const evt_engine* engine) noexcept nogil

    int c_evt_engine_register_timer(evt_engine* engine, evt_topic* topic, double interval_seconds, const void* payload_args)
    int c_evt_engine_unregister_timer(evt_engine* engine, evt_topic* topic)
    void c_evt_engine_set_timer_active(evt_engine* engine, c_bool active) noexcept nogil


cdef extern from "event_engine/capi/c_engine_gil.h":
    int c_evt_engine_loop_gil(evt_engine* engine)
    int c_evt_engine_publish_gil(evt_engine* engine, evt_message_payload* payload, c_bool block, size_t max_spin, double timeout)


cdef class EventHookMap(BoundByteMap):
    @staticmethod
    cdef EventHookMap c_from_header(bytemap* header, bint owner=?)


cdef class EventEngineEx:
    cdef evt_engine* header
    cdef EventHookMap exact_hook_map
    cdef EventHookMap generic_hook_map

    cdef public object logger
    cdef readonly object engine
    cdef readonly dict timer
    cdef dict timer_payloads

    cdef inline void c_loop(self)

    cdef inline evt_message_payload* c_get(self, bint block, size_t max_spin, double timeout)

    cdef inline int c_publish(self, Topic topic, tuple args, dict kwargs, bint block, size_t max_spin, double timeout)


cdef EventEngineEx EVENT_ENGINE
cdef evt_engine* C_EVENT_ENGINE
