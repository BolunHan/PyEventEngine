from libc.stdint cimport uint64_t

from .c_allocator cimport MemoryAllocator, Allocator
from .c_bytemap cimport ByteMapHeader, ByteMap


cdef extern from "c_topic.h":
    const char DEFAULT_TOPIC_SEP
    const char DEFAULT_OPTION_SEP
    const char* DEFAULT_RANGE_BRACKETS
    const char DEFAULT_WILDCARD_MARKER
    const char DEFAULT_PATTERN_DELIM
    ByteMapHeader* GLOBAL_INTERNAL_MAP

    ctypedef enum TopicType:
        TOPIC_PART_EXACT = 0
        TOPIC_PART_ANY = 1
        TOPIC_PART_RANGE = 2
        TOPIC_PART_PATTERN = 3

    ctypedef struct TopicPartHeader:
        TopicType ttype
        TopicPart* next

    ctypedef struct TopicPartExact:
        TopicPartHeader header
        char* part
        size_t part_len

    ctypedef struct TopicPartAny:
        TopicPartHeader header
        char* name
        size_t name_len

    ctypedef struct TopicPartRange:
        TopicPartHeader header
        char** options
        size_t* option_length
        size_t num_options
        char* literal
        size_t literal_len

    ctypedef struct TopicPartPattern:
        TopicPartHeader header
        char* pattern
        size_t pattern_len

    ctypedef union TopicPart:
        TopicPartHeader header
        TopicPartExact exact
        TopicPartAny any
        TopicPartRange range
        TopicPartPattern pattern

    ctypedef struct Topic:
        TopicPart* parts
        size_t n
        uint64_t hash
        char* key
        size_t key_len
        int is_exact
        MemoryAllocator* allocator

    ctypedef struct TopicPartMatchResult:
        int matched
        TopicPart* part_a
        TopicPart* part_b
        char* literal
        size_t literal_len
        TopicPartMatchResult* next
        MemoryAllocator* allocator

    ByteMapHeader* c_get_global_internal_map(MemoryAllocator* allocator) except NULL
    Topic* c_topic_new(const char* key, size_t key_len, MemoryAllocator* allocator)
    int c_topic_free(Topic* topic, int free_self) except -1
    int c_topic_internalize(Topic* topic, const char* key, size_t key_len) except -1
    int c_topic_append(Topic* topic, const char* s, size_t len, TopicType ttype) except -1
    int c_topic_parse(Topic* topic, const char* key, size_t key_len)
    int c_topic_assign(Topic* topic, const char* key, size_t key_len)
    int c_topic_update_literal(Topic* topic) except -1
    TopicPartMatchResult* c_topic_match(Topic* topic_a, Topic* topic_b, TopicPartMatchResult* out) except NULL
    TopicPartMatchResult* c_topic_match_new(TopicPartMatchResult* prev, MemoryAllocator* allocator) except NULL
    void c_topic_match_free(TopicPartMatchResult* res) noexcept
    int c_topic_match_bool(Topic* topic_a, Topic* topic_b)


cdef class PyTopicPart:
    cdef TopicPart* header
    cdef readonly bint owner

    @staticmethod
    cdef PyTopicPart c_from_header(TopicPart* header, bint owner=*)

    cdef object c_cast(self)


cdef class PyTopicPartExact(PyTopicPart):
    pass


cdef class PyTopicPartRange(PyTopicPart):
    pass


cdef class PyTopicPartPattern(PyTopicPart):
    pass


cdef Allocator C_ALLOCATOR

cpdef ByteMap init_internal_map(size_t default_capacity=*)

cpdef void clear_internal_map()

cpdef PyTopic get_internal_topic(str key, bint owner=*)

cpdef dict get_internal_map()

cpdef Allocator init_allocator(size_t init_capacity=*, bint with_shm=*)


cdef class PyTopicMatchResult:
    cdef TopicPartMatchResult* header
    cdef bint owner

    @staticmethod
    cdef dict c_match_res(TopicPartMatchResult* node)

    @staticmethod
    cdef PyTopicMatchResult c_from_header(TopicPartMatchResult* node, bint owner=*)


cdef class PyTopic:
    cdef Topic* header
    cdef readonly bint owner

    @staticmethod
    cdef PyTopic c_from_header(Topic* header, bint owner=*)

    cdef void c_append(self, TopicPart* tpart)

    cdef void c_update_literal(self)

    cpdef PyTopic append(self, PyTopicPart topic_part)

    cpdef PyTopicMatchResult match(self, PyTopic other)

    cpdef PyTopic format_map(self, dict mapping, bint internalized=*)
