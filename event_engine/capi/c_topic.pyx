import enum
import re
from collections.abc import Iterable

from cpython.unicode cimport PyUnicode_AsUTF8AndSize, PyUnicode_FromStringAndSize
from libc.stdint cimport uint8_t, uintptr_t
from libc.stdlib cimport calloc, free
from libc.string cimport memcpy, strlen


class TopicType(enum.IntEnum):
    TOPIC_PART_EXACT = evt_topic_type.TOPIC_PART_EXACT
    TOPIC_PART_ANY = evt_topic_type.TOPIC_PART_ANY
    TOPIC_PART_RANGE = evt_topic_type.TOPIC_PART_RANGE
    TOPIC_PART_PATTERN = evt_topic_type.TOPIC_PART_PATTERN


cdef class TopicPart:
    def __cinit__(self, *arg, bint alloc=False, **kwargs):
        if not alloc:
            return

        self.header = <evt_topic_part_variant*> calloc(1, sizeof(evt_topic_part_variant))
        if not self.header:
            raise MemoryError('Failed to allocate memory!')
        self.owner = True

    def __dealloc__(self):
        if self.owner and self.header:
            free(self.header)
            self.header = NULL

    @staticmethod
    cdef TopicPart c_from_header(evt_topic_part_variant* header, bint owner=False):
        cdef TopicPart instance = TopicPart.__new__(TopicPart, alloc=False)
        instance.header = header
        instance.owner = owner
        return instance

    cdef object c_cast(self):
        cdef uint8_t ttype = self.header.header.ttype
        cdef object casted
        if ttype == evt_topic_type.TOPIC_PART_EXACT:
            casted = TopicPartExact.__new__(TopicPartExact, alloc=False)
        elif ttype == evt_topic_type.TOPIC_PART_ANY:
            casted = TopicPartAny.__new__(TopicPartAny, alloc=False)
        elif ttype == evt_topic_type.TOPIC_PART_RANGE:
            casted = TopicPartRange.__new__(TopicPartRange, alloc=False)
        elif ttype == evt_topic_type.TOPIC_PART_PATTERN:
            casted = TopicPartPattern.__new__(TopicPartPattern, alloc=False)
        else:
            raise ValueError(f'Invalid ttype {ttype}')
        (<TopicPart> casted).header = self.header
        (<TopicPart> casted).owner = self.owner
        self.owner = False
        return casted

    # --- Python Interfaces ---

    def next(self):
        if self.header.header.next:
            return TopicPart.c_from_header(self.header.header.next, False).c_cast()
        raise StopIteration

    property ttype:
        def __get__(self) -> TopicType:
            if self.header:
                return TopicType(self.header.header.ttype)
            raise RuntimeError('Not initialized!')

    property addr:
        def __get__(self) -> int:
            if self.header:
                return <uintptr_t> self.header


cdef class TopicPartExact(TopicPart):
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
        self.header.header.ttype = evt_topic_type.TOPIC_PART_EXACT

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


cdef class TopicPartAny(TopicPart):
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
        self.header.header.ttype = evt_topic_type.TOPIC_PART_ANY

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


cdef class TopicPartRange(TopicPart):
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
        self.header.header.ttype = evt_topic_type.TOPIC_PART_RANGE

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


cdef class TopicPartPattern(TopicPart):
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
        self.header.header.ttype = evt_topic_type.TOPIC_PART_PATTERN

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


cdef heap_allocator* HEAP_ALLOCATOR = c_heap_allocator_new()
GLOBAL_INTERNAL_MAP = c_strmap_new(0, HEAP_ALLOCATOR, 1)


cpdef Topic get_internal_topic(str key, bint owner=False):
    global GLOBAL_INTERNAL_MAP
    if not GLOBAL_INTERNAL_MAP:
        raise RuntimeError('Internal map not initialized!')

    cdef Py_ssize_t key_length
    cdef const char* key_ptr = PyUnicode_AsUTF8AndSize(key, &key_length)
    cdef evt_topic* topic = NULL
    cdef int ret_code = c_strmap_get(GLOBAL_INTERNAL_MAP, key_ptr, key_length, <void**> &topic)
    if topic is NULL:
        return None
    return Topic.c_from_header(topic, owner)


