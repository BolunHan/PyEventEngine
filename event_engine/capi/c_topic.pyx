import enum
import re
from collections.abc import Iterable

from cpython.unicode cimport PyUnicode_AsUTF8AndSize, PyUnicode_FromStringAndSize
from libc.stdint cimport uint8_t, uintptr_t
from libc.stdlib cimport calloc, free
from libc.string cimport memcpy, strlen

from .c_bytemap cimport c_bytemap_new, c_bytemap_free, DEFAULT_BYTEMAP_CAPACITY
from .c_allocator cimport DEFAULT_ALLOC_PAGE, c_heap_request

GLOBAL_INTERNAL_MAP = NULL
C_INTERNAL_MAP = None
C_ALLOCATOR = None


class PyTopicType(enum.IntEnum):
    TOPIC_PART_EXACT = TopicType.TOPIC_PART_EXACT
    TOPIC_PART_ANY = TopicType.TOPIC_PART_ANY
    TOPIC_PART_RANGE = TopicType.TOPIC_PART_RANGE
    TOPIC_PART_PATTERN = TopicType.TOPIC_PART_PATTERN


cdef class PyTopicPart:
    def __cinit__(self, *arg, bint alloc=False, **kwargs):
        if not alloc:
            return

        self.header = <TopicPart*> calloc(1, sizeof(TopicPart))
        if not self.header:
            raise MemoryError('Failed to allocate memory!')
        self.owner = True

    def __dealloc__(self):
        if self.owner and self.header:
            free(self.header)
            self.header = NULL

    @staticmethod
    cdef PyTopicPart c_from_header(TopicPart* header, bint owner=False):
        cdef PyTopicPart instance = PyTopicPart.__new__(PyTopicPart, alloc=False)
        instance.header = header
        instance.owner = owner
        return instance

    cdef object c_cast(self):
        cdef uint8_t ttype = self.header.header.ttype
        cdef object casted
        if ttype == TopicType.TOPIC_PART_EXACT:
            casted = PyTopicPartExact.__new__(PyTopicPartExact, alloc=False)
        elif ttype == TopicType.TOPIC_PART_ANY:
            casted = PyTopicPartAny.__new__(PyTopicPartAny, alloc=False)
        elif ttype == TopicType.TOPIC_PART_RANGE:
            casted = PyTopicPartRange.__new__(PyTopicPartRange, alloc=False)
        elif ttype == TopicType.TOPIC_PART_PATTERN:
            casted = PyTopicPartPattern.__new__(PyTopicPartPattern, alloc=False)
        else:
            raise ValueError(f'Invalid ttype {ttype}')
        (<PyTopicPart> casted).header = self.header
        (<PyTopicPart> casted).owner = self.owner
        self.owner = False
        return casted

    # --- Python Interfaces ---

    def next(self):
        if self.header.header.next:
            return PyTopicPart.c_from_header(self.header.header.next, False).c_cast()
        raise StopIteration

    property ttype:
        def __get__(self) -> PyTopicType:
            if self.header:
                return PyTopicType(self.header.header.ttype)
            raise RuntimeError('Not initialized!')

    property addr:
        def __get__(self) -> int:
            if self.header:
                return <uintptr_t> self.header


cdef class PyTopicPartExact(PyTopicPart):
    def __cinit__(self, str part=None, *arg, bint alloc=False, **kwargs):
        if not alloc:
            if part:
                raise RuntimeError('Can not assign part string when uninitialized!')
            return

        if not part:
            return

        cdef Py_ssize_t length
        cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(part, &length)
        cdef char* part_ptr = <char*> calloc(length + 1, sizeof(char))
        if not part_ptr:
            free(self.header)
            self.header = NULL
            raise MemoryError('Failed to allocate memory!')
        memcpy(part_ptr, key_ptr, length)

        self.header.exact.part = part_ptr
        self.header.exact.part_len = length
        self.header.header.ttype = TopicType.TOPIC_PART_EXACT

    def __dealloc__(self):
        if self.owner and self.header:
            if self.header.exact.part:
                free(self.header.exact.part)

    def __repr__(self):
        if self.header:
            return f'<TopicPartExact>(topic="{self.part}")'
        return f'<TopicPartExact uninitialized>'

    def __len__(self):
        return self.header.exact.part_len

    property part:
        def __get__(self) -> str:
            return PyUnicode_FromStringAndSize(self.header.exact.part, self.header.exact.part_len)


