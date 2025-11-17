"""
Native Python fallback implementation for PyTopic and related classes.

This module provides a pure Python implementation that mimics the behavior of the 
Cython-based c_topic module. It is used as a fallback when the Cython extension 
cannot be compiled (e.g., due to lack of Cython, GCC, or Clang).

The API is designed to match event_engine.capi.c_topic as closely as possible.
"""

from __future__ import annotations

import enum
import re
from collections import deque
from collections.abc import Iterable, Iterator
from functools import cached_property
from typing import Any, TypedDict, overload

# Global internal map for topic internalization
_GLOBAL_INTERNAL_MAP: dict[str, PyTopic] = {}
_GLOBAL_ALLOCATOR = None

# Topic parsing configuration (matching C defaults)
DEFAULT_TOPIC_SEP = '.'
DEFAULT_OPTION_SEP = '|'
DEFAULT_RANGE_BRACKETS = "()"
DEFAULT_WILDCARD_BRACKETS = "{}"
DEFAULT_WILDCARD_MARKER = '+'
DEFAULT_PATTERN_DELIM = '/'


def init_internal_map(default_capacity: int = 1024) -> dict[str, PyTopic]:
    """Initialize or return a shared internal byte map.

    Args:
        default_capacity: Default capacity (in bytes) used when creating the internal map.

    Returns:
        A ByteMap instance wrapping the shared internal bytemap.
    """
    global _GLOBAL_INTERNAL_MAP
    # In pure Python, we just use a dict, so capacity is ignored
    return _GLOBAL_INTERNAL_MAP


def clear_internal_map() -> None:
    """Clear and free the shared internal bytemap.

    This releases the internal resources and resets any cached references.
    """
    global _GLOBAL_INTERNAL_MAP
    _GLOBAL_INTERNAL_MAP.clear()


def get_internal_topic(key: str, owner: bool = False) -> PyTopic | None:
    """Get a registered topic from the internal map, if there is any.

    Args:
        key: the literal of the topic to look up.
        owner: whether to return a copy (True) or the original reference (False).
               In pure Python, ownership is always with the object itself.

    Returns:
        PyTopic instance if found or None.
    """
    global _GLOBAL_INTERNAL_MAP
    topic = _GLOBAL_INTERNAL_MAP.get(key)
    if topic is None:
        return None

    # Return a copy if owner is True, otherwise return reference
    if owner:
        new_topic = PyTopic.__new__(PyTopic)
        new_topic._parts = list(topic._parts)
        new_topic._value = topic._value
        new_topic._hash = topic._hash
        new_topic._is_exact = topic._is_exact
        return new_topic

    return topic


def get_internal_map() -> dict[str, PyTopic]:
    """Return a dictionary view of the internal topic map.

    Returns:
        A dictionary mapping topic literal strings to PyTopic instances.
    """
    global _GLOBAL_INTERNAL_MAP
    return _GLOBAL_INTERNAL_MAP.copy()


def init_allocator(init_capacity: int = 4096, with_shm: bool = False) -> None:
    """Initialize or return the global Allocator.

    Args:
        init_capacity: Initial capacity (in bytes) for the allocator.
                      (Ignored in pure Python implementation)
        with_shm: If True, create an allocator backed by shared memory.
                 (Ignored in pure Python implementation)

    Returns:
        None (allocator not used in pure Python implementation)

    Note:
        This function is provided for API compatibility with the Cython version,
        but does nothing in the pure Python implementation.
    """
    # No-op in pure Python - allocators are not needed
    pass


class PyTopicType(enum.IntEnum):
    """Enumeration of topic part types.

    Maps to the underlying C-level TopicType constants.
    """
    TOPIC_PART_EXACT = 0
    TOPIC_PART_ANY = 1
    TOPIC_PART_RANGE = 2
    TOPIC_PART_PATTERN = 3