cpdef dict get_internal_map():
    global GLOBAL_INTERNAL_MAP
    if not GLOBAL_INTERNAL_MAP:
        raise RuntimeError('Internal map not initialized!')

    cdef str key
    cdef evt_topic* topic
    cdef strmap_entry* entry = GLOBAL_INTERNAL_MAP.first
    cdef dict out = {}
    while entry:
        key = PyUnicode_FromStringAndSize(entry.key, entry.key_length)
        topic = <evt_topic*> entry.value
        out[key] = Topic.c_from_header(topic, False)
        entry = entry.next
    return out


cdef class TopicMatchResult:
    def __cinit__(self, size_t n_parts=0, bint alloc=False, **kwargs):
        if not alloc:
            if n_parts:
                raise RuntimeError('Can not allocator buffer when uninitialized!')
            return

        cdef size_t i
        cdef evt_topic_match* node = NULL
        for i in range(n_parts):
            node = c_topic_match_new(node, HEAP_ALLOCATOR, 1)
            if not node:
                c_topic_match_free(self.header, 1)
            elif not self.header:
                self.header = node
                self.owner = True

    def __dealloc__(self):
        if self.owner and self.header:
            c_topic_match_free(self.header, 1)

    @staticmethod
    cdef TopicMatchResult c_from_header(evt_topic_match* node, bint owner=True):
        cdef TopicMatchResult instance = TopicMatchResult.__new__(TopicMatchResult, alloc=False)
        instance.header = node
        instance.owner = owner
        return instance

    @staticmethod
    cdef dict c_match_res(evt_topic_match* node):
        if not node:
            raise RuntimeError('Not initialized!')
        cdef dict info = {
            'matched': node.matched,
            'part_a': TopicPart.c_from_header(node.part_a, False).c_cast() if node.part_a else None,
            'part_b': TopicPart.c_from_header(node.part_b, False).c_cast() if node.part_b else None,
            'literal': PyUnicode_FromStringAndSize(node.literal, node.literal_len) if node.literal else None,
        }
        return info

    def __repr__(self):
        return f'<evt_topic_match {"success" if self.matched else "failed"}>(nodes={self.length})'

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
        cdef evt_topic_match* node = self.header
        while i < idx:
            i += 1
            node = node.next

        return TopicMatchResult.c_match_res(node)

    def __iter__(self):
        cdef evt_topic_match* node = self.header
        while node:
            yield TopicMatchResult.c_match_res(node)
            node = node.next

    def to_dict(self):
        cdef dict out = {}
        cdef evt_topic_match* node = self.header
        cdef str literal

        while node:
            literal = PyUnicode_FromStringAndSize(node.literal, node.literal_len)
            out[literal] = TopicPart.c_from_header(node.part_b, False).c_cast()
            node = node.next
        return out

    property length:
        def __get__(self) -> size_t:
            if not self.header:
                raise RuntimeError('Not initialized!')
            cdef size_t i = 0
            cdef evt_topic_match* node = self.header
            while node:
                i += 1
                node = node.next
            return i

    property matched:
        def __get__(self) -> bint:
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef evt_topic_match* node = self.header
            while node:
                if not node.matched:
                    return False
                node = node.next
            return True


