from cpython.bytes cimport PyBytes_FromStringAndSize, PyBytes_GET_SIZE
from cpython.ref cimport PyObject
from cpython.unicode cimport PyUnicode_AsUTF8AndSize, PyUnicode_FromStringAndSize
from libc.stdint cimport uintptr_t


cdef object STRMAP_NO_DEFAULT = object()


cdef class StrMap:
    def __cinit__(self, size_t init_capacity=DEFAULT_STRMAP_CAPACITY):
        if not init_capacity:
            return

        self.owner = True
        self.header = c_strmap_new(init_capacity, NULL, 1)
        if self.header == NULL:
            raise MemoryError(f'Failed to allocate memory for <{self.__class__.__name__}>.')

    def __dealloc__(self):
        if not self.owner:
            return

        if self.header:
            c_strmap_free(self.header, 1, 1)

    @staticmethod
    cdef inline StrMap c_from_header(strmap* header, bint owner):
        cdef StrMap instance = StrMap.__new__(StrMap, 0)
        instance.header = header
        instance.owner = owner
        return instance

    cdef inline void* c_get(self, const char* key):
        cdef void* out
        cdef int ret_code = c_strmap_get(self.header, key, 0, &out)

        if ret_code == STRMAP_OK:
            return out
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError('Not found')
        else:
            raise RuntimeError(f'Failed to get from {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void* c_get_bytes(self, bytes key_bytes):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        cdef const char* key = <const char*> key_bytes
        cdef void* out
        cdef int ret_code = c_strmap_get(self.header, key, length, &out)

        if ret_code == STRMAP_OK:
            return out
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError(key_bytes)
        else:
            raise RuntimeError(f'Failed to get from {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void* c_get_str(self, str key_str):
        cdef Py_ssize_t length
        cdef const char* key = PyUnicode_AsUTF8AndSize(key_str, &length)
        cdef void* out
        cdef int ret_code = c_strmap_get(self.header, key, length, &out)

        if ret_code == STRMAP_OK:
            return out
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError(key_str)
        else:
            raise RuntimeError(f'Failed to get from {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void c_set(self, const char* key, void* value):
        cdef int ret_code = c_strmap_set(self.header, key, 0, value, NULL, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_FULL:
            raise MemoryError('Mapping is full')
        else:
            raise RuntimeError(f'Failed to set to {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void c_set_bytes(self, bytes key_bytes, void* value):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        cdef const char* key = <const char*> key_bytes
        cdef int ret_code = c_strmap_set(self.header, key, length, value, NULL, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_FULL:
            raise MemoryError('Mapping is full')
        else:
            raise RuntimeError(f'Failed to set to {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void c_set_str(self, str key_str, void* value):
        cdef Py_ssize_t length
        cdef const char* key = PyUnicode_AsUTF8AndSize(key_str, &length)
        cdef int ret_code = c_strmap_set(self.header, key, length, value, NULL, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_FULL:
            raise MemoryError('Mapping is full')
        else:
            raise RuntimeError(f'Failed to set to {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void c_pop(self, const char* key, void** out):
        cdef int ret_code = c_strmap_pop(self.header, key, 0, out, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError('Not found')
        else:
            raise RuntimeError(f'Failed to pop from {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void c_pop_bytes(self, bytes key_bytes, void** out):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        cdef const char* key = <const char*> key_bytes
        cdef int ret_code = c_strmap_pop(self.header, key, length, out, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError(key_bytes)
        else:
            raise RuntimeError(f'Failed to pop from {self.__class__.__name__}, err code: {ret_code}')

    cdef inline void c_pop_str(self, str key_str, void** out):
        cdef Py_ssize_t length
        cdef const char* key = PyUnicode_AsUTF8AndSize(key_str, &length)
        cdef int ret_code = c_strmap_pop(self.header, key, length, out, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError(key_str)
        else:
            raise RuntimeError(f'Failed to pop from {self.__class__.__name__}, err code: {ret_code}')

    cdef inline bint c_contains(self, const char* key):
        cdef int ret_code = c_strmap_contains(self.header, key, 0)

        if ret_code >= 0:
            return <bint> ret_code
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        else:
            raise RuntimeError(f'Failed to check {self.__class__.__name__} contain, err code: {ret_code}')

    cdef inline bint c_contains_bytes(self, bytes key_bytes):
        cdef size_t length = PyBytes_GET_SIZE(key_bytes)
        cdef const char* key = <const char*> key_bytes
        cdef int ret_code = c_strmap_contains(self.header, key, length)

        if ret_code >= 0:
            return <bint> ret_code
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        else:
            raise RuntimeError(f'Failed to check {self.__class__.__name__} contain, err code: {ret_code}')

    cdef inline bint c_contains_str(self, str key_str):
        cdef Py_ssize_t length
        cdef const char* key = PyUnicode_AsUTF8AndSize(key_str, &length)
        cdef int ret_code = c_strmap_contains(self.header, key, length)

        if ret_code >= 0:
            return <bint> ret_code
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        else:
            raise RuntimeError(f'Failed to check {self.__class__.__name__} contain, err code: {ret_code}')

    cdef inline void c_clear(self):
        c_strmap_clear(self.header, 1)

    # --- python interface ---

    def __len__(self):
        return self.header.occupied

    def __contains__(self, object key):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef int ret_code = c_strmap_contains(self.header, key_ptr, length)

        if ret_code >= 0:
            return <bint> ret_code
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        else:
            raise RuntimeError(f'Failed to check {self.__class__.__name__} contain, err code: {ret_code}')

    def __getitem__(self, object key):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef void* out
        cdef int ret_code = c_strmap_get(self.header, key_ptr, length, &out)

        if ret_code == STRMAP_OK:
            return <object> <PyObject*> out
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError(key)
        else:
            raise RuntimeError(f'Failed to get from {self.__class__.__name__}, err code: {ret_code}')

    def __setitem__(self, object key, object value):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef int ret_code = c_strmap_set(self.header, key_ptr, length, <void*> <PyObject*> value, NULL, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_FULL:
            raise MemoryError('Mapping is full')
        else:
            raise RuntimeError(f'Failed to set to {self.__class__.__name__}, err code: {ret_code}')

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>(size={self.total_size}, occupied={self.occupied}, capacity={self.capacity})"

    def get(self, object key, object default=None):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef void* out
        cdef int ret_code = c_strmap_get(self.header, key_ptr, length, &out)

        if ret_code == STRMAP_OK:
            return <object> <PyObject*> out
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            return default
        else:
            raise RuntimeError(f'Failed to get from {self.__class__.__name__}, err code: {ret_code}')

    def get_addr(self, object key):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef void* out
        cdef int ret_code = c_strmap_get(self.header, key_ptr, length, &out)

        if ret_code == STRMAP_OK:
            return <uintptr_t> out
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            raise KeyError(key)
        else:
            raise RuntimeError(f'Failed to get from {self.__class__.__name__}, err code: {ret_code}')

    def set(self, object key, object value):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef int ret_code = c_strmap_set(self.header, key_ptr, length, <void*> <PyObject*> value, NULL, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_FULL:
            raise MemoryError('Mapping is full')
        else:
            raise RuntimeError(f'Failed to set to {self.__class__.__name__}, err code: {ret_code}')

    def set_addr(self, object key, uintptr_t value):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef int ret_code = c_strmap_set(self.header, key_ptr, length, <void*> value, NULL, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_FULL:
            raise MemoryError('Mapping is full')
        else:
            raise RuntimeError(f'Failed to set to {self.__class__.__name__}, err code: {ret_code}')

    def pop(self, object key, object default=STRMAP_NO_DEFAULT, *):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef void* out
        cdef int ret_code = c_strmap_pop(self.header, key_ptr, length, &out, 1)

        if ret_code == STRMAP_OK:
            return
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        elif ret_code == STRMAP_ERR_NOT_FOUND:
            if default is STRMAP_NO_DEFAULT:
                raise KeyError(key)
            else:
                return default
        else:
            raise RuntimeError(f'Failed to pop from {self.__class__.__name__}, err code: {ret_code}')

    def contains(self, key: str | bytes):
        cdef Py_ssize_t length
        cdef const char* key_ptr
        if isinstance(key, str):
            key_ptr = PyUnicode_AsUTF8AndSize(key, &length)
        elif isinstance(key, bytes):
            length = PyBytes_GET_SIZE(key)
            key_ptr = <const char*> key
        else:
            raise TypeError('Key must be str or bytes')

        cdef int ret_code = c_strmap_contains(self.header, key_ptr, length)

        if ret_code >= 0:
            return <bint> ret_code
        elif ret_code == STRMAP_ERR_INVALID_BUF:
            raise ValueError('Invalid args')
        elif ret_code == STRMAP_ERR_INVALID_KEY:
            raise KeyError('Invalid key')
        else:
            raise RuntimeError(f'Failed to check {self.__class__.__name__} contain, err code: {ret_code}')

    def clear(self):
        c_strmap_clear(self.header, 1)

    def bytes_keys(self):
        cdef strmap_entry* entry = self.header.first
        while entry:
            yield PyBytes_FromStringAndSize(entry.key, entry.key_length)
            entry = entry.next

    def str_keys(self):
        cdef strmap_entry* entry = self.header.first
        while entry:
            yield PyUnicode_FromStringAndSize(entry.key, entry.key_length)
            entry = entry.next

    def values(self):
        cdef strmap_entry* entry = self.header.first
        while entry:
            yield <uintptr_t> entry.value
            entry = entry.next

    property capacity:
        def __get__(self):
            return self.header.capacity

        def __set__(self, size_t capacity):
            c_strmap_rehash(self.header, capacity, 1)

    property salt:
        def __get__(self):
            return self.header.salt

        def __set__(self, uint64_t salt):
            self.header.salt = salt

    property total_size:
        def __get__(self):
            return self.header.size

    property occupied:
        def __get__(self):
            return self.header.occupied
