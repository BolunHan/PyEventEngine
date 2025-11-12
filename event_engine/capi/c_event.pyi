from collections.abc import Callable, Iterator
from datetime import datetime
from logging import Logger
from typing import TypedDict, Any

from .c_topic import PyTopic


class PyMessagePayload:
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
        Initialize a ``PyMessagePayload`` instance.

        Args:
            alloc: If ``True``, allocate a new C message payload.
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

    Handlers are triggered with a ``PyMessagePayload``. The dispatcher supports two calling conventions:
    - **With-topic**: the handler receives the topic as a positional or keyword argument.
    - **No-topic**: the handler receives only ``args`` and ``kwargs`` from the payload.

    Handlers that accept ``**kwargs`` are recommended to ensure compatibility with both conventions.

    Attributes:
        topic (PyTopic): The topic associated with this hook.
        logger (Logger | None): Optional logger instance.
        retry_on_unexpected_topic (bool): If ``True``, retries with no-topic calling convention if a with-topic handler raises a ``TypeError`` and the error message indicates an unexpected topic argument.
    """

    topic: PyTopic
    logger: Logger
    retry_on_unexpected_topic: bool

    def __init__(self, topic: PyTopic, logger: Logger = None, retry_on_unexpected_topic: bool = False) -> None:
        """
        Initialize an ``EventHook``.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
            retry_on_unexpected_topic: If ``True``, enables retrying on unexpected topic argument errors.
        """

    def __call__(self, msg: PyMessagePayload) -> None:
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

    def trigger(self, msg: PyMessagePayload) -> None:
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


class Full(Exception):
    """Raised when attempting to publish to a full event queue."""


class Empty(Exception):
    """Raised when attempting to retrieve from an empty event queue."""


class EventEngine:
    """
    High‑performance, topic‑driven event dispatcher backed by a lock–aware C implementation.

    The engine manages an internal message queue and dispatches events to registered handlers
    based on topic matching rules. Internally, it uses the following C components:
      - A pthread-based event loop that consumes messages and triggers callbacks.
      - A custom payload allocator to avoid frequent ``malloc``/``free`` in performance-critical paths.
      - Two ``ByteMap`` instances:
          * One for **exact** topic matches (literal key equality).
          * One for **generic** topic matches (pattern-based, handled by ``PyTopic``).

    These C structures are allocated during initialization and are managed automatically.

    **Matching priority**: exact topic matches take precedence over generic matches.
    Exact matches are based on the topic’s internal literal key (not its string representation).
    Generic matches are evaluated by testing whether the published topic matches a registered pattern.

    Notes:
        Two ``PyTopic`` instances may have identical string representations but different internal structures
        (e.g., different numbers of parts). In such cases, they are considered distinct exact topics.

        Example:

        >>> t1 = PyTopic.join(['Realtime', 'TickData', '600010.SH'])
        >>> t2 = PyTopic.join(['Realtime', 'TickData', '600010', 'SH'])

        Although ``str(t1) == str(t2)``, they have different part counts and thus different literal keys.
        If both were somehow registered (which the Python API prevents), only one hook would be triggered,
        with undefined selection priority.

        Topic construction validity is the user’s responsibility. Use a ``TopicSet`` for robust topic management.

    Attributes:
        capacity (int): Maximum number of messages the internal queue can hold.
        logger (Logger): Logger instance used for diagnostics.
    """

    capacity: int
    logger: Logger

    def __init__(self, capacity: int = ..., logger: Logger = None) -> None:
        """
        Initialize an ``EventEngine``.

        Allocates the following internal C resources:
          - A fixed-capacity message queue.
          - A high-performance payload allocator.
          - Two ``ByteMap`` instances for exact and generic topic routing.

        It is recommended to use singleton instances to minimize resource overhead.

        Args:
            capacity: Maximum number of pending messages.
            logger: Optional logger. If ``None``, a default logger is created.

        Raises:
            MemoryError: If internal C structures fail to allocate.
        """

    def __len__(self) -> int:
        """
        Return the total number of registered topics (both exact and generic).
        """

    def run(self) -> None:
        """
        Run the event loop in the current thread (blocking).
        """

    def start(self) -> None:
        """
        Start the event loop in a dedicated background thread.

        If the engine is already running, this method has no effect.
        """

    def stop(self) -> None:
        """
        Stop the event loop and wait for the background thread to terminate.

        If the engine is already stopped, this method has no effect.
        """

    def clear(self) -> None:
        """
        Unregister all event hooks.

        Notes:
            This method only works when the engine is stopped. If called while running,
            an error is logged and no action is taken.
        """

    def get(self, block: bool = True, max_spin: int = ..., timeout: float = 0.0) -> PyMessagePayload:
        """
        Retrieve an event from the internal queue.

        Args:
            block: If ``True``, wait until an event is available.
            max_spin: Maximum number of spin-loop iterations before blocking (hybrid wait strategy).
            timeout: Maximum wait time in seconds when blocking (``0.0`` means indefinite wait).

        Returns:
            A ``PyMessagePayload`` instance that owns its internal buffer, ``args``, and ``kwargs`` to prevent memory leaks.

        Raises:
            Empty: If ``block=False`` and the queue is empty.
        """

    def put(self, topic: PyTopic, *args, block: bool = True, max_spin: int = ..., timeout: float = 0.0, **kwargs) -> None:
        """
        Publish an event to the queue (convenience alias for ``publish``).

        Args:
            topic: Must be an **exact** ``PyTopic`` (i.e., ``topic.is_exact`` must be ``True``).
            *args: Positional arguments for the event.
            block: If ``True``, wait if the queue is full.
            max_spin: Spin count before blocking (hybrid strategy).
            timeout: Maximum wait time in seconds when blocking (``0.0`` = indefinite).
            **kwargs: Keyword arguments for the event.

        Raises:
            Full: If ``block=False`` and the queue is full.
            ValueError: If ``topic`` is not an exact topic.
        """

    def publish(self, topic: PyTopic, args: tuple, kwargs: dict, block: bool = True, timeout: float = 0.0) -> None:
        """
        Publish an event to the queue.

        Args:
            topic: Must be an **exact** ``PyTopic`` (i.e., ``topic.is_exact`` must be ``True``).
            args: Positional arguments for the event.
            kwargs: Keyword arguments for the event.
            block: If ``True``, wait if the queue is full.
            timeout: Maximum wait time in seconds when blocking (``0.0`` = indefinite).

        Raises:
            Full: If ``block=False`` and the queue is full.
            ValueError: If ``topic`` is not an exact topic.
        """

    def register_hook(self, hook: EventHook) -> None:
        """
        Register an ``EventHook`` for its associated topic.

        Args:
            hook: The hook to register.

        Raises:
            KeyError: If a hook is already registered for the same topic (exact or generic).
        """

    def unregister_hook(self, topic: PyTopic) -> EventHook:
        """
        Unregister and return the ``EventHook`` associated with a topic.

        Args:
            topic: The topic to unregister.

        Returns:
            The unregistered ``EventHook``.

        Raises:
            KeyError: If no hook is registered for the given topic.
        """

    def register_handler(self, topic: PyTopic, py_callable: Callable[..., Any], deduplicate: bool = False) -> None:
        """
        Register a Python callable as a handler for a topic.

        Args:
            topic: The topic to register the handler for (can be exact or generic).
            py_callable: The callable to register.
            deduplicate: If ``True``, skip registration if the handler is already present in the target ``EventHook``.
        """

    def unregister_handler(self, topic: PyTopic, py_callable: Callable[..., Any]) -> None:
        """
        Unregister a handler for a topic.

        Args:
            topic: The topic (exact or generic) to unregister the handler from.
            py_callable: The callable to remove.

        Raises:
            KeyError: If no ``EventHook`` is registered for the given topic.

        Notes:
            - If the ``EventHook`` exists but the handler is not found, no exception is raised.
            - If the handler removal leaves the ``EventHook`` empty, the hook itself is automatically unregistered.
        """

    @property
    def capacity(self) -> int:
        """
        Capacity (maximum number of ``PyMessagePayload`` instances) of the internal message queue.
        """

    def event_hooks(self) -> Iterator[EventHook]:
        """
        Iterate over all registered ``EventHook`` instances.

        Returns:
            An iterator of ``EventHook`` objects.
        """

    def topics(self) -> Iterator[PyTopic]:
        """
        Iterate over all registered topics (both exact and generic).

        Returns:
            An iterator of ``PyTopic`` instances.
        """

    def items(self) -> Iterator[tuple[PyTopic, EventHook]]:
        """
        Iterate over all registered (topic, hook) pairs.

        Returns:
            An iterator of ``(PyTopic, EventHook)`` tuples.
        """


class EventEngineEx(EventEngine):
    """
    Extended ``EventEngine`` with built-in timer support.

    Timer events are published periodically to specified topics, enabling time-driven workflows
    (e.g., heartbeats, scheduled tasks).

    Attributes:
        capacity (int): Capacity of the internal message queue.
        logger (Logger): Logger instance.
    """

    def __init__(self, capacity: int = ..., logger: Logger = None) -> None:
        """
        Initialize an ``EventEngineEx``.

        Args:
            capacity: Maximum number of pending messages.
            logger: Optional logger. If ``None``, a default logger is used.

        Raises:
            MemoryError: If internal C structures fail to allocate.
        """

    def run_timer(self, interval: float, topic: PyTopic, activate_time: datetime | None = None) -> None:
        """
        Run a blocking timer loop that periodically publishes to a topic.

        Args:
            interval: Publication interval in seconds.
            topic: The topic to publish timer events to.
            activate_time: Time at which the timer should start. If ``None``, starts immediately.
        """

    def minute_timer(self, topic: PyTopic) -> None:
        """
        Run a blocking timer that publishes to a topic once per minute (on the minute).

        Args:
            topic: The topic to publish timer events to.
        """

    def second_timer(self, topic: PyTopic) -> None:
        """
        Run a blocking timer that publishes to a topic once per second.

        Args:
            topic: The topic to publish timer events to.
        """

    def get_timer(self, interval: float, activate_time: datetime | None = None) -> PyTopic:
        """
        Start a background timer thread and return its associated topic.

        The engine automatically publishes a message to this topic at each interval.

        Args:
            interval: Timer interval in seconds.
            activate_time: Time to start the timer. If ``None``, starts immediately.

        Returns:
            A unique ``PyTopic`` representing the timer stream.
        """

    def stop(self) -> None:
        """
        Stop the event engine and all associated timer threads.
        """

    def clear(self) -> None:
        """
        Unregister all event hooks and stop all active timer threads.
        """
