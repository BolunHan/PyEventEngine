import enum
import re
from collections.abc import Iterator, Iterable
from typing import Any, TypedDict, overload

from .c_allocator import Allocator
from .c_bytemap import ByteMap


def init_internal_map(default_capacity: int = ...) -> ByteMap:
    """Initialize or return a shared internal byte map.

    Args:
        default_capacity: Default capacity (in bytes) used when creating the internal map.

    Returns:
        A ByteMap instance wrapping the shared internal bytemap.
    """


def clear_internal_map() -> None:
    """Clear and free the shared internal bytemap.

    This releases the internal resources and resets any cached references.
    """


def get_internal_topic(key: str, owner: bool = False) -> PyTopic | None:
    """ Get a registered topic from the internal map, if there is any.

    Args:
        key: the literal of the topic to look up.
        owner: whether the returned PyTopic owns the underlying memory. If so, when the PyTopic is deallocated,
               the underlying memory will be freed and de-registered. If False, the PyTopic is just a wrapper around the internal memory.

    Returns:
        PyTopic instance if found or None.
    """


def get_internal_map() -> dict[str, PyTopic]:
    """Return a dictionary view of the internal topic map.

    Returns:
        A dictionary mapping topic literal strings to PyTopic instances.
    """


def init_allocator(init_capacity: int = ..., with_shm: bool = False) -> Allocator:
    """Initialize or return the global Allocator.

    Args:
        init_capacity: Initial capacity (in bytes) for the allocator.
        with_shm: If True, create an allocator backed by shared memory.

    Returns:
        The global Allocator instance.
    """


class PyTopicType(enum.IntEnum):
    """Enumeration of topic part types.

    Maps to the underlying C-level TopicType constants.
    """
    TOPIC_PART_EXACT: int
    TOPIC_PART_ANY: int
    TOPIC_PART_RANGE: int
    TOPIC_PART_PATTERN: int