cdef class PyTopicPartAny(PyTopicPart):
    def __cinit__(self, str name=None, *arg, bint alloc=False, **kwargs):
        if not alloc:
            if name:
                raise RuntimeError('Can not assign name string when uninitialized!')
            return

        if not name:
            return

        cdef Py_ssize_t length
        cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(name, &length)
        cdef char* name_ptr = <char*> calloc(length + 1, sizeof(char))
        if not name_ptr:
            free(self.header)
            self.header = NULL
            raise MemoryError('Failed to allocate memory!')
        memcpy(name_ptr, key_ptr, length)

        self.header.any.name = name_ptr
        self.header.any.name_len = length
        self.header.header.ttype = TopicType.TOPIC_PART_ANY

    def __dealloc__(self):
        if self.owner and self.header:
            if self.header.any.name:
                free(self.header.any.name)

    def __repr__(self):
        if self.header:
            return f'<TopicPartAny>(name="{self.name}")'
        return f'<TopicPartAny uninitialized>'

    property name:
        def __get__(self) -> str:
            return PyUnicode_FromStringAndSize(self.header.any.name, self.header.any.name_len)


cdef class PyTopicPartRange(PyTopicPart):
    def __cinit__(self, list options=None, *arg, bint alloc=False, **kwargs):
        if not alloc:
            if options:
                raise RuntimeError('Can not assign options when uninitialized!')
            return

        if not options:
            return

        cdef size_t n_internal = len(options) - 1 + sum(len(_) for _ in options)
        cdef char* internal = <char*> calloc(n_internal + 1, sizeof(char))
        if not internal:
            free(self.header)
            self.header = NULL
            raise MemoryError('Failed to allocate memory!')

        cdef size_t n_options = len(options)
        cdef char** option_array = <char**> calloc(n_options, sizeof(char*))
        if not option_array:
            free(internal)
            free(self.header)
            self.header = NULL
            raise MemoryError('Failed to allocate memory!')

        cdef str option
        cdef Py_ssize_t option_length
        cdef const char* option_ptr
        cdef size_t start = 0, i = 0

        for option in options:
            option_ptr = PyUnicode_AsUTF8AndSize(option, &option_length)
            memcpy(<char*> internal + start, <void*> option_ptr, option_length)
            option_array[i] = <char*> internal + start
            if not option_array[i]:
                free(internal)
                free(option_array)
                free(self.header)
                self.header = NULL
                raise MemoryError('Failed to allocate memory!')
            i += 1
            start += option_length + 1

        self.header.range.options = option_array
        self.header.range.num_options = n_options
        self.header.range.literal = internal
        self.header.header.ttype = TopicType.TOPIC_PART_RANGE

    def __dealloc__(self):
        if self.owner and self.header:
            if self.header.range.options:
                free(self.header.range.options)
            if self.header.range.literal:
                free(self.header.range.literal)

    def __repr__(self):
        if self.header:
            return f'<TopicPartRange>(n={self.header.range.num_options}, options={str(list(self.options()))})'
        return f'<TopicPartRange uninitialized>'

    def __len__(self):
        return self.header.range.num_options

    def __iter__(self):
        return self.options()

    def options(self):
        if not self.header:
            raise RuntimeError('Not initialized!')

        cdef char** option_array = self.header.range.options
        cdef size_t num_options = self.header.range.num_options
        cdef size_t i
        cdef char* option_ptr
        cdef size_t option_length

        for i in range(num_options):
            option_ptr = option_array[i]
            option_length = strlen(option_ptr)
            yield PyUnicode_FromStringAndSize(option_ptr, option_length)


