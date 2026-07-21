from libc.stdint cimport uint64_t

from cbase.allocator_protocol.c_allocator_protocol cimport allocator_protocol
from cbase.bytemap.c_bytemap cimport bytemap


cdef extern from "event_engine/capi/c_topic.h":
    const char DEFAULT_TOPIC_SEP
    const char DEFAULT_OPTION_SEP
    const char* DEFAULT_RANGE_BRACKETS
    const char* DEFAULT_WILDCARD_BRACKETS
    const char DEFAULT_WILDCARD_MARKER
    const char DEFAULT_PATTERN_DELIM
    bytemap* GLOBAL_INTERNAL_MAP

    ctypedef enum evt_topic_type:
        TOPIC_PART_EXACT = 0
        TOPIC_PART_ANY = 1
        TOPIC_PART_RANGE = 2
        TOPIC_PART_PATTERN = 3

    ctypedef struct evt_topic_part:
        evt_topic_type ttype
        evt_topic_part_variant* next

    ctypedef struct evt_topic_exact:
        evt_topic_part header
        char* part
        size_t part_len

    ctypedef struct evt_topic_any:
        evt_topic_part header
        char* name
        size_t name_len

    ctypedef struct evt_topic_range:
        evt_topic_part header
        char** options
        size_t* option_length
        size_t num_options
        char* literal
        size_t literal_len

    ctypedef struct evt_topic_pattern:
        evt_topic_part header
        char* pattern
        size_t pattern_len

    ctypedef union evt_topic_part_variant:
        evt_topic_part header
        evt_topic_exact exact
        evt_topic_any any
        evt_topic_range range
        evt_topic_pattern pattern

    ctypedef struct evt_topic:
        evt_topic_part_variant* parts
        size_t n
        uint64_t hash
        char* key
        size_t key_len
        int is_exact

    ctypedef struct evt_topic_match:
        int matched
        evt_topic_part_variant* part_a
        evt_topic_part_variant* part_b
        char* literal
        size_t literal_len
        evt_topic_match* next

    bytemap* c_get_global_internal_map(allocator_protocol* allocator) noexcept nogil
    evt_topic* c_topic_new(const char* key, size_t key_len, allocator_protocol* allocator) noexcept nogil
    void c_topic_free(evt_topic* topic) noexcept nogil
    int c_topic_internalize(evt_topic* topic, const char* key, size_t key_len) noexcept nogil
    int c_topic_append(evt_topic* topic, const char* s, size_t len, evt_topic_type ttype) noexcept nogil
    int c_topic_parse(evt_topic* topic, const char* key, size_t key_len) noexcept nogil
    int c_topic_assign(evt_topic* topic, const char* key, size_t key_len) noexcept nogil
    int c_topic_update_literal(evt_topic* topic) noexcept nogil
    evt_topic_match* c_topic_match(evt_topic* topic_a, evt_topic* topic_b, evt_topic_match* out) noexcept nogil
    evt_topic_match* c_topic_match_new(evt_topic_match* prev, allocator_protocol* allocator) noexcept nogil
    void c_topic_match_free(evt_topic_match* res) noexcept nogil
    int c_topic_match_bool(evt_topic* topic_a, evt_topic* topic_b) noexcept nogil


cdef class TopicPart:
    cdef evt_topic_part_variant* header
    cdef readonly bint owner

    @staticmethod
    cdef TopicPart c_from_header(evt_topic_part_variant* header, bint owner=?)

    cdef object c_cast(self)


cdef class TopicPartExact(TopicPart):
    pass


cdef class TopicPartAny(TopicPart):
    pass


cdef class TopicPartRange(TopicPart):
    pass


cdef class TopicPartPattern(TopicPart):
    pass


cdef allocator_protocol* TOPIC_ALLOCATOR


cpdef Topic get_internal_topic(str key, bint owner=?)


cpdef dict get_internal_map()


cdef class TopicMatchResult:
    cdef evt_topic_match* header
    cdef bint owner

    @staticmethod
    cdef dict c_match_res(evt_topic_match* node)

    @staticmethod
    cdef TopicMatchResult c_from_header(evt_topic_match* node, bint owner=?)


cdef class Topic:
    cdef evt_topic* header
    cdef readonly bint owner

    @staticmethod
    cdef Topic c_from_header(evt_topic* header, bint owner=?)

    cdef void c_append(self, evt_topic_part_variant* tpart)

    cdef void c_update_literal(self)

    cpdef Topic append(self, TopicPart topic_part)

    cpdef TopicMatchResult match(self, Topic other)

    cpdef Topic format_map(self, dict mapping, bint internalized=?, bint strict=?)
