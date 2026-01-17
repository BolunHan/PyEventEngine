from collections.abc import Callable, Iterator
from logging import Logger
from typing import TypedDict

from .c_topic import Topic


class MessagePayload:
    """
    Python wrapper for a C message payload structure.

    Attributes:
        owner (bool): Indicates whether this instance owns the underlying C payload.
    """

    owner: bool

    def __init__(self, topic: Topic, args: tuple, kwargs: dict) -> None:
        """
        Initialize a ``MessagePayload`` instance.

        Args:
            topic (Topic): Topic for this payload
            args (tuple): Positional arguments for this payload
            kwargs (dict): Keyword arguments for this payload
        """

    def __repr__(self) -> str:
        """
        Return a string representation of the payload.
        """

    @property
    def topic(self) -> Topic:
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


class EvtPyCallable(TypedDict):
    fn: Callable[...]
    logger: Logger
    idx: int
    with_topic: bool


class EventHook:
    """
    Event dispatcher for registering and triggering handlers.

    Handlers are triggered with a ``MessagePayload``. The dispatcher supports two calling conventions:
    - **With-topic**: the handler receives the topic as a positional or keyword argument.
    - **No-topic**: the handler receives only ``args`` and ``kwargs`` from the payload.

    Handlers that accept ``**kwargs`` are recommended to ensure compatibility with both conventions.

    Attributes:
        topic (Topic): The topic associated with this hook.
        logger (Logger | None): Optional logger instance. If not provided, use module global logger.
    """

    topic: Topic
    logger: Logger

    def __init__(self, topic: Topic, logger: Logger = None) -> None:
        """
        Initialize an ``EventHook``.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
        """

    def __call__(self, msg: MessagePayload) -> None:
        """
        Trigger all registered handlers with the given message payload.

        Alias for method ``trigger``.

        Args:
            msg: The message payload to dispatch to handlers.
        """

    def __iadd__(self, handler: Callable) -> EventHook:
        """
        Add a handler using the ``+=`` operator.

        Args:
            handler: The callable to register.
        Returns:
            Self, for chaining.
        """

    def __isub__(self, handler: Callable) -> EventHook:
        """
        Remove a handler using the ``-=`` operator.

        Args:
            handler: The callable to unregister.
        Returns:
            Self, for chaining.
        """

    def __len__(self) -> int:
        """
        Return the number of registered handlers.
        """

    def __repr__(self) -> str:
        """
        Return a string representation of the ``EventHook``.
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
            ``True`` if the handler is registered; ``False`` otherwise.
        """

    def trigger(self, msg: MessagePayload) -> None:
        """
        Trigger all registered handlers with the given message payload.

        Args:
            msg: The message payload to dispatch.
        """

    def add_handler(self, handler: Callable, logger: Logger = None, deduplicate: bool = False) -> None:
        """
        Register a new handler.

        It is strongly recommended that handlers accept ``**kwargs`` to remain compatible with both
        with-topic and no-topic calling conventions.

        Args:
            handler: The callable to register.
            logger: Optional logger instance for this handler. If not provided, use the hook's logger.
            deduplicate: If ``True``, skip registration if the handler is already present.
        """

    def remove_handler(self, handler: Callable) -> EventHook:
        """
        Remove a handler from the hook.

        Only the first matching occurrence is removed. If the same callable was added multiple times,
        subsequent instances remain registered.

        Args:
            handler: The callable to remove.

        Returns:
            Self, for chaining.
        """

    def clear(self) -> None:
        """
        Remove all registered handlers.
        """

    @property
    def handlers(self) -> list[EvtPyCallable]:
        """
        List all registered handlers.

        Returns:
            A list of dictionaries, each containing information about a registered handler.
        """


class HandlerStats(TypedDict):
    n_calls: int
    last_call_start: float
    last_call_complete: float
    elapsed_seconds: float


class EventHookEx(EventHook):
    """
    Extended ``EventHook`` that tracks per-handler execution statistics.
    """

    def __init__(self, topic: object, logger: object = None) -> None:
        """
        Initialize an ``EventHookEx``.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
        """

    @property
    def stats(self) -> HandlerStats:
        """
        Get aggregate statistics for this EventHook

        Returns:
            A dictionary with total calls and total execution time.
        """
        ...