cdef class PyTopicPartPattern(PyTopicPart):
    def __cinit__(self, str regex=None, *arg, bint alloc=False, **kwargs):
        if not alloc:
            if regex:
                raise RuntimeError('Can not assign regex string when uninitialized!')
            return

        if not regex:
            return

        cdef Py_ssize_t length
        cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(regex, &length)
        cdef char* regex_ptr = <char*> calloc(length + 1, sizeof(char))
        if not regex_ptr:
            free(self.header)
            self.header = NULL
            raise MemoryError('Failed to allocate memory!')
        memcpy(regex_ptr, key_ptr, length)

        self.header.pattern.pattern = regex_ptr
        self.header.pattern.pattern_len = length
        self.header.header.ttype = TopicType.TOPIC_PART_PATTERN

    def __dealloc__(self):
        if self.owner and self.header:
            if self.header.pattern.pattern:
                free(self.header.pattern.pattern)

    def __repr__(self):
        if self.header:
            return f'<TopicPartPattern>(regex="{self.pattern}")'
        return f'<TopicPartPattern uninitialized>'

    property pattern:
        def __get__(self) -> str:
            return PyUnicode_FromStringAndSize(self.header.pattern.pattern, self.header.pattern.pattern_len)

    property regex:
        def __get__(self):
            return re.compile(self.pattern)


cpdef ByteMap init_internal_map(size_t default_capacity=DEFAULT_BYTEMAP_CAPACITY):
    global C_INTERNAL_MAP, GLOBAL_INTERNAL_MAP
    if not GLOBAL_INTERNAL_MAP:
        GLOBAL_INTERNAL_MAP = c_bytemap_new(default_capacity, C_ALLOCATOR.allocator)
    C_INTERNAL_MAP = ByteMap.c_from_header(GLOBAL_INTERNAL_MAP, 0)
    return C_INTERNAL_MAP


cpdef void clear_internal_map():
    global C_INTERNAL_MAP, GLOBAL_INTERNAL_MAP
    C_INTERNAL_MAP = None
    if GLOBAL_INTERNAL_MAP:
        c_bytemap_free(GLOBAL_INTERNAL_MAP, 1)
        GLOBAL_INTERNAL_MAP = NULL


cpdef Allocator init_allocator(size_t init_capacity=DEFAULT_ALLOC_PAGE, bint with_shm=False):
    global C_ALLOCATOR

    if C_ALLOCATOR is None:
        if with_shm:
            C_ALLOCATOR = Allocator.get_shm(init_capacity)
        else:
            C_ALLOCATOR = Allocator.get_buffer(init_capacity)
    return C_ALLOCATOR


cdef class PyTopicMatchResult:
    def __cinit__(self, size_t n_parts=0, bint alloc=False, Allocator allocator=None, **kwargs):
        if not alloc:
            if n_parts:
                raise RuntimeError('Can not allocator buffer when uninitialized!')
            return

        cdef MemoryAllocator* c_allocator = NULL if allocator is None else allocator.allocator
        cdef size_t i
        cdef TopicPartMatchResult* node = NULL
        for i in range(n_parts):
            node = c_topic_match_new(node, c_allocator)
            if not node:
                c_topic_match_free(self.header)
            elif not self.header:
                self.header = node
                self.owner = True

    def __dealloc__(self):
        if self.owner and self.header:
            c_topic_match_free(self.header)

    @staticmethod
    cdef PyTopicMatchResult c_from_header(TopicPartMatchResult* node, bint owner=True):
        cdef PyTopicMatchResult instance = PyTopicMatchResult.__new__(PyTopicMatchResult, alloc=False)
        instance.header = node
        instance.owner = owner
        return instance

    @staticmethod
    cdef dict c_match_res(TopicPartMatchResult* node):
        if not node:
            raise RuntimeError('Not initialized!')
        cdef dict info = {
            'matched': node.matched,
            'part_a': PyTopicPart.c_from_header(node.part_a, False).c_cast() if node.part_a else None,
            'part_b': PyTopicPart.c_from_header(node.part_b, False).c_cast() if node.part_b else None,
            'literal': PyUnicode_FromStringAndSize(node.literal, node.literal_len) if node.literal else None,
        }
        return info

    def __repr__(self):
        return f'<TopicPartMatchResult {"success" if self.matched else "failed"}>(nodes={self.length})'

    def __bool__(self):
        return self.matched

    def __len__(self):
        return self.length

    def __getitem__(self, ssize_t idx):
        cdef ssize_t length = self.length
        if idx < -length:
            raise IndexError(f'Index {idx} out of range!')
        elif idx < 0:
            idx += length
        elif idx >= length:
            raise IndexError(f'Index {idx} out of range!')

        cdef ssize_t i = 0
        cdef TopicPartMatchResult* node = self.header
        while i < idx:
            i += 1
            node = node.next

        return PyTopicMatchResult.c_match_res(node)

    def __iter__(self):
        cdef TopicPartMatchResult* node = self.header
        while node:
            yield PyTopicMatchResult.c_match_res(node)
            node = node.next

    def to_dict(self):
        cdef dict out = {}
        cdef TopicPartMatchResult* node = self.header
        cdef str literal

        while node:
            literal = PyUnicode_FromStringAndSize(node.literal, node.literal_len)
            out[literal] = PyTopicPart.c_from_header(node.part_b, False).c_cast()
        return out

    property length:
        def __get__(self) -> size_t:
            if not self.header:
                raise RuntimeError('Not initialized!')
            cdef size_t i = 0
            cdef TopicPartMatchResult* node = self.header
            while node:
                i += 1
                node = node.next
            return i

    property matched:
        def __get__(self) -> bint:
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef TopicPartMatchResult* node = self.header
            while node:
                if not node.matched:
                    return False
                node = node.next
            return True


