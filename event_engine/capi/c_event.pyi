from collections.abc import Callable, Iterator
from logging import Logger
from typing import TypedDict

from .c_topic import PyTopic


class PyMessagePayload:
    """
    Python wrapper for a C message payload structure.

    Attributes:
        owner (bool): Indicates if this instance owns the C payload.
        args_owner (bool): Indicates if this instance owns the args. If so, the args field in its buffer will be cleared on dealloc. Default is False.
        kwargs_owner (bool): Indicates if this instance owns the kwargs. If so the kwargs field in its buffer will be cleared on dealloc. Default is False.
    """

    owner: bool
    args_owner: bool
    kwargs_owner: bool

    def __init__(self, alloc: bool = False) -> None:
        """
        Initialize a PyMessagePayload instance.

        Args:
            alloc: If True, allocate a new C message payload.
        """

    def __repr__(self) -> str:
        """
        Return a string representation of the payload.
        """

    @property
    def topic(self) -> object:
        """
        The topic associated with this payload.
        """

    @property
    def args(self) -> tuple | None:
        """
        The positional arguments of the payload.
        """

    @property
    def kwargs(self) -> dict | None:
        """
        The keyword arguments of the payload.
        """

    @property
    def seq_id(self) -> int:
        """
        The sequence ID of the payload.
        """


class EventHook:
    """
    Event dispatcher for registering and triggering handlers.

    Attributes:
        topic: The topic associated with this hook.
        logger: Optional logger instance.
    """
    topic: PyTopic
    logger: Logger

    def __init__(self, topic: PyTopic, logger: Logger = None) -> None:
        """
        Initialize an EventHook.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
        """

    def __call__(self, msg: PyMessagePayload) -> None:
        """
        Trigger all handlers with the given message payload.
        Alias for ``trigger``.

        Args:
            msg: The message payload to trigger handlers with.
        """

    def __iadd__(self, handler: Callable) -> EventHook:
        """
        Add a handler using the "+=" operator.

        Args:
            handler: The callable to add.
        Returns:
            Self.
        """

    def __isub__(self, handler: Callable) -> EventHook:
        """
        Remove a handler using the "-=" operator.

        Args:
            handler: The callable to remove.
        Returns:
            Self.
        """

    def __len__(self) -> int:
        """
        Return the number of registered handlers.
        """

    def __repr__(self) -> str:
        """
        Return a string representation of the EventHook.
        """

    def __iter__(self) -> Iterator[Callable]:
        """
        Iterate over all registered handlers.
        """

    def __contains__(self, handler: Callable) -> bool:
        """
        Check if a handler is registered.

        Args:
            handler: The callable to check.
        Returns:
            True if registered, False otherwise.
        """

    def trigger(self, msg: PyMessagePayload) -> None:
        """
        Trigger all handlers with the given message payload.

        Handlers are executed in the order they were added: first all no-topic handlers, then all with-topic handlers.
        For with-topic handlers, if a handler raises TypeError (likely due to an unexpected keyword argument),
        the hook will retry the call without the topic argument. This can cause the same handler to be executed twice
        if it accepts both signatures.

        Args:
            msg: The message payload to trigger handlers with.
        """

    def add_handler(self, handler: Callable, deduplicate: bool = False) -> None:
        """
        Add a handler to the hook.

        The recommended handler signature is to include a ``topic`` argument only if needed, and always include a
        ``**kwargs`` guard to ensure compatibility with both with-topic and no-topic calls.

        Args:
            handler: The callable to add.
            deduplicate: If True, do not add if already present.
        """

    def remove_handler(self, handler: Callable) -> EventHook:
        """
        Remove a handler from the hook.

        Only the first matched handler is removed; if the same callable was added multiple times, only the first occurrence is removed.

        Args:
            handler: The callable to remove.
        Returns:
            Self.
        """

    def clear(self) -> None:
        """
        Remove all handlers from the hook.
        """

    @property
    def handlers(self) -> list[Callable]:
        """
        List all registered handlers.
        no_topic handlers are listed before with_topic handlers.
        in the order they were added.
        """


class HandlerStats(TypedDict):
    calls: int
    total_time: float


class EventHookEx(EventHook):
    """
    Extended EventHook with per-handler statistics.
    """

    def __init__(self, topic: object, logger: object = None) -> None:
        """
        Initialize an EventHookEx.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
        """

    def get_stats(self, py_callable: Callable) -> HandlerStats | None:
        """
        Get statistics for a specific handler.

        Args:
            py_callable: The handler to query.
        Returns:
            A dictionary with 'calls' and 'total_time', or None if not found.
        """

    @property
    def stats(self) -> Iterator[tuple[Callable, HandlerStats]]:
        """
        Iterate over (handler, stats) pairs for all handlers.

        Returns:
            A iterator of tuples of (handler, stats_dict) for all handlers.
        """
