from collections.abc import Callable, Iterator
from logging import Logger
from typing import TypedDict

from .c_topic import Topic


class MessagePayload:
    """
    Python wrapper for a C message payload structure.

    Attributes:
        owner (bool): Indicates whether this instance owns the underlying C payload.
        args_owner (bool): Indicates whether this instance owns the positional arguments.
            If ``True``, the ``args`` field in the internal buffer is cleared upon deallocation.
            Defaults to ``False``.
        kwargs_owner (bool): Indicates whether this instance owns the keyword arguments.
            If ``True``, the ``kwargs`` field in the internal buffer is cleared upon deallocation.
            Defaults to ``False``.
    """

    owner: bool
    args_owner: bool
    kwargs_owner: bool

    def __init__(self, alloc: bool = False) -> None:
        """
        Initialize a ``MessagePayload`` instance.

        Args:
            alloc: If ``True``, allocate a new C message payload.
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


class EventHook:
    """
    Event dispatcher for registering and triggering handlers.

    Handlers are triggered with a ``MessagePayload``. The dispatcher supports two calling conventions:
    - **With-topic**: the handler receives the topic as a positional or keyword argument.
    - **No-topic**: the handler receives only ``args`` and ``kwargs`` from the payload.

    Handlers that accept ``**kwargs`` are recommended to ensure compatibility with both conventions.

    Attributes:
        topic (Topic): The topic associated with this hook.
        logger (Logger | None): Optional logger instance.
        retry_on_unexpected_topic (bool): If ``True``, retries with no-topic calling convention if a with-topic handler raises a ``TypeError`` and the error message indicates an unexpected topic argument.
    """

    topic: Topic
    logger: Logger
    retry_on_unexpected_topic: bool

    def __init__(self, topic: Topic, logger: Logger = None, retry_on_unexpected_topic: bool = False) -> None:
        """
        Initialize an ``EventHook``.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
            retry_on_unexpected_topic: If ``True``, enables retrying on unexpected topic argument errors.
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

        Handlers are executed in registration order:
        1. All **no-topic** handlers (called with ``*args, **kwargs`` only).
        2. All **with-topic** handlers (called with ``topic, *args, **kwargs``).
        In each group, handlers are invoked in the order they were added.

        If ``retry_on_unexpected_topic`` flag is on and a with-topic handler raises a ``TypeError`` and the error message indicates an unexpected topic argument,
        the dispatcher retries the call without the topic.
        This may result in the same handler being invoked twice if the unexpected topic argument is inside the callback.
        e.g.:

        >>> def outer_f(*args, **kwargs):
        ...     print('outer_f called')
        ...     inner_f(topic='abc')
        ...
        ... def inner_f():
        ...     pass

        In this way some code in outer_f may be executed twice. The ``retry_on_unexpected_topic`` can be disabled to avoid this behavior.
        By Default ``retry_on_unexpected_topic`` is ``False``.

        Args:
            msg: The message payload to dispatch.
        """

    def add_handler(self, handler: Callable, deduplicate: bool = False) -> None:
        """
        Register a new handler.

        It is strongly recommended that handlers accept ``**kwargs`` to remain compatible with both
        with-topic and no-topic calling conventions.

        Args:
            handler: The callable to register.
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
    def handlers(self) -> list[Callable]:
        """
        List all registered handlers.

        Handlers are ordered as follows:
        - First, all no-topic handlers (in registration order).
        - Then, all with-topic handlers (in registration order).
        """


class HandlerStats(TypedDict):
    calls: int
    total_time: float


class EventHookEx(EventHook):
    """
    Extended ``EventHook`` that tracks per-handler execution statistics.
    """

    def __init__(self, topic: object, logger: object = None, retry_on_unexpected_topic: bool = False) -> None:
        """
        Initialize an ``EventHookEx``.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
        """

    def get_stats(self, py_callable: Callable) -> HandlerStats | None:
        """
        Retrieve execution statistics for a specific handler.

        Args:
            py_callable: The handler to query.
        Returns:
            A dictionary with keys ``'calls'`` (number of invocations) and ``'total_time'`` (cumulative execution time in seconds),
            or ``None`` if the handler is not registered or the HandlerStats is not registered.
        """

    @property
    def stats(self) -> Iterator[tuple[Callable, HandlerStats]]:
        """
        Iterate over all registered handlers and their execution statistics.

        Returns:
            An iterator yielding ``(handler, stats_dict)`` pairs.
        """
