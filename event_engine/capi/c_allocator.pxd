
cdef extern from "c_allocator.h":
    size_t DEFAULT_ALLOC_PAGE

    ctypedef struct MemoryBlock:
        size_t size
        MemoryBlock* next

    ctypedef struct MemoryPage:
        MemoryPage* prev
        size_t occupied
        size_t capacity
        char* buffer

    ctypedef struct MemoryAllocator:
        int active
        MemoryPage* pages
        int owned
        int extendable
        MemoryBlock* free_list

    # MemoryAllocator related function declarations
    size_t c_heap_align(size_t size) noexcept
    int c_heap_extend(MemoryAllocator* allocator, size_t page_size) except -1
    void* c_heap_alloc(MemoryAllocator* allocator, size_t total_size)
    MemoryAllocator* c_heap_new(size_t capacity) except NULL
    void* c_heap_request(MemoryAllocator* allocator, size_t size) noexcept
    void c_heap_recycle(MemoryAllocator* allocator, void* ptr) noexcept
    void c_heap_free(MemoryAllocator* allocator) noexcept
    size_t c_heap_available(MemoryAllocator* allocator) noexcept
    size_t c_heap_total_capacity(MemoryAllocator* allocator) noexcept


cdef class Allocator:
    cdef MemoryAllocator* allocator

    cdef Py_buffer** views
    cdef size_t n_views
    cdef size_t cap_views
    cdef readonly list buffer
    cdef readonly dict address_map

    cdef MemoryPage* c_new_page(self, object buffer)

    cdef void c_register(self, void* addr, object instance)

    cpdef char[:] request(self, size_t size)

    cpdef void recycle(self, char[:] buffer)

    cpdef void clear(self)