class PyTopicPart:
    """Base Python wrapper for a single topic part.

    Attributes:
        owner: Whether this Python object owns/free the underlying memory.
    """

    owner: bool

    def __init__(self, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create or attach to a topic part.

        Args:
            alloc: If True, allocate and initialize internal C structures.
        """

    def next(self) -> PyTopicPart:
        """Return the next topic part.

        Returns:
            The next PyTopicPart instance.

        Raises:
            StopIteration: If this is the last part.
        """

    @property
    def ttype(self) -> PyTopicType:
        """int: The topic part type as a PyTopicType."""

    @property
    def addr(self) -> int:
        """int: Numeric address / id of the underlying C structure."""


class PyTopicPartExact(PyTopicPart):
    """Topic part representing an exact literal segment."""

    def __init__(self, part: str = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create an exact topic part.

        Args:
            part: Literal string to store. If omitted and alloc is True, an empty initialized part is created.
            alloc: If True, allocate underlying C memory.
        """

    def __repr__(self) -> str:
        """Return human-readable representation."""

    def __len__(self) -> int:
        """Return the length of the stored literal in bytes."""

    @property
    def part(self) -> str:
        """The literal string value for this part."""


class PyTopicPartAny(PyTopicPart):
    """Topic part representing a named wildcard."""

    def __init__(self, name: str = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create an 'any' topic part.

        Args:
            name: Optional name for the wildcard.
            alloc: If True, allocate underlying C memory.
        """

    def __repr__(self) -> str:
        """Return human-readable representation."""

    @property
    def name(self) -> str:
        """The wildcard name (identifier)."""


class PyTopicPartRange(PyTopicPart):
    """Topic part representing a range (choice) among multiple literals."""

    def __init__(self, options: list[str] = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create a range part.

        Args:
            options: List of literal option strings.
            alloc: If True, allocate underlying C memory.
        """

    def __repr__(self) -> str:
        """Return human-readable representation."""

    def __len__(self) -> int:
        """Return the number of options."""

    def __iter__(self) -> Iterator[str]:
        """Iterate over option strings."""

    def options(self) -> Iterator[str]:
        """Yield option strings in order.

        Yields:
            Each option as a Python string.
        """


class PyTopicPartPattern(PyTopicPart):
    """Topic part representing a regex pattern."""

    def __init__(self, regex: str = None, *args: Any, alloc: bool = False, **kwargs: Any) -> None:
        """Create a pattern topic part.

        Args:
            regex: Regular expression string.
            alloc: If True, allocate underlying C memory.
        """

    def __repr__(self) -> str:
        """Return human-readable representation."""

    @property
    def pattern(self) -> str:
        """str: The raw regex pattern string."""

    @property
    def regex(self) -> re.Pattern:
        """re.Pattern: Compiled regex object for the pattern."""


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

    owner: bool

    def __init__(self, n_parts: int = 0, alloc: bool = False, allocator: Allocator = None, **kwargs: Any) -> None:
        """Allocate or attach a chain of match result nodes.

        Args:
            n_parts: Number of nodes to pre-create.
            alloc: If True, allocate underlying C structures.
            allocator: Optional Allocator used for internal node allocations.
        """

    def __repr__(self) -> str:
        """Return a compact representation with success/failure and length."""

    def __bool__(self) -> bool:
        """True if all nodes matched."""

    def __len__(self) -> int:
        """Return number of nodes in the result chain."""

    def __getitem__(self, idx: int) -> TopicMatchNode:
        """Return a single node's info as a TopicMatchNode.

        Args:
            idx: Index of the node (supports negative indexing).

        Returns:
            A TopicMatchNode TypedDict containing 'matched', 'part_a', 'part_b', 'literal'.

        Raises:
            IndexError: If idx is out of range.
        """

    def __iter__(self) -> Iterator[TopicMatchNode]:
        """Iterate over node info dicts in sequence."""

    def to_dict(self) -> dict[str, PyTopicPart]:
        """Convert match results into a dictionary mapping literal -> matched part.

        Returns:
            A mapping from literal string to the matched PyTopicPart.
        """

    @property
    def length(self) -> int:
        """int: Number of nodes in the result chain."""

    @property
    def matched(self) -> bool:
        """bool: True if every node in the chain reports matched == True."""


class PyTopic:
    """High-level Python representation of a parsed topic.

    PyTopic instances internalize their literal content into a shared internal buffer / ByteMap.
    All topics created via the normal constructor are internalized into the global ByteMap and do not
    own the underlying character storage (the buffer is bound to the global map).

    Examples:

        >>> # This internalizes the literal string "Realtime.TickData.600010.SH" into the global ByteMap
        ... t1 = PyTopic("Realtime.TickData.600010.SH")
        >>> assert not t1.owner

        >>> # Because t1 does not own its buffer we can create another topic with the same literal string
        ... t2 = PyTopic.__new__(PyTopic, "Realtime.TickData.600010.SH")
        >>> # Creation of t2 is faster due to internalization.
        ... assert id(t1) != id(t2)

        ``t1`` and ``t2`` are different Python objects but may share the same underlying buffer address.
        If the allocator is initialized with shared memory, another process can also create topics
        referencing the same internal ByteMap.

    Topic parser
        The separator, option delimiter and wildcard/pattern markers can be customized at build time by
        changing the following C macros before compiling the extension:

        ```
        #define DEFAULT_TOPIC_SEP '.'
        #define DEFAULT_OPTION_SEP '|'
        #define DEFAULT_RANGE_BRACKETS "()"
        #define DEFAULT_WILDCARD_MARKER '+'
        #define DEFAULT_PATTERN_DELIM '/'
        ```

        For example, compile with ``-DDEFAULT_TOPIC_SEP='/'`` to change the topic separator to ``/``.

        When parsing a topic string:
        - If the pattern delimiter appears in balanced pairs, the enclosed text is parsed as a regex
          pattern part (``PyTopicPartPattern``).
        - A part beginning with the wildcard marker is parsed as a wildcard part (``PyTopicPartAny``).
        - A part enclosed by the range brackets and containing the option separator (or NUL) is parsed
          as a range part (``PyTopicPartRange``). Options are separated by the option separator or NUL;
          empty options are not allowed.
        - All other parts are parsed as exact literal parts (``PyTopicPartExact``).

    Example:

        >>> t = PyTopic(r'Realtime.(TickData|TradeData)./^[0-9]{6}\.(SZ|SH)$/.+suffix')
        ... for tp in t:
        >>>     print(tp)
        <TopicPartExact>(topic="Realtime")
        <TopicPartRange>(n=2, options=['TickData', 'TradeData'])
        <TopicPartPattern>(regex="^[0-9]{6}\.(SZ|SH)$")
        <TopicPartAny>(name="suffix")

        >>> t = PyTopic('Realtime.TickData.{ticker}')
        ... for tp in t:
        ...     print(tp)
        <TopicPartExact>(topic="Realtime")
        <TopicPartExact>(topic="TickData")
        <TopicPartAny>(name="ticker")
        Malformed or ill-formatted literal strings may raise MemoryError during parsing.

    Owning a topic (lazy init)
        To create a topic that owns its internal buffer (``owner`` is True), use lazy initialization:

        >>> t3 = PyTopic.__new__(PyTopic, alloc=True)  # create an empty topic with allocated buffer
        >>> assert t3.owner
        >>> t3.value = "Realtime.TickData.600010.SH"    # set the value once
        ... assert t3.value == "Realtime.TickData.600010.SH"
        >>> assert t3.owner

    Note:
        assigning a literal that includes the topic separator inside a logical part (for example a ticker like ``"600010.SH"``)
        will be split by the parser into multiple parts:

        >>> t3[-2], t3[-1]
        (<TopicPartExact>(topic="600010"), <TopicPartExact>(topic="SH"))

        To avoid unwanted splitting, construct the topic from explicit parts:

        >>> t4 = PyTopic.from_parts([
        ...     PyTopicPartExact("Realtime", alloc=True),
        ...     PyTopicPartExact("TickData", alloc=True),
        ...     PyTopicPartExact("600010.SH", alloc=True),
        ... ])
        >>> assert t4.value == "Realtime.TickData.600010.SH"
        >>> t4[-1]
        <TopicPartExact>(topic="600010.SH")

        Or use the convenience join helper:

        >>> t5 = PyTopic.join(["Realtime", "TickData", "600010.SH"])
        ... assert t5.value == "Realtime.TickData.600010.SH"
        >>> t5[-1]
        <TopicPartExact>(topic="600010.SH")

    Empty parts and parsing caveats
        The topic string must not contain empty parts. For example, ``"Realtime..TickData"``:

        >>> t6 = PyTopic("Realtime..TickData")
        ... for tp in t6:
        >>>     print(tp)
        <TopicPartExact>(topic="Realtime")
        <TopicPartExact>(topic="TickData")

        The empty part is ignored during parsing (parsed parts omit the empty entry) but the literal string
        remains unchanged:

        >>> t6.value
        'Realtime..TickData'

        This inconsistency between the literal string and parsed parts can be confusing—use with caution.

    Notes on internalization and lifecycle
        - PyTopic instances internalize their literal content into a shared global ByteMap.
        - When two PyTopic objects are created from the same literal string key, the underlying buffer
          for that literal is shared (same numeric address in the ByteMap). Topics remain distinct Python
          objects but can share storage.
        - Because of internalization, avoid frequent create/destroy cycles; prefer reusing instances or a
          global TopicSet-style registry.
        - Setting the ``value`` attribute mutates internalized storage and triggers de-register / re-register
          in the internal mapping. This is an expensive operation; prefer lazy-init (create an empty owning
          topic and set ``value`` once).
        - ``__init__`` does not support escape characters; for complex topics that require escaping use
          ``from_parts`` or ``join``.
        - Empty topic parts are not allowed; inputs with empty parts are parsed by ignoring the empties and
          preserving the original literal string.
"""

    owner: int

    def __len__(self) -> int:
        """Return the number of parts in the topic."""

    def __iter__(self) -> Iterator[PyTopicPart]:
        """Iterate over topic parts (yields PyTopicPart subclasses)."""

    def __getitem__(self, idx: int) -> PyTopicPart:
        """Return the topic part at index `idx`.

        Supports negative indexing.

        Raises:
            IndexError: If index is out of range.
        """

    @overload
    def __add__(self, topic: PyTopic) -> PyTopic: ...

    @overload
    def __add__(self, topic: PyTopicPart) -> PyTopic: ...

    def __add__(self, topic: PyTopic | PyTopicPart) -> PyTopic:
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

    @overload
    def __iadd__(self, topic: PyTopic) -> PyTopic: ...

    @overload
    def __iadd__(self, topic: PyTopicPart) -> PyTopic: ...

    def __iadd__(self, topic: PyTopic | PyTopicPart) -> PyTopic:
        """In-place append another PyTopic or PyTopicPart.

        Behavior:
            - Modifies `self` in place and leaves the other operand unchanged.
            - This is equivalent to `self.append(...)` and returns `self`.
        """

    def __eq__(self, other: PyTopic) -> bool:
        """Check equality between this topic and another topic.

        Args:
            other: The other PyTopic to compare against.

        Returns:
            True if both topics have the same literal value.
        """

    def __call__(self, **kwargs) -> PyTopic:
        """ Alias of ``format`` method to format the topic by replacing named wildcards with provided values."""

    @classmethod
    def from_parts(cls, topic_parts: Iterable[PyTopicPart]) -> PyTopic:
        """Build a PyTopic from an iterable of PyTopicPart instances."""

    @classmethod
    def join(cls, topic_parts: Iterable[str]) -> PyTopic:
        """Build a PyTopic from an iterable of literal strings.

        Each string is appended as an exact part.

        Notes:
            - This is a higher-level helper for simple literal-only topics.
            - For complex parts that need escaping or patterns, use `from_parts`.
        """

    def append(self, topic_part: PyTopicPart) -> PyTopic:
        """Append a PyTopicPart to this topic (high-level API).

        Args:
            topic_part: The part to append.

        Returns:
            Self for chaining.

        Raises:
            RuntimeError: If either topic or part is uninitialized.
        """

    def match(self, other: PyTopic) -> PyTopicMatchResult:
        """Match this topic against another topic.

        Args:
            other: The topic to match against.

        Returns:
            A PyTopicMatchResult describing per-part matches.
        """

    def update_literal(self) -> PyTopic:
        """Update the internal literal buffer to reflect the current parts.

        This is useful after in-place modifications of the subordinate TopicParts.
        To avoid inconsistencies, call this method to regenerate the internal literal.

        Notes:
            For TopicPartRange, the reconstructed literal may not be the same as the original.
            e.g.

            >>> t = PyTopic(r'Realtime.(TickData|TradeData)./^[0-9]{6}\.(SZ|SH)$/.+suffix')
            ... print(t)
            Realtime.(TickData|TradeData)./^[0-9]{6}\.(SZ|SH)$/.+suffix
            >>> t.update_literal()
            <PyTopic Generic>(value="Realtime.(TickData|TradeData)./^[0-9]{6}\.(SZ|SH)$/.{suffix}", n_parts=4)
            >>> print(t)
            Realtime.(TickData|TradeData)./^[0-9]{6}\.(SZ|SH)$/.{suffix}

            As show above, there are 2 ways to represent a range part: a ``+suffix`` or ``{suffix}``.
            Recommend using the breakets format, so that the .format is done Intuitively.

        Returns:
            Self for chaining.

        Raises:
            RuntimeError: If the topic is uninitialized.
        """

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

    def format_map(self, mapping: dict[str, str], internalized: bool = True) -> PyTopic:
        """Format the topic by replacing named wildcards with provided values from a mapping.

        Args:
            mapping: Dictionary mapping wildcard names to replacement strings.
            internalized: If True, the returned topic is internalized into the global ByteMap and not owning its underlying buffer.
                          If False, the returned topic owns its internal buffer.

        Returns:
            A new Exact PyTopic with wildcards replaced by the provided values.

        Raises:
            KeyError: If a required wildcard name is missing in mapping.
            ValueError: If having subordinate parts that are not exact or wildcards.
        """

    @property
    def value(self) -> str:
        """str: The full topic literal value.

        Getting returns the current literal. Setting attempts to assign and will raise
        ValueError on syntax errors. Setting mutates the internalized buffer and will
        re-register the topic in the internal mapping.
        """

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

    @property
    def is_exact(self) -> bool:
        """bool: True if the topic consists only of exact parts (no wildcards, ranges, or patterns)."""
