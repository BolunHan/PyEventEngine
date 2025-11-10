from ctypes import c_char

from cpython.buffer cimport PyBUF_SIMPLE, PyObject_GetBuffer, PyBuffer_Release
from libc.stdint cimport uintptr_t
from libc.stdlib cimport malloc, realloc, free


cdef class Allocator:
    def __cinit__(self, object buffer=None, Py_ssize_t capacity=0):
        # Case 1: Use extendable auto memory allocator
        if buffer is None:
            self.allocator = c_heap_new(capacity or DEFAULT_ALLOC_PAGE)
        # Case 2: Use provided python buffer, for maximal buffer size control and shared memory
        else:
            self.allocator = c_heap_new(0)
            self.allocator.owned = 0
            self.allocator.extendable = 0

        self.views = NULL
        self.n_views = 0
        self.cap_views = 0
        self.buffer = []
        self.address_map = {}

        if buffer is not None:
            self.c_new_page(buffer)

    def __dealloc__(self):
        self.address_map.clear()

        cdef size_t i
        cdef Py_buffer* view
        for i in range(self.n_views):
            view = self.views[i]
            PyBuffer_Release(view)
            self.view_obtained = False

        if self.views:
            free(self.views)
            self.views = NULL

        if self.allocator:
            c_heap_free(self.allocator)

    cdef MemoryPage* c_new_page(self, object buffer):
        cdef Py_buffer view
        PyObject_GetBuffer(buffer, &view, PyBUF_SIMPLE)
        cdef char* m = <char*> view.buf
        cdef Py_ssize_t max_cap = view.len

        cdef MemoryPage* page = <MemoryPage*> malloc(sizeof(MemoryPage));
        if not page:
            raise MemoryError('Failed to allocate memory')

        page.buffer = m
        page.capacity = max_cap
        page.occupied = 0
        page.prev = self.allocator.pages
        self.allocator.pages = page
        # self.allocator.owned = 0

        if not self.views:
            self.views = <Py_buffer**> malloc(4 * sizeof(Py_buffer*))
            if not self.views:
                raise MemoryError('Failed to allocate memory')
            self.cap_views = 4
            self.views[0] = &view
            self.n_views = 1
            return page

        cdef size_t new_cap = self.cap_views * 2
        cdef Py_buffer** new_views = <Py_buffer**> realloc(self.views, new_cap * sizeof(Py_buffer*))
        if not new_views:
            raise MemoryError('Failed to allocate memory')
        self.views = new_views
        self.cap_views = new_cap

        self.views[self.n_views] = &view
        self.n_views += 1
        return page

    cdef void c_register(self, void* addr, object instance):
        self.address_map[<uintptr_t> addr] = instance

    def __len__(self):
        return c_heap_total_capacity(self.allocator)

    @classmethod
    def get_shm(cls, size_t size) -> Allocator:
        from multiprocessing import RawArray
        cdef object shm = RawArray(c_char, size)
        cdef Allocator self = Allocator.__new__(Allocator, shm, 0)
        return self

    @classmethod
    def get_buffer(cls, size_t size) -> Allocator:
        cdef object buffer = bytearray(size)
        cdef Allocator self = Allocator.__new__(Allocator, buffer, 0)
        return self

    cpdef char[:] request(self, size_t size):
        cdef char* buffer = <char*> c_heap_request(self.allocator, size)
        if not buffer:
            raise MemoryError('Failed to allocate memory')
        return <char[:size]> buffer

    cpdef void recycle(self, char[:] buffer):
        c_heap_recycle(self.allocator, &buffer[0])

    cpdef void clear(self):
        self.address_map.clear()

    property capacity:
        def __get__(self):
            return c_heap_total_capacity(self.allocator)

    property available_bytes:
        def __get__(self):
            return c_heap_available(self.allocator)

    property addr:
        def __get__(self):
            return <uintptr_t> self.allocator