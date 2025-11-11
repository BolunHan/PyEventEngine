# cython: language_level=3
from libc.stdint cimport uint64_t

from .c_allocator cimport MemoryAllocator


cdef extern from "c_bytemap.h":
    const size_t MIN_BYTEMAP_CAPACITY
    const size_t DEFAULT_BYTEMAP_CAPACITY
    const size_t MAX_BYTEMAP_CAPACITY
    const void* C_BYTEMAP_NOT_FOUND

    ctypedef struct MapEntry:
        char* key
        size_t key_length
        void* value
        uint64_t hash
        int occupied
        int removed
        MapEntry* prev
        MapEntry* next

    ctypedef struct ByteMapHeader:
        MemoryAllocator* allocator
        MapEntry* table
        size_t capacity
        size_t size
        size_t occupied
        MapEntry* first
        MapEntry* last
        uint64_t salt

    uint64_t c_bytemap_hash(ByteMapHeader* map, const char* key, size_t key_len) noexcept nogil
    char* c_bytemap_clone_key(MemoryAllocator* allocator, const char* key, size_t key_len) except NULL
    void c_bytemap_free_key(MemoryAllocator* allocator, char* key) noexcept
    ByteMapHeader* c_bytemap_new(size_t capacity, MemoryAllocator* allocator) except NULL
    void c_bytemap_clear(ByteMapHeader* map) noexcept
    void c_bytemap_free(ByteMapHeader* map, int free_self) noexcept
    void* c_bytemap_get(ByteMapHeader* map, const char* key, size_t key_len) noexcept nogil
    int c_bytemap_contains(ByteMapHeader* map, const char* key, size_t key_len) noexcept nogil
    int c_bytemap_rehash(ByteMapHeader* map, size_t new_capacity) except -1
    MapEntry* c_bytemap_set(ByteMapHeader* map, const char* key, size_t key_len, void* value) except NULL
    int c_bytemap_pop(ByteMapHeader* map, const char* key, size_t key_len, void** out) except -1


cdef object C_BYTEMAP_NO_DEFAULT


cdef class ByteMap:
    cdef ByteMapHeader* _header
    cdef bint _owner

    @staticmethod
    cdef inline ByteMap c_from_header(ByteMapHeader* header, bint is_owner)

    cdef inline void* c_get(self, const char* key_ptr) nogil

    cdef inline void* c_get_bytes(self, bytes key_bytes)

    cdef inline void* c_get_str(self, str key_str)

    cdef inline void c_set(self, const char* key_ptr, void* value)

    cdef inline void c_set_bytes(self, bytes key_bytes, void* value)

    cdef inline void c_set_str(self, str key_str, void* value)

    cdef inline void c_pop(self, const char* key_ptr, void** out)

    cdef inline void c_pop_bytes(self, bytes key_bytes, void** out)

    cdef inline void c_pop_str(self, str key_str, void** out)

    cdef inline bint c_contains(self, const char* key_ptr) nogil

    cdef inline bint c_contains_bytes(self, bytes key_bytes)

    cdef inline bint c_contains_str(self, str key_str)

    cdef void c_clear(self)
