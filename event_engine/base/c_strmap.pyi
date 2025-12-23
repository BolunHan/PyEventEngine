from __future__ import annotations

from ctypes import c_size_t, c_uint64
from dataclasses import dataclass
from typing import Union, Any, Iterator, Annotated


@dataclass
class ValueRange:
    lo: int
    hi: int


KEY_T = Union[str, bytes]
SIZE_MAX = c_size_t(-1).value
SIZE_UINT64 = c_uint64(-1).value
size_t = Annotated[int, ValueRange(0, SIZE_MAX), c_size_t]
uint64_t = Annotated[int, ValueRange(0, SIZE_UINT64), c_uint64]


class StrMap:
    """A high-performance, memory-safe hash map for byte strings.

    This class wraps a C-level hash table (``strmap``) that supports
    O(1) average-case insertion, lookup, and deletion. It uses salted XXH3
    hashing for DoS resistance and supports custom memory allocators.

    The map maintains insertion order and tracks both logical size (live entries)
    and occupied slots (including tombstones) for rehashing decisions.

    Note that this class is not designed to outperformance python builtin dict,
    but provide a python interface wrapper of the underlying c / cython module.

    Attributes:
        capacity (int): Current number of slots in the hash table.
        salt (int): Per-instance 64-bit hash salt for security.
        total_size (int): Number of live (non-deleted) entries.
        occupied (int): Number of slots that are either live or tombstone.
    """
    capacity: size_t
    salt: uint64_t
    total_size: size_t
    occupied: size_t

    def __init__(self, init_capacity: int = ..., no_init: bool = ...) -> None:
        """Initialize a new StrMap.

        Args:
            init_capacity: Initial hash table capacity (default: 64).
            no_init: If True, skip internal allocation (used internally).
        """

    def __len__(self) -> int:
        """Return the number of occupied slots (live + tombstones)."""

    def __contains__(self, key: KEY_T) -> bool:
        """Check if a key exists in the map."""

    def __getitem__(self, key: KEY_T) -> Any:
        """Retrieve a value by key.

        Args:
            key: The key to look up (str or bytes).

        Returns:
            The associated value.

        Raises:
            KeyError: If the key is not found.
        """

    def __setitem__(self, key: KEY_T, value: Any) -> None:
        """Insert or update a key-value pair.

        Args:
            key: The key (str or bytes).
            value: The value to store (must be a Python object).
        """

    def __repr__(self) -> str:
        """Return a string representation of the StrMap."""

    def get(self, key: KEY_T, default=None) -> Any:
        """Retrieve a value, returning a default if not found.

        Args:
            key: The key to look up.
            default: Value to return if key is missing.

        Returns:
            The associated value or `default`.
        """

    def get_addr(self, key: KEY_T) -> int:
        """Get the raw pointer value as an integer.

        Args:
            key: The key to look up.

        Returns:
            The stored `void*` cast to `int`.

        Raises:
            KeyError: If the key is not found.
        """

    def set(self, key: KEY_T, value: Any) -> None:
        """Insert or update a key-value pair (alias for `__setitem__`)."""

    def set_addr(self, key: KEY_T, value: int) -> None:
        """Insert a raw pointer value.

        Args:
            key: The key to associate.
            value: Integer representing a `void*`.
        """

    def pop(self, key: KEY_T, default: Any = ...) -> Any:
        """Remove and return a value.

        Args:
            key: The key to remove.
            default: Value to return if key is missing.

        Returns:
            The removed value or `default`.

        Raises:
            KeyError: If key is missing and no default is provided.
        """

    def contains(self, key: KEY_T) -> bool:
        """Check for key existence (alias for `__contains__`)."""

    def clear(self) -> None:
        """Remove all entries from the map."""

    def bytes_keys(self) -> Iterator[bytes]:
        """Iterate over keys as `bytes` in insertion order."""

    def str_keys(self) -> Iterator[str]:
        """Iterate over keys as `str` (UTF-8 decoded) in insertion order."""

    def values(self) -> Iterator[int]:
        """Iterate over raw pointer values (`uintptr_t`) in insertion order."""

    @property
    def capacity(self) -> int:
        """Current hash table capacity (number of slots)."""

    @capacity.setter
    def capacity(self, value: int) -> None:
        """Resize the hash table to the given capacity."""

    @property
    def salt(self) -> int:
        """64-bit per-instance hash salt used for DoS resistance."""

    @salt.setter
    def salt(self, value: int) -> None:
        """Set a new salt (affects future hashing only)."""

    @property
    def total_size(self) -> int:
        """Number of live (non-deleted) entries."""

    @property
    def occupied(self) -> int:
        """Number of slots that are occupied (live or tombstone)."""
