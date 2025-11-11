from typing import Any


class Allocator:
    """
    Manage a raw memory buffer and allocate/recycle regions inside it.

    This stub matches the public surface of the Cython implementation in
    `c_allocator.pyx`. Only the runtime-visible methods/properties are declared.

    Attributes:
        buffer: underlying Python buffer/shm object (if any).
        addr: numeric address/id of the underlying allocator structure.
        address_map: mapping from uintptr addresses to Python instances registered with the allocator.
    """

    buffer: object
    addr: int
    address_map: dict[int, Any]

    def __init__(self, buffer: Any = None, capacity: int = 0) -> None:
        """
        Initialize Allocator.

        Args:
            buffer: optional Python object supporting the buffer protocol (bytearray, RawArray, etc).
                    If omitted the allocator will create an internal extendable allocator.
            capacity: maximum usable bytes of the provided buffer (0 means use full buffer).
        """

    def __len__(self) -> int:
        """Return total capacity (in bytes) managed by this allocator."""

    @classmethod
    def get_buffer(cls, size: int) -> Allocator:
        """Create an Allocator backed by a `bytearray` of `size` bytes."""

    @classmethod
    def get_shm(cls, size: int) -> Allocator:
        """Create an Allocator backed by a multiprocessing shared memory RawArray of `size` bytes."""

    def request(self, size: int) -> memoryview:
        """
        Request a contiguous block of memory of `size` bytes from the allocator.

        Returns:
            A memoryview of length `size` pointing at the allocated memory.
        Raises:
            MemoryError if allocation fails.
        """

    def recycle(self, buffer: memoryview) -> None:
        """
        Return previously allocated memory (provided as a memoryview) back to the allocator.
        """

    def clear(self) -> None:
        """Clear internal state (registered address map)."""

    @property
    def capacity(self) -> int:
        """Total capacity (bytes) of the allocator."""

    @property
    def available_bytes(self) -> int:
        """Number of free bytes currently available for allocation."""

    @property
    def occupied(self) -> int:
        """Number of bytes currently occupied (capacity - available_bytes)."""

    @property
    def occupied_ratio(self) -> float:
        """Fraction (0.0..1.0) of capacity that is occupied."""

    @property
    def free_ratio(self) -> float:
        """Fraction (0.0..1.0) of capacity that is free."""
