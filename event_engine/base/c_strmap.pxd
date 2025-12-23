from libc.stdint cimport uint64_t


cdef extern from "c_heap_allocator.h":
    ctypedef struct heap_allocator:
        pass


cdef extern from "c_strmap.h":
    const size_t MIN_STRMAP_CAPACITY
    const size_t DEFAULT_STRMAP_CAPACITY
    const size_t MAX_STRMAP_CAPACITY

    const int STRMAP_OK
    const int STRMAP_ERR_INVALID_BUF
    const int STRMAP_ERR_INVALID_KEY
    const int STRMAP_ERR_NOT_FOUND
    const int STRMAP_ERR_FULL
    const int STRMAP_ERR_EMPTY

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


cdef class StrMap:
    cdef strmap* header
    cdef bint owner

    @staticmethod
    cdef inline StrMap c_from_header(strmap* header, bint owner)

    cdef inline void* c_get(self, const char* key_ptr)

    cdef inline void* c_get_bytes(self, bytes key_bytes)

    cdef inline void* c_get_str(self, str key_str)

    cdef inline void c_set(self, const char* key_ptr, void* value)

    cdef inline void c_set_bytes(self, bytes key_bytes, void* value)

    cdef inline void c_set_str(self, str key_str, void* value)

    cdef inline void c_pop(self, const char* key_ptr, void** out)

    cdef inline void c_pop_bytes(self, bytes key_bytes, void** out)

    cdef inline void c_pop_str(self, str key_str, void** out)

    cdef inline bint c_contains(self, const char* key_ptr)

    cdef inline bint c_contains_bytes(self, bytes key_bytes)

    cdef inline bint c_contains_str(self, str key_str)

    cdef void c_clear(self)