class PyTopicPart:
    """Base Python wrapper for a single topic part.

    In the native Python implementation, all topic parts own their underlying memory.
    """

    __slots__ = ('_next', '_ttype')

    def __init__(self, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create or attach to a topic part.

        Args:
            alloc: If True, allocate and initialize internal structures.
        """
        self._next: PyTopicPart | None = None
        self._ttype: PyTopicType = PyTopicType.TOPIC_PART_EXACT

    def next(self) -> PyTopicPart:
        """Return the next topic part.

        Returns:
            The next PyTopicPart instance.

        Raises:
            StopIteration: If this is the last part.
        """
        if self._next is None:
            raise StopIteration
        return self._next

    @property
    def owner(self) -> bool:
        """bool: Whether this Python object owns the underlying memory (always True in native Python)."""
        return True

    @property
    def ttype(self) -> PyTopicType:
        """int: The topic part type as a PyTopicType."""
        return self._ttype

    @property
    def addr(self) -> int:
        """int: Numeric address / id of the underlying C structure."""
        return id(self)


class PyTopicPartExact(PyTopicPart):
    """Topic part representing an exact literal segment."""

    __slots__ = ('_part',)

    def __init__(self, part: str = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create an exact topic part.

        Args:
            part: Literal string to store. If omitted and alloc is True, an empty initialized part is created.
            alloc: If True, allocate underlying structures.
        """
        super().__init__(*args, alloc=alloc, **kwargs)
        self._ttype = PyTopicType.TOPIC_PART_EXACT
        self._part: str = part if part is not None else ""

    def __repr__(self) -> str:
        """Return human-readable representation."""
        return f'<TopicPartExact>(topic="{self.part}")'

    def __len__(self) -> int:
        """Return the length of the stored literal in bytes."""
        return len(self._part.encode('utf-8'))

    @property
    def part(self) -> str:
        """The literal string value for this part."""
        return self._part


class PyTopicPartAny(PyTopicPart):
    """Topic part representing a named wildcard."""

    __slots__ = ('_name',)

    def __init__(self, name: str = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create an 'any' topic part.

        Args:
            name: Optional name for the wildcard.
            alloc: If True, allocate underlying structures.
        """
        super().__init__(*args, alloc=alloc, **kwargs)
        self._ttype = PyTopicType.TOPIC_PART_ANY
        self._name: str = name if name is not None else ""

    def __repr__(self) -> str:
        """Return human-readable representation."""
        return f'<TopicPartAny>(name="{self.name}")'

    @property
    def name(self) -> str:
        """The wildcard name (identifier)."""
        return self._name


class PyTopicPartRange(PyTopicPart):
    """Topic part representing a range (choice) among multiple literals."""

    __slots__ = ('_options',)

    def __init__(self, options: list[str] = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create a range part.

        Args:
            options: List of literal option strings.
            alloc: If True, allocate underlying structures.
        """
        super().__init__(*args, alloc=alloc, **kwargs)
        self._ttype = PyTopicType.TOPIC_PART_RANGE
        self._options: list[str] = options if options is not None else []

    def __repr__(self) -> str:
        """Return human-readable representation."""
        return f'<TopicPartRange>(n={len(self._options)}, options={self._options})'

    def __len__(self) -> int:
        """Return the number of options."""
        return len(self._options)

    def __iter__(self) -> Iterator[str]:
        """Iterate over option strings."""
        return iter(self._options)

    def options(self) -> Iterator[str]:
        """Yield option strings in order.

        Yields:
            Each option as a Python string.
        """
        return iter(self._options)


class PyTopicPartPattern(PyTopicPart):
    """Topic part representing a regex pattern."""

    __slots__ = ('_pattern', '_compiled_regex')

    def __init__(self, regex: str = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create a pattern topic part.

        Args:
            regex: Regular expression string.
            alloc: If True, allocate underlying structures.
        """
        super().__init__(*args, alloc=alloc, **kwargs)
        self._ttype = PyTopicType.TOPIC_PART_PATTERN
        self._pattern: str = regex if regex is not None else ""
        self._compiled_regex: re.Pattern | None = None

    def __repr__(self) -> str:
        """Return human-readable representation."""
        return f'<TopicPartPattern>(regex="{self.pattern}")'

    @property
    def pattern(self) -> str:
        """str: The raw regex pattern string."""
        return self._pattern

    @property
    def regex(self) -> re.Pattern:
        """re.Pattern: Compiled regex object for the pattern."""
        if self._compiled_regex is None:
            self._compiled_regex = re.compile(self._pattern)
        return self._compiled_regex


class TopicMatchNode(TypedDict):
    """TypedDict describing a single match node returned by PyTopicMatchResult accessors.

    Keys:
        matched: Whether this node matched.
        part_a: The left-side topic part (or None).
        part_b: The right-side topic part (or None).
        literal: The literal string associated with this node (if any).
    """
    matched: bool
    part_a: PyTopicPart | None
    part_b: PyTopicPart | None
    literal: str | None


class PyTopicMatchResult:
    """Container for topic part match results (linked list-like).

    Provides iteration and indexing over match nodes and utilities to convert results.

    The public API yields `TopicMatchNode` entries for per-node accessors.
    """

    def __init__(self, n_parts: int = 0, alloc: bool = False, allocator: Any = None, **kwargs: Any) -> None:
        """Allocate or attach a chain of match result nodes.

        Args:
            n_parts: Number of nodes to pre-create.
            alloc: If True, allocate underlying structures.
            allocator: Optional Allocator (ignored in pure Python implementation).
        """
        self._nodes: deque[TopicMatchNode] = deque()
        if alloc and n_parts > 0:
            for _ in range(n_parts):
                self._nodes.append({'matched': False, 'part_a': None, 'part_b': None, 'literal': None})

    def __repr__(self) -> str:
        """Return a compact representation with success/failure and length."""
        status = "success" if self.matched else "failed"
        return f'<TopicPartMatchResult {status}>(nodes={self.length})'

    def __bool__(self) -> bool:
        """True if all nodes matched."""
        return self.matched

    def __len__(self) -> int:
        """Return number of nodes in the result chain."""
        return len(self._nodes)

    def __getitem__(self, idx: int) -> TopicMatchNode:
        """Return a single node's info as a TopicMatchNode.

        Args:
            idx: Index of the node (supports negative indexing).

        Returns:
            A TopicMatchNode TypedDict containing 'matched', 'part_a', 'part_b', 'literal'.

        Raises:
            IndexError: If idx is out of range.
        """
        # deque doesn't support negative indexing directly, convert to list for that
        nodes_list = list(self._nodes)
        return nodes_list[idx]

    def __iter__(self) -> Iterator[TopicMatchNode]:
        """Iterate over node info dicts in sequence."""
        return iter(self._nodes)

    def to_dict(self) -> dict[str, PyTopicPart]:
        """Convert match results into a dictionary mapping literal -> matched part.

        Returns:
            A mapping from literal string to the matched PyTopicPart.
        """
        result = {}
        for node in self._nodes:
            if node['literal'] and node['part_b']:
                result[node['literal']] = node['part_b']
        return result

    @property
    def owner(self) -> bool:
        """bool: Whether this Python object owns the underlying memory (always True in native Python)."""
        return True

    @property
    def length(self) -> int:
        """int: Number of nodes in the result chain."""
        return len(self._nodes)

    @cached_property
    def matched(self) -> bool:
        """bool: True if every node in the chain reports matched == True."""
        return all(node['matched'] for node in self._nodes) if self._nodes else False


class PyTopic:
    """High-level Python representation of a parsed topic.

    PyTopic instances internalize their literal content into a shared internal dict.
    All topics created via the normal constructor are internalized into the global map and do not
    own the underlying character storage (the buffer is bound to the global map).
    """

    __slots__ = ('_parts', '_value', '_hash', '_is_exact')

    def __init__(self, topic: str = None, *args: Any, alloc: bool = True, allocator: Any = None, **kwargs: Any):
        """Create a PyTopic from a topic string.

        Args:
            topic: Topic string to parse.
            alloc: If True, allocate and initialize (default for normal usage).
            allocator: Optional allocator (ignored in pure Python implementation).
        """
        self._parts: list[PyTopicPart] = []
        self._value: str = ""
        self._hash: int = 0
        self._is_exact: bool = True

        if not alloc:
            if topic:
                raise RuntimeError('Can not assign topic string when uninitialized!')
            return

        if topic:
            self._parse_topic(topic)
            # Internalize into global map
            global _GLOBAL_INTERNAL_MAP
            if topic not in _GLOBAL_INTERNAL_MAP:
                _GLOBAL_INTERNAL_MAP[topic] = self
            self._value = topic
            self._hash = hash(topic)

    def _parse_topic(self, topic_str: str) -> None:
        """Parse a topic string into parts."""
        if not topic_str:
            return

        parts = []
        i = 0
        current_part = ""

        while i < len(topic_str):
            char = topic_str[i]

            # Check for pattern delimiter
            if char == DEFAULT_PATTERN_DELIM:
                # Find matching closing delimiter
                j = i + 1
                while j < len(topic_str) and topic_str[j] != DEFAULT_PATTERN_DELIM:
                    j += 1
                if j < len(topic_str):
                    # Extract pattern
                    pattern = topic_str[i + 1:j]
                    parts.append(PyTopicPartPattern(pattern, alloc=True))
                    self._is_exact = False
                    i = j + 1
                    if i < len(topic_str) and topic_str[i] == DEFAULT_TOPIC_SEP:
                        i += 1
                    continue

            # Check for range (options)
            elif char == DEFAULT_RANGE_BRACKETS[0]:
                # Find matching closing bracket
                j = i + 1
                depth = 1
                while j < len(topic_str) and depth > 0:
                    if topic_str[j] == DEFAULT_RANGE_BRACKETS[0]:
                        depth += 1
                    elif topic_str[j] == DEFAULT_RANGE_BRACKETS[1]:
                        depth -= 1
                    j += 1
                if depth == 0:
                    # Extract options
                    options_str = topic_str[i + 1:j - 1]
                    options = [opt for opt in options_str.split(DEFAULT_OPTION_SEP) if opt]
                    parts.append(PyTopicPartRange(options, alloc=True))
                    self._is_exact = False
                    i = j
                    if i < len(topic_str) and topic_str[i] == DEFAULT_TOPIC_SEP:
                        i += 1
                    continue

            # Check for wildcard with brackets {name}
            elif char == DEFAULT_WILDCARD_BRACKETS[0]:
                j = i + 1
                while j < len(topic_str) and topic_str[j] != DEFAULT_WILDCARD_BRACKETS[1]:
                    j += 1
                if j < len(topic_str):
                    name = topic_str[i + 1:j]
                    parts.append(PyTopicPartAny(name, alloc=True))
                    self._is_exact = False
                    i = j + 1
                    if i < len(topic_str) and topic_str[i] == DEFAULT_TOPIC_SEP:
                        i += 1
                    continue

            # Check for wildcard marker +
            elif char == DEFAULT_WILDCARD_MARKER:
                # Read the name after +
                j = i + 1
                name_start = j
                while j < len(topic_str) and topic_str[j] != DEFAULT_TOPIC_SEP:
                    j += 1
                name = topic_str[name_start:j]
                parts.append(PyTopicPartAny(name, alloc=True))
                self._is_exact = False
                i = j
                if i < len(topic_str) and topic_str[i] == DEFAULT_TOPIC_SEP:
                    i += 1
                continue

            # Regular part - read until separator
            elif char == DEFAULT_TOPIC_SEP:
                if current_part:
                    parts.append(PyTopicPartExact(current_part, alloc=True))
                    current_part = ""
                i += 1
            else:
                current_part += char
                i += 1

        # Add final part
        if current_part:
            parts.append(PyTopicPartExact(current_part, alloc=True))

        # Link parts
        for j in range(len(parts) - 1):
            parts[j]._next = parts[j + 1]

        self._parts = parts

    def _update_literal(self) -> None:
        """Reconstruct the literal value from parts."""
        if not self._parts:
            self._value = ""
            return

        parts_strs = []
        for part in self._parts:
            if isinstance(part, PyTopicPartExact):
                parts_strs.append(part.part)
            elif isinstance(part, PyTopicPartAny):
                parts_strs.append(f"{DEFAULT_WILDCARD_BRACKETS[0]}{part.name}{DEFAULT_WILDCARD_BRACKETS[1]}")
            elif isinstance(part, PyTopicPartRange):
                options_str = DEFAULT_OPTION_SEP.join(part._options)
                parts_strs.append(f"{DEFAULT_RANGE_BRACKETS[0]}{options_str}{DEFAULT_RANGE_BRACKETS[1]}")
            elif isinstance(part, PyTopicPartPattern):
                parts_strs.append(f"{DEFAULT_PATTERN_DELIM}{part.pattern}{DEFAULT_PATTERN_DELIM}")

        self._value = DEFAULT_TOPIC_SEP.join(parts_strs)
        self._hash = hash(self._value)

    def __len__(self) -> int:
        """Return the number of parts in the topic."""
        return len(self._parts)

    def __iter__(self) -> Iterator[PyTopicPart]:
        """Iterate over topic parts (yields PyTopicPart subclasses)."""
        return iter(self._parts)

    def __getitem__(self, idx: int) -> PyTopicPart:
        """Return the topic part at index `idx`.

        Supports negative indexing.

        Raises:
            IndexError: If index is out of range.
        """
        return self._parts[idx]

    @overload
    def __add__(self, topic: 'PyTopic') -> 'PyTopic':
        ...

    @overload
    def __add__(self, topic: PyTopicPart) -> 'PyTopic':
        ...

    def __add__(self, topic: 'PyTopic | PyTopicPart') -> 'PyTopic':
        """Return a new PyTopic that aggregates this topic with another PyTopic or PyTopicPart.

        Behavior:
            - `__add__` creates and returns a copy; both operands remain unchanged.
            - Use `append` or `__iadd__` for in-place modifications.

        Args:
            topic: Either a PyTopic or PyTopicPart.

        Returns:
            A new aggregated PyTopic.

        Raises:
            TypeError: When the operand type is unsupported.
        """
        new_topic = PyTopic.__new__(PyTopic)
        new_topic._parts = list(self._parts)
        new_topic._is_exact = self._is_exact

        if isinstance(topic, PyTopic):
            new_topic._parts.extend(topic._parts)
            if not topic._is_exact:
                new_topic._is_exact = False
        elif isinstance(topic, PyTopicPart):
            new_topic._parts.append(topic)
            if topic.ttype != PyTopicType.TOPIC_PART_EXACT:
                new_topic._is_exact = False
        else:
            raise TypeError(f'Can not add {topic} to {self}, expected either a PyTopic or PyTopicPart')

        new_topic._update_literal()
        return new_topic

    @overload
    def __iadd__(self, topic: 'PyTopic') -> 'PyTopic':
        ...

    @overload
    def __iadd__(self, topic: PyTopicPart) -> 'PyTopic':
        ...

    def __iadd__(self, topic: 'PyTopic | PyTopicPart') -> 'PyTopic':
        """In-place append another PyTopic or PyTopicPart.

        Behavior:
            - Modifies `self` in place and leaves the other operand unchanged.
            - This is equivalent to `self.append(...)` and returns `self`.
        """
        if isinstance(topic, PyTopic):
            self._parts.extend(topic._parts)
            if not topic._is_exact:
                self._is_exact = False
        elif isinstance(topic, PyTopicPart):
            self._parts.append(topic)
            if topic.ttype != PyTopicType.TOPIC_PART_EXACT:
                self._is_exact = False
        else:
            raise TypeError(f'Can not add {topic} to {self}, expected either a PyTopic or PyTopicPart')

        self._update_literal()
        return self

    def __hash__(self):
        """Return hash based on the topic's literal value.

        The hash is precomputed during initialization for efficiency.

        Returns:
            A uint64_t hash integer.
        """
        return self._hash

    def __eq__(self, other: 'PyTopic') -> bool:
        """Check equality between this topic and another topic.

        Args:
            other: The other PyTopic to compare against.

        Returns:
            True if both topics have the same literal value.
        """
        if not isinstance(other, PyTopic):
            return False
        return self._value == other._value

    def __repr__(self) -> str:
        """Return string representation."""
        exact_or_generic = "Exact" if self._is_exact else "Generic"
        return f'<{self.__class__.__name__} {exact_or_generic}>(value="{self._value}", n_parts={len(self._parts)})'

    def __str__(self) -> str:
        """Return the topic literal value."""
        return self._value

    def __call__(self, **kwargs) -> 'PyTopic':
        """Alias of ``format`` method to format the topic by replacing named wildcards with provided values."""
        return self.format_map(kwargs, internalized=True, strict=False)

    @classmethod
    def from_parts(cls, topic_parts: Iterable[PyTopicPart]) -> PyTopic:
        """Build a PyTopic from an iterable of PyTopicPart instances."""
        new_topic = cls.__new__(cls)
        new_topic._parts = list(topic_parts)
        new_topic._is_exact = all(p.ttype == PyTopicType.TOPIC_PART_EXACT for p in new_topic._parts)
        new_topic._update_literal()
        return new_topic

    @classmethod
    def join(cls, topic_parts: Iterable[str]) -> 'PyTopic':
        """Build a PyTopic from an iterable of literal strings.

        Each string is appended as an exact part.

        Notes:
            - This is a higher-level helper for simple literal-only topics.
            - For complex parts that need escaping or patterns, use `from_parts`.
        """
        parts = [PyTopicPartExact(part, alloc=True) for part in topic_parts]
        return cls.from_parts(parts)

    def append(self, topic_part: PyTopicPart) -> 'PyTopic':
        """Append a PyTopicPart to this topic (high-level API).

        Args:
            topic_part: The part to append.

        Returns:
            Self for chaining.

        Raises:
            RuntimeError: If either topic or part is uninitialized.
        """
        self._parts.append(topic_part)
        if topic_part.ttype != PyTopicType.TOPIC_PART_EXACT:
            self._is_exact = False
        self._update_literal()
        return self

    def match(self, other: 'PyTopic') -> PyTopicMatchResult:
        """Match this topic against another topic.

        Args:
            other: The topic to match against.

        Returns:
            A PyTopicMatchResult describing per-part matches.
        """
        result = PyTopicMatchResult(alloc=True)

        # Simple matching logic: compare parts
        self_parts = list(self._parts)
        other_parts = list(other._parts)

        max_len = max(len(self_parts), len(other_parts))

        for i in range(max_len):
            node: TopicMatchNode = {
                'matched': False,
                'part_a': None,
                'part_b': None,
                'literal': None
            }

            if i >= len(self_parts) or i >= len(other_parts):
                # Length mismatch
                result._nodes.append(node)
                continue

            part_a = self_parts[i]
            part_b = other_parts[i]
            node['part_a'] = part_a
            node['part_b'] = part_b

            # Match logic
            if part_a.ttype == PyTopicType.TOPIC_PART_EXACT and part_b.ttype == PyTopicType.TOPIC_PART_EXACT:
                # Exact match - cast to PyTopicPartExact
                part_a_exact = part_a if isinstance(part_a, PyTopicPartExact) else None
                part_b_exact = part_b if isinstance(part_b, PyTopicPartExact) else None
                if part_a_exact and part_b_exact and part_a_exact.part == part_b_exact.part:
                    node['matched'] = True
                    node['literal'] = part_a_exact.part
            elif part_a.ttype == PyTopicType.TOPIC_PART_ANY:
                # Wildcard matches anything
                node['matched'] = True
                if part_b.ttype == PyTopicType.TOPIC_PART_EXACT:
                    part_b_exact = part_b if isinstance(part_b, PyTopicPartExact) else None
                    if part_b_exact:
                        node['literal'] = part_b_exact.part
            elif part_b.ttype == PyTopicType.TOPIC_PART_ANY:
                # Wildcard matches anything
                node['matched'] = True
                if part_a.ttype == PyTopicType.TOPIC_PART_EXACT:
                    part_a_exact = part_a if isinstance(part_a, PyTopicPartExact) else None
                    if part_a_exact:
                        node['literal'] = part_a_exact.part
            elif part_a.ttype == PyTopicType.TOPIC_PART_RANGE:
                # Range match - cast to PyTopicPartRange
                if part_b.ttype == PyTopicType.TOPIC_PART_EXACT:
                    part_a_range = part_a if isinstance(part_a, PyTopicPartRange) else None
                    part_b_exact = part_b if isinstance(part_b, PyTopicPartExact) else None
                    if part_a_range and part_b_exact and part_b_exact.part in part_a_range._options:
                        node['matched'] = True
                        node['literal'] = part_b_exact.part
            elif part_b.ttype == PyTopicType.TOPIC_PART_RANGE:
                # Range match (reversed) - cast to PyTopicPartRange
                if part_a.ttype == PyTopicType.TOPIC_PART_EXACT:
                    part_a_exact = part_a if isinstance(part_a, PyTopicPartExact) else None
                    part_b_range = part_b if isinstance(part_b, PyTopicPartRange) else None
                    if part_a_exact and part_b_range and part_a_exact.part in part_b_range._options:
                        node['matched'] = True
                        node['literal'] = part_a_exact.part
            elif part_a.ttype == PyTopicType.TOPIC_PART_PATTERN:
                # Pattern match - cast to PyTopicPartPattern
                if part_b.ttype == PyTopicType.TOPIC_PART_EXACT:
                    part_a_pattern = part_a if isinstance(part_a, PyTopicPartPattern) else None
                    part_b_exact = part_b if isinstance(part_b, PyTopicPartExact) else None
                    if part_a_pattern and part_b_exact and part_a_pattern.regex.match(part_b_exact.part):
                        node['matched'] = True
                        node['literal'] = part_b_exact.part
            elif part_b.ttype == PyTopicType.TOPIC_PART_PATTERN:
                # Pattern match (reversed) - cast to PyTopicPartPattern
                if part_a.ttype == PyTopicType.TOPIC_PART_EXACT:
                    part_a_exact = part_a if isinstance(part_a, PyTopicPartExact) else None
                    part_b_pattern = part_b if isinstance(part_b, PyTopicPartPattern) else None
                    if part_a_exact and part_b_pattern and part_b_pattern.regex.match(part_a_exact.part):
                        node['matched'] = True
                        node['literal'] = part_a_exact.part

            result._nodes.append(node)

        return result

    def update_literal(self) -> 'PyTopic':
        """Update the internal literal buffer to reflect the current parts.

        This is useful after in-place modifications of the subordinate TopicParts.
        To avoid inconsistencies, call this method to regenerate the internal literal.

        Returns:
            Self for chaining.

        Raises:
            RuntimeError: If the topic is uninitialized.
        """
        self._update_literal()
        return self

    def format(self, **kwargs) -> PyTopic:
        """Format the topic by replacing named wildcards with provided values.

        Args:
            **kwargs: Mapping from wildcard names to replacement strings.

        Returns:
            A new Exact PyTopic with wildcards replaced by the provided values.

        Raises:
            KeyError: If a required wildcard name is missing in kwargs.
            ValueError: If having subordinate parts that are not exact or wildcards.
        """
        return self.format_map(kwargs, internalized=True, strict=False)

    def format_map(self, mapping: dict[str, str], internalized: bool = True, strict: bool = False) -> PyTopic:
        """Format the topic by replacing named wildcards with provided values from a mapping.

        Args:
            mapping: Dictionary mapping wildcard names to replacement strings.
            internalized: If True, the returned topic is internalized into the global map and not owning its underlying buffer.
                          If False, the returned topic owns its internal buffer.
            strict: If True, raises KeyError if a wildcard name is missing in mapping.

        Returns:
            A new PyTopic with wildcards replaced by the provided values. If strict is True, the new PyTopic is guaranteed to be an exact PyTopic.

        Raises:
            KeyError: If a required wildcard name is missing in mapping.
            ValueError: If having subordinate parts that are not exact or wildcards.
        """
        new_parts = []

        for part in self._parts:
            if part.ttype == PyTopicType.TOPIC_PART_EXACT:
                part_exact = part if isinstance(part, PyTopicPartExact) else None
                if part_exact:
                    new_parts.append(PyTopicPartExact(part_exact.part, alloc=True))
            elif part.ttype == PyTopicType.TOPIC_PART_ANY:
                part_any = part if isinstance(part, PyTopicPartAny) else None
                if part_any:
                    if part_any.name not in mapping:
                        if strict:
                            raise KeyError(part_any.name)
                        else:
                            new_parts.append(PyTopicPartAny(part_any.name, alloc=True))
                    else:
                        new_parts.append(PyTopicPartExact(mapping[part_any.name], alloc=True))
            else:
                raise ValueError(f'Not supported topic type {part.ttype}')

        new_topic = PyTopic.from_parts(new_parts)

        if internalized:
            global _GLOBAL_INTERNAL_MAP
            if new_topic._value not in _GLOBAL_INTERNAL_MAP:
                _GLOBAL_INTERNAL_MAP[new_topic._value] = new_topic

        return new_topic

    @property
    def value(self) -> str:
        """str: The full topic literal value.

        Getting returns the current literal. Setting attempts to assign and will raise
        ValueError on syntax errors. Setting mutates the internalized buffer and will
        re-register the topic in the internal mapping.
        """
        return self._value

    @value.setter
    def value(self, value: str) -> None:
        """Set the topic literal value.

        Args:
            value: New topic string to assign.

        Raises:
            ValueError: If assignment fails due to syntax error.

        Notes:
            - Mutating `value` is an expensive operation (de-register / re-register). Avoid frequent calls.
            - Prefer lazy-init: create an empty topic and set `value` once when needed.
        """
        # Remove from internal map if present
        global _GLOBAL_INTERNAL_MAP
        if self._value in _GLOBAL_INTERNAL_MAP and _GLOBAL_INTERNAL_MAP[self._value] is self:
            del _GLOBAL_INTERNAL_MAP[self._value]

        # Parse new value
        self._parts = []
        self._value = ""
        self._hash = 0
        self._is_exact = True

        try:
            self._parse_topic(value)
            self._value = value
            self._hash = hash(value)

            # Re-internalize
            if value not in _GLOBAL_INTERNAL_MAP:
                _GLOBAL_INTERNAL_MAP[value] = self
        except Exception as e:
            raise ValueError(f'Failed to assign topic "{value}", check if syntax is correct!') from e

    @property
    def owner(self) -> bool:
        """bool: Whether this Python object owns the underlying memory (always True in native Python)."""
        return True

    @property
    def is_exact(self) -> bool:
        """bool: True if the topic consists only of exact parts (no wildcards, ranges, or patterns)."""
        return self._is_exact

    @property
    def addr(self) -> int:
        """int: Numeric address / id of the underlying structure."""
        return id(self)