cdef class PyTopic:
    def __cinit__(self, str topic=None, *arg, bint alloc=True, Allocator allocator=None, **kwargs):
        if not alloc:
            if topic:
                raise RuntimeError('Can not assign topic string when uninitialized!')
            return

        cdef MemoryAllocator* c_allocator = NULL if allocator is None else allocator.allocator
        if not topic:
            self.header = c_topic_new(NULL, 0, c_allocator)
            self.owner = True
            if not self.header:
                raise MemoryError(f'Failed to init topic ":{topic}", check if the syntax is correct!')
            return

        cdef Py_ssize_t topic_length
        cdef const char* topic_ptr = PyUnicode_AsUTF8AndSize(topic, &topic_length)
        self.header = c_topic_new(topic_ptr, topic_length, c_allocator)
        if not self.header:
            raise MemoryError('Failed to allocate memory!')

    def __dealloc__(self):
        if self.owner and self.header:
            c_topic_free(self.header, 1)

    @staticmethod
    cdef PyTopic c_from_header(Topic* header, bint owner=False):
        cdef PyTopic instance = PyTopic.__new__(PyTopic, alloc=False)
        instance.header = header
        instance.owner = owner
        return instance

    cdef void c_append(self, TopicPart* tpart):
        cdef TopicType ttype = tpart.header.ttype
        if ttype == TopicType.TOPIC_PART_EXACT:
            literal = tpart.exact.part
            literal_len = tpart.exact.part_len
        elif ttype == TopicType.TOPIC_PART_ANY:
            literal = tpart.any.name
            literal_len = tpart.any.name_len
        elif ttype == TopicType.TOPIC_PART_RANGE:
            literal = tpart.range.literal
            literal_len = tpart.range.literal_len
        elif ttype == TopicType.TOPIC_PART_PATTERN:
            literal = tpart.pattern.pattern
            literal_len = tpart.pattern.pattern_len
        else:
            raise RuntimeError(f'Unknown topic type {PyTopicType(ttype)}')
        c_topic_append(self.header, literal, literal_len, ttype)

    cdef void c_update_literal(self):
        c_topic_update_literal(self.header)

    # --- Python Interface ---

    def __len__(self):
        return self.header.n

    def __iter__(self):
        cdef TopicPart* part = self.header.parts
        while part:
            yield PyTopicPart.c_from_header(part, False).c_cast()
            part = part.header.next

    def __getitem__(self, ssize_t idx):
        cdef ssize_t n_parts = self.header.n
        if idx < -n_parts:
            raise IndexError(f'Index {idx} out of range!')
        elif idx < 0:
            idx += n_parts
        elif idx >= n_parts:
            raise IndexError(f'Index {idx} out of range!')

        cdef ssize_t i = 0
        cdef TopicPart* part = self.header.parts

        while part:
            if i == idx:
                return PyTopicPart.c_from_header(part, False).c_cast()
            i += 1
            part = part.header.next
        raise IndexError('i')

    def __add__(self, object topic):
        cdef PyTopic aggregated = PyTopic.__new__(PyTopic)
        cdef TopicPart* other_part
        cdef TopicPart* tpart = self.header.parts
        cdef size_t i, n
        if isinstance(object, PyTopic):
            other_part = (<PyTopic> topic).header.parts
            n = self.header.n
            for i in range(n):
                aggregated.c_append(<TopicPart*> tpart + i)
            n = (<PyTopic> topic).header.n
            for i in range(n):
                aggregated.c_append(<TopicPart*> other_part + i)
        elif isinstance(object, PyTopicPart):
            other_part = (<PyTopicPart> topic).header
            n = self.header.n
            for i in range(n):
                aggregated.c_append(<TopicPart*> tpart + i)
            aggregated.c_append(other_part)
        else:
            raise TypeError(f'Can not add {topic} to {self}, expected ether a {PyTopic} or {PyTopicPart}')
        aggregated.c_update_literal()
        return aggregated

    def __iadd__(self, object topic):
        cdef TopicPart* other_part
        cdef size_t i, n
        if isinstance(object, PyTopic):
            other_part = (<PyTopic> topic).header.parts
            n = (<PyTopic> topic).header.n
            for i in range(n):
                self.c_append(<TopicPart*> other_part + i)
        elif isinstance(object, PyTopicPart):
            other_part = (<PyTopicPart> topic).header
            self.c_append(other_part)
        else:
            raise TypeError(f'Can not add {topic} to {self}, expected ether a {PyTopic} or {PyTopicPart}')
        self.c_update_literal()
        return self

    @classmethod
    def from_parts(cls, topic_parts: Iterable[PyTopicPart]) -> PyTopic:
        cdef PyTopic aggregated = PyTopic.__new__(PyTopic)
        cdef PyTopicPart tpart
        for tpart in topic_parts:
            aggregated.c_append(tpart.header)
        aggregated.c_update_literal()
        return aggregated

    @classmethod
    def join(cls, topic_parts: Iterable[str]) -> PyTopic:
        cdef PyTopic aggregated = PyTopic.__new__(PyTopic)
        cdef str part
        cdef Py_ssize_t literal_len
        cdef const char* literal
        cdef Topic* topic = aggregated.header

        for tpart in topic_parts:
            literal = PyUnicode_AsUTF8AndSize(tpart, &literal_len)
            c_topic_append(topic, literal, literal_len, TopicType.TOPIC_PART_EXACT)
        c_topic_update_literal(topic)
        return aggregated

    cpdef PyTopic append(self, PyTopicPart topic_part):
        if not self.header or not topic_part.header:
            raise RuntimeError('Not initialized!')
        cdef TopicPart* part = topic_part.header
        cdef Topic* topic = self.header
        cdef TopicPart* curr = topic.parts
        cdef MemoryAllocator* allocator = topic.allocator
        cdef char* literal
        cdef size_t literal_len

        # shortcut: just appending the buffer if it is owned and topic not using allocator.
        if topic_part.owner and not (allocator and allocator.active):
            topic_part.owner = False
            part = topic_part.header
            part.header.next = NULL

            if not curr:
                topic.parts = part
            else:
                while curr.header.next:
                    curr = curr.header.next
                curr.header.next = part
            topic.n += 1
        else:
            self.c_append(part)
        self.c_update_literal()
        return self

    cpdef PyTopicMatchResult match(self, PyTopic other):
        cdef TopicPartMatchResult* match_res = c_topic_match(self.header, other.header, NULL)
        return PyTopicMatchResult.c_from_header(match_res, True)

    property value:
        def __get__(self):
            cdef str literal = PyUnicode_FromStringAndSize(self.header.key, self.header.key_len)
            return literal

        def __set__(self, str value):
            cdef Py_ssize_t topic_length
            cdef const char* topic_ptr = PyUnicode_AsUTF8AndSize(value, &topic_length)
            cdef int assign_ret = c_topic_assign(self.header, topic_ptr, topic_length)
            if assign_ret:
                raise ValueError(f'Failed to assign topic "{value}", check if syntax is correct!')
