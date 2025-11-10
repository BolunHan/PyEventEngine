# cython: c_string_type=unicode, c_string_encoding=UTF8
from cpython.bytes cimport PyBytes_FromStringAndSize, PyBytes_GET_SIZE
from cpython.ref cimport PyObject
from cpython.unicode cimport PyUnicode_AsUTF8AndSize, PyUnicode_FromStringAndSize
from libc.stdint cimport uintptr_t

from .c_allocator cimport MemoryAllocator, Allocator


cdef object C_BYTEMAP_NO_DEFAULT = object()


cdef class ByteMap:

    def __cinit__(self, size_t init_capacity=DEFAULT_BYTEMAP_CAPACITY, bint no_init=False):
        if no_init:
            return

        self._owner = True
        self._header = c_bytemap_new(init_capacity, NULL)
        if self._header == NULL:
            raise MemoryError(f'Failed to allocate memory for <{self.__class__.__name__}>.')

    def __dealloc__(self):
        if self._owner and self._header != NULL:
            c_bytemap_free(self._header, True)
            self._header = NULL

    @staticmethod
    cdef inline ByteMap c_from_header(ByteMapHeader* header, bint is_owner):
        cdef ByteMap instance = ByteMap.__new__(ByteMap, 0, True)
        instance._header = header
        instance._owner = is_owner
        return instance

    cdef inline void* c_get(self, const char* key_ptr) nogil:
        cdef void* value = c_bytemap_get(self._header, key_ptr, 0)
        return value

    cdef inline void* c_get_bytes(self, bytes key_bytes):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        cdef void* value = c_bytemap_get(self._header, <char*> key_bytes, length)
        return value

    cdef inline void* c_get_str(self, str key_str):
        cdef Py_ssize_t length
        cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(key_str, &length)
        cdef void* value = c_bytemap_get(self._header, <char*> key_ptr, <size_t> length)
        return value

    cdef inline void c_set(self, const char* key_ptr, void* value):
        c_bytemap_set(self._header, key_ptr, 0, value)

    cdef inline void c_set_bytes(self, bytes key_bytes, void* value):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        c_bytemap_set(self._header, <char*> key_bytes, length, value)

    cdef inline void c_set_str(self, str key_str, void* value):
        cdef Py_ssize_t length
        cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(key_str, &length)
        c_bytemap_set(self._header, key_ptr, length, value)

    cdef inline void c_pop(self, const char* key_ptr, void** out):
        cdef int success = c_bytemap_pop(self._header, key_ptr, 0, out)

    cdef inline void c_pop_bytes(self, bytes key_bytes, void** out):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        c_bytemap_pop(self._header, <char*> key_bytes, length, out)

    cdef inline void c_pop_str(self, str key_str, void** out):
        cdef Py_ssize_t length
        cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(key_str, &length)
        c_bytemap_pop(self._header, key_ptr, length, out)

    cdef inline bint c_contains(self, const char* key_ptr) nogil:
        cdef bint res = c_bytemap_contains(self._header, key_ptr, 0)
        return res

    cdef inline bint c_contains_bytes(self, bytes key_bytes):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        cdef bint res =  c_bytemap_contains(self._header, <char*> key_bytes, length)
        return res

    cdef inline bint c_contains_str(self, str key_str):
        cdef Py_ssize_t length
        cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(key_str, &length)
        cdef bint res =  c_bytemap_contains(self._header, key_ptr, length)
        return res

    cdef inline void c_clear(self):
        c_bytemap_clear(self._header)

    # --- python interface ---

    @classmethod
    def from_buffer(cls, Allocator heap, size_t init_capacity=DEFAULT_BYTEMAP_CAPACITY) -> ByteMap:
        cdef MemoryAllocator* allocator = heap.allocator
        cdef ByteMapHeader* mapping = c_bytemap_new(init_capacity, allocator)
        if mapping == NULL:
            raise MemoryError(f'Failed to allocate memory for <{cls.__name__}>.')
        cdef ByteMap instance = ByteMap.c_from_header(mapping, False)
        heap.c_register(<void*> mapping, instance)
        return instance

    def __len__(self):
        return self._header.occupied

    def __contains__(self, key: str | bytes):
        if isinstance(key, str):
            return self.c_contains_str(key)
        elif isinstance(key, bytes):
            return self.c_contains_bytes(key)
        else:
            raise TypeError('Key must be str or bytes')

    def __getitem__(self, key: str | bytes):
        cdef void* value

        if isinstance(key, str):
            value = self.c_get_str(key)
        elif isinstance(key, bytes):
            value = self.c_get_bytes(key)
        else:
            raise TypeError('Key must be str or bytes')

        if value == C_BYTEMAP_NOT_FOUND:
            raise KeyError(f'Key {key} not found')
        return <object> <PyObject*> value

    def __setitem__(self, key: str | bytes, value: object):
        if isinstance(key, str):
            self.c_set_str(key, <void*> <PyObject*> value)
        elif isinstance(key, bytes):
            self.c_set_bytes(key, <void*> <PyObject*> value)
        else:
            raise TypeError('Key must be str or bytes')

    def __repr__(self) -> str:
        return f"<ByteMap(size={self.total_size}, occupied={self.occupied}, capacity={self.capacity})>"

    def get(self, object key, object default=None):
        cdef void* value

        if isinstance(key, str):
            value = self.c_get_str(key)
        elif isinstance(key, bytes):
            value = self.c_get_bytes(key)
        else:
            raise TypeError('Key must be str or bytes')

        if value == C_BYTEMAP_NOT_FOUND:
            return default
        return <object> <PyObject*> value

    def get_addr(self, key: str | bytes):
        cdef void* value

        if isinstance(key, str):
            value = self.c_get_str(key)
        elif isinstance(key, bytes):
            value = self.c_get_bytes(key)
        else:
            raise TypeError('Key must be str or bytes')

        if value == C_BYTEMAP_NOT_FOUND:
            raise KeyError(f'Key {key} not found')
        return <uintptr_t> value

    def set(self, key: str | bytes, object value):
        if isinstance(key, str):
            self.c_set_str(key, <void*> <PyObject*> value)
        elif isinstance(key, bytes):
            self.c_set_bytes(key, <void*> <PyObject*> value)
        else:
            raise TypeError('Key must be str or bytes')

    def set_addr(self, key: str | bytes, size_t value):
        if isinstance(key, str):
            self.c_set_str(key, <void*> <uintptr_t> value)
        elif isinstance(key, bytes):
            self.c_set_bytes(key, <void*> <uintptr_t> value)
        else:
            raise TypeError('Key must be str or bytes')

    def pop(self, key: str | bytes, object default=C_BYTEMAP_NO_DEFAULT, *):
        cdef void* out = <void*> C_BYTEMAP_NOT_FOUND
        if isinstance(key, str):
            self.c_pop_str(key, &out)
        elif isinstance(key, bytes):
            self.c_pop_bytes(key, &out)
        else:
            raise TypeError('Key must be str or bytes')

        if out == C_BYTEMAP_NOT_FOUND:
            if default is C_BYTEMAP_NO_DEFAULT:
                raise KeyError(f'Key {key} not found')
            else:
                return default
        return <object> <PyObject*> out

    def contains(self, key: str | bytes):
        if isinstance(key, str):
            return self.c_contains_str(key)
        elif isinstance(key, bytes):
            return self.c_contains_bytes(key)
        else:
            raise TypeError('Key must be str or bytes')

    def clear(self):
        self.c_clear()

    def bytes_keys(self):
        cdef MapEntry* entry = self._header.first
        while entry:
            yield PyBytes_FromStringAndSize(entry.key, entry.key_length)
            entry = entry.next

    def str_keys(self):
        cdef MapEntry* entry = self._header.first
        while entry:
            yield PyUnicode_FromStringAndSize(entry.key, entry.key_length)
            entry = entry.next

    def values(self):
        cdef MapEntry* entry = self._header.first
        while entry:
            yield <uintptr_t> entry.value
            entry = entry.next

    property capacity:
        def __get__(self):
            return self._header.capacity

        def __set__(self, size_t capacity):
            c_bytemap_rehash(self._header, capacity)

    property salt:
        def __get__(self):
            return self._header.salt

        def __set__(self, uint64_t salt):
            self._header.salt = salt

    property total_size:
        def __get__(self):
            return self._header.size

    property occupied:
        def __get__(self):
            return self._header.occupied