cdef class Topic:
    def __cinit__(self, str topic=None, *arg, bint alloc=True, **kwargs):
        if not alloc:
            if topic:
                raise RuntimeError('Can not assign topic string when uninitialized!')
            return

        if not topic:
            self.header = c_topic_new(NULL, 0, HEAP_ALLOCATOR, 1)
            self.owner = True
            if not self.header:
                raise MemoryError(f'Failed to init topic ":{topic}", check if the syntax is correct!')
            return

        cdef Py_ssize_t topic_length
        cdef const char* topic_ptr = PyUnicode_AsUTF8AndSize(topic, &topic_length)
        self.header = c_topic_new(topic_ptr, topic_length, HEAP_ALLOCATOR, 1)
        if not self.header:
            raise MemoryError('Failed to allocate memory!')

    def __dealloc__(self):
        if self.owner and self.header:
            c_topic_free(self.header, 1, 1)

    @staticmethod
    cdef Topic c_from_header(evt_topic* header, bint owner=False):
        cdef Topic instance = Topic.__new__(Topic, alloc=False)
        instance.header = header
        instance.owner = owner
        return instance

    cdef void c_append(self, evt_topic_part_variant* tpart):
        cdef evt_topic_type ttype = tpart.header.ttype
        if ttype == evt_topic_type.TOPIC_PART_EXACT:
            literal = tpart.exact.part
            literal_len = tpart.exact.part_len
        elif ttype == evt_topic_type.TOPIC_PART_ANY:
            literal = tpart.any.name
            literal_len = tpart.any.name_len
        elif ttype == evt_topic_type.TOPIC_PART_RANGE:
            literal = tpart.range.literal
            literal_len = tpart.range.literal_len
        elif ttype == evt_topic_type.TOPIC_PART_PATTERN:
            literal = tpart.pattern.pattern
            literal_len = tpart.pattern.pattern_len
        else:
            raise RuntimeError(f'Unknown topic type {TopicType(ttype)}')
        c_topic_append(self.header, literal, literal_len, ttype, 1)

    cdef void c_update_literal(self):
        c_topic_update_literal(self.header, 1)

    # --- Python Interface ---

    def __len__(self):
        if not self.header:
            raise RuntimeError('Not initialized!')
        return self.header.n

    def __bool__(self):
        if not self.header:
            return False
        return self.header.n > 0

    def __hash__(self):
        if not self.header:
            raise RuntimeError('Not initialized!')
        return self.header.hash

    def __eq__(self, Topic other):
        if not self.header or not other.header:
            raise RuntimeError('Not initialized!')
        return self.value == other.value

    def __repr__(self):
        if not self.header:
            return f'<{self.__class__.__name__} uninitialized>'
        return f'<{self.__class__.__name__} {"Exact" if self.header.is_exact else "Generic"}>(value="{self.value}", n_parts={self.header.n})'

    def __str__(self):
        if not self.header:
            raise RuntimeError('Not initialized!')
        return self.value

    def __iter__(self):
        if not self.header:
            raise RuntimeError('Not initialized!')

        cdef evt_topic_part_variant* part = self.header.parts
        while part:
            yield TopicPart.c_from_header(part, False).c_cast()
            part = part.header.next

    def __getitem__(self, ssize_t idx):
        if not self.header:
            raise RuntimeError('Not initialized!')

        cdef ssize_t n_parts = self.header.n
        if idx < -n_parts:
            raise IndexError(f'Index {idx} out of range!')
        elif idx < 0:
            idx += n_parts
        elif idx >= n_parts:
            raise IndexError(f'Index {idx} out of range!')

        cdef ssize_t i = 0
        cdef evt_topic_part_variant* part = self.header.parts

        while part:
            if i == idx:
                return TopicPart.c_from_header(part, False).c_cast()
            i += 1
            part = part.header.next
        raise IndexError('i')

    def __add__(self, object topic):
        if not self.header:
            raise RuntimeError('Not initialized!')

        cdef Topic aggregated = Topic.__new__(Topic)
        cdef evt_topic_part_variant* other_part
        cdef evt_topic_part_variant* tpart = self.header.parts
        cdef size_t i, n
        if isinstance(object, Topic):
            other_part = (<Topic> topic).header.parts
            n = self.header.n
            for i in range(n):
                aggregated.c_append(<evt_topic_part_variant*> tpart + i)
            n = (<Topic> topic).header.n
            for i in range(n):
                aggregated.c_append(<evt_topic_part_variant*> other_part + i)
        elif isinstance(object, TopicPart):
            other_part = (<TopicPart> topic).header
            n = self.header.n
            for i in range(n):
                aggregated.c_append(<evt_topic_part_variant*> tpart + i)
            aggregated.c_append(other_part)
        else:
            raise TypeError(f'Can not add {topic} to {self}, expected ether a {Topic} or {TopicPart}')
        aggregated.c_update_literal()
        return aggregated

    def __iadd__(self, object topic):
        if not self.header:
            raise RuntimeError('Not initialized!')

        cdef evt_topic_part_variant* other_part
        cdef size_t i, n
        if isinstance(object, Topic):
            other_part = (<Topic> topic).header.parts
            n = (<Topic> topic).header.n
            for i in range(n):
                self.c_append(<evt_topic_part_variant*> other_part + i)
        elif isinstance(object, TopicPart):
            other_part = (<TopicPart> topic).header
            self.c_append(other_part)
        else:
            raise TypeError(f'Can not add {topic} to {self}, expected ether a {Topic} or {TopicPart}')
        self.c_update_literal()
        return self

    def __call__(self, **kwargs):
        return self.format_map(kwargs, internalized=True, strict=False)

    @classmethod
    def from_parts(cls, topic_parts: Iterable[TopicPart]) -> Topic:
        cdef Topic aggregated = Topic.__new__(Topic)
        cdef TopicPart tpart
        for tpart in topic_parts:
            aggregated.c_append(tpart.header)
        aggregated.c_update_literal()
        return aggregated

    @classmethod
    def join(cls, topic_parts: Iterable[str]) -> Topic:
        cdef Topic aggregated = Topic.__new__(Topic)
        cdef str part
        cdef Py_ssize_t literal_len
        cdef const char* literal
        cdef evt_topic* topic = aggregated.header

        for tpart in topic_parts:
            literal = PyUnicode_AsUTF8AndSize(tpart, &literal_len)
            c_topic_append(topic, literal, literal_len, evt_topic_type.TOPIC_PART_EXACT, 1)
        c_topic_update_literal(topic, 1)
        return aggregated

    cpdef Topic append(self, TopicPart topic_part):
        if not self.header or not topic_part.header:
            raise RuntimeError('Not initialized!')

        cdef evt_topic_part_variant* part = topic_part.header
        cdef evt_topic* topic = self.header
        cdef evt_topic_part_variant* curr = topic.parts
        cdef heap_allocator* allocator = topic.allocator
        cdef char* literal
        cdef size_t literal_len

        # shortcut: just appending the buffer if it is owned and topic not using allocator.
        if topic_part.owner and not allocator:
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
            if part.header.ttype != evt_topic_type.TOPIC_PART_EXACT:
                self.header.is_exact = 0
        else:
            self.c_append(part)
        self.c_update_literal()
        return self

    cpdef TopicMatchResult match(self, Topic other):
        if not self.header:
            raise RuntimeError('Not initialized!')

        cdef evt_topic_match* match_res = c_topic_match(self.header, other.header, NULL, 1)
        return TopicMatchResult.c_from_header(match_res, True)

    def update_literal(self) -> Topic:
        self.c_update_literal()
        return self

    cpdef Topic format_map(self, dict mapping, bint internalized=True, bint strict=False):
        cdef evt_topic_part_variant* tpart = self.header.parts
        cdef evt_topic_type ttype
        cdef evt_topic* formatted = c_topic_new(NULL, 0, self.header.allocator, 1)
        cdef str key
        cdef const char* literal
        cdef Py_ssize_t literal_len

        while tpart:
            ttype = tpart.header.ttype
            # Case 1: For an exact part, simply append it.
            if ttype == evt_topic_type.TOPIC_PART_EXACT:
                c_topic_append(formatted, tpart.exact.part, tpart.exact.part_len, ttype, 1)
            # Case 2: For a named any part, check from the mapping dict.
            elif ttype == evt_topic_type.TOPIC_PART_ANY:
                key = PyUnicode_FromStringAndSize(tpart.any.name, tpart.any.name_len)
                # Raise KeyError if not found.
                if key not in mapping:
                    if strict:
                        c_topic_free(formatted, 1, 1)
                        raise KeyError(key)
                    else:
                        c_topic_append(formatted, tpart.any.name, tpart.any.name_len, evt_topic_type.TOPIC_PART_ANY, 1)
                else:
                    # Append the mapped value as an exact part.
                    literal = PyUnicode_AsUTF8AndSize(mapping[key], &literal_len)
                    c_topic_append(formatted, literal, literal_len, evt_topic_type.TOPIC_PART_EXACT, 1)
            else:
                c_topic_free(formatted, 1, 1)
                raise ValueError(f'Not supported topic type {TopicType(ttype)}')
            tpart = tpart.header.next

        c_topic_update_literal(formatted, 1)
        # If internalized, the TopicPart will not own the literal buffers.
        # Requested or not, in any way, the topic literal must be added to the internal map.
        return Topic.c_from_header(formatted, not internalized)

    def format(self, **kwargs) -> Topic:
        return self.format_map(kwargs, internalized=True, strict=False)

    property value:
        def __get__(self):
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef str literal = PyUnicode_FromStringAndSize(self.header.key, self.header.key_len)
            return literal

        def __set__(self, str value):
            if not self.header:
                raise RuntimeError('Not initialized!')

            cdef Py_ssize_t topic_length
            cdef const char* topic_ptr = PyUnicode_AsUTF8AndSize(value, &topic_length)
            cdef int assign_ret = c_topic_assign(self.header, topic_ptr, topic_length, 1)
            if assign_ret:
                raise ValueError(f'Failed to assign topic "{value}", check if syntax is correct!')

    property is_exact:
        def __get__(self) -> bint:
            if not self.header:
                raise RuntimeError('Not initialized!')
            return self.header.is_exact

    property addr:
        def __get__(self) -> uintptr_t:
            if self.header:
                return <uintptr_t> self.header
            return 0