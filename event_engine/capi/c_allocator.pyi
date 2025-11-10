from typing import Any, overload

from .c_bytemap import ByteMap
from .c_retick import OrderQueue, OrderMap, OrderBook, ReTick


class Allocator:
    """Manages a memory buffer and allocates space for objects within it.

    Tracks allocated objects by their memory address.

    The Allocator is designed to use a shared memory. So that ReTick module can easily be shared with processes.

    Attributes:
        buffer: The buffer object assigned to this allocator.
        addr: The address of the buffer assigned to this allocator.
        overhead: The size of the memory overhead for each allocated object.
        offset_map: All the instances init from this allocator. The memory address offset (to the allocator buffer) as keys and python instance as values.
        address_map: All the instances init from this allocator. The actual memory address as keys and python instance as values.
    """
    buffer: object
    addr: int
    overhead: int
    address_map: dict[int, Any]

    def __init__(self, buffer: Any, capacity: int = 0) -> None:
        """Initialize the Allocator with a buffer and its capacity.

        Note that the provided buffer will be zeroed on init. But only limited within the capacity if provided.
        The allocator will only use the size of the buffer within the capacity too.
        If a capacity is provided greater than the length of the buffer, it will be trimmed to prevent overflow.

        Args:
            buffer: A Python object supporting the buffer protocol.
            capacity: The max size of the buffer can be used, in bytes. If not provided, capacity will be inferred from buffer.
        """

    def __len__(self) -> int:
        """Get the total capacity of the allocator's buffer.

        Returns:
            The size of the buffer in bytes.
        """

    @classmethod
    def get_buffer(cls, size: int) -> Allocator:
        """Get the allocator backed by bytearray for the given size."""
        ...

    @classmethod
    def get_shm(cls, size: int) -> Allocator:
        """Get the allocator backed by SHM for the given size."""
        ...

    @overload
    def init_from_buffer(self, constructor: type[ByteMap], price: float, init_capacity: int = ...) -> ByteMap: ...

    @overload
    def init_from_buffer(self, constructor: type[OrderQueue], price: float, init_capacity: int = ...) -> OrderQueue: ...

    @overload
    def init_from_buffer(self, constructor: type[OrderMap], init_capacity: int = ...) -> OrderMap: ...

    @overload
    def init_from_buffer(self, constructor: type[OrderBook], side: int, price: float, tick_size: float = ..., n_alloc_slots: int = ..., init_orderbook_capacity: int = ..., init_orderqueue_capacity: int = ..., init_ordermap_capacity: int = ...) -> OrderBook: ...

    @overload
    def init_from_buffer(self, constructor: type[ReTick], base_price: float, tick_size: float = ..., n_alloc_slots: int = ..., init_orderbook_capacity: int = ..., init_orderqueue_capacity: int = ..., init_ordermap_capacity: int = ...) -> ReTick: ...

    def init_from_buffer(self, constructor: Any, *args: Any, **kwargs: Any) -> Any: ...

    def available_bytes(self) -> int:
        """Get the number of bytes currently available in the buffer.

        Returns:
            The number of free bytes.
        """

    @property
    def capacity(self) -> int:
        """int: The total capacity of the allocator's buffer."""

    @property
    def occupied(self) -> int:
        """int: The number of bytes currently occupied in the buffer."""

    @property
    def occupied_ratio(self) -> float: ...

    @property
    def free_ratio(self) -> float: ...
