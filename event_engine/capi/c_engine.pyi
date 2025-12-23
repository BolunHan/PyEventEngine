from collections.abc import Callable, Iterator
from datetime import datetime
from logging import Logger
from typing import Any

from .c_bytemap import ByteMap
from .c_event import MessagePayload, EventHook
from .c_topic import Topic


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
          * One for **generic** topic matches (pattern-based, handled by ``Topic``).

    These C structures are allocated during initialization and are managed automatically.

    **Matching priority**: exact topic matches take precedence over generic matches.
    Exact matches are based on the topic’s internal literal key (not its string representation).
    Generic matches are evaluated by testing whether the published topic matches a registered pattern.

    Notes:
        Two ``Topic`` instances may have identical string representations but different internal structures
        (e.g., different numbers of parts). In such cases, they are considered distinct exact topics.

        Example:

        >>> t1 = Topic.join(['Realtime', 'TickData', '600010.SH'])
        >>> t2 = Topic.join(['Realtime', 'TickData', '600010', 'SH'])

        Although ``str(t1) == str(t2)``, they have different part counts and thus different literal keys.
        If both were somehow registered (which the Python API prevents), only one hook would be triggered,
        with undefined selection priority.

        Topic construction validity is the user’s responsibility. Use a ``TopicSet`` for robust topic management.

    Attributes:
        capacity (int): Maximum number of messages the internal queue can hold.
        logger (Logger): Logger instance used for diagnostics.
        active (bool): Indicates whether the engine is currently running.
        seq_id (int): Monotonically increasing sequence ID for published messages.
    """

    capacity: int
    logger: Logger
    active: bool
    seq_id: int

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

    def activate(self):
        """
        Activate the event engine.

        This method is called automatically when ``start`` is invoked.
        It can also be called manually to prepare the engine for operation.
        """

    def deactivate(self) -> None:
        """
        Deactivate the event engine.

        This method is called automatically when ``stop`` is invoked.
        It can also be called manually to halt the engine's operation.
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

    def get(self, block: bool = True, max_spin: int = ..., timeout: float = 0.0) -> MessagePayload:
        """
        Retrieve an event from the internal queue.

        Args:
            block: If ``True``, wait until an event is available.
            max_spin: Maximum number of spin-loop iterations before blocking (hybrid wait strategy).
            timeout: Maximum wait time in seconds when blocking (``0.0`` means indefinite wait).

        Returns:
            A ``MessagePayload`` instance that owns its internal buffer, ``args``, and ``kwargs`` to prevent memory leaks.

        Raises:
            Empty: If ``block=False`` and the queue is empty.
        """

    def put(self, topic: Topic, *args, block: bool = True, max_spin: int = ..., timeout: float = 0.0, **kwargs) -> None:
        """
        Publish an event to the queue (convenience alias for ``publish``).

        Args:
            topic: Must be an **exact** ``Topic`` (i.e., ``topic.is_exact`` must be ``True``).
            *args: Positional arguments for the event.
            block: If ``True``, wait if the queue is full.
            max_spin: Spin count before blocking (hybrid strategy).
            timeout: Maximum wait time in seconds when blocking (``0.0`` = indefinite).
            **kwargs: Keyword arguments for the event.

        Raises:
            Full: If ``block=False`` and the queue is full.
            ValueError: If ``topic`` is not an exact topic.
        """

    def publish(self, topic: Topic, args: tuple, kwargs: dict, block: bool = True, timeout: float = 0.0) -> None:
        """
        Publish an event to the queue.

        Args:
            topic: Must be an **exact** ``Topic`` (i.e., ``topic.is_exact`` must be ``True``).
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

    def unregister_hook(self, topic: Topic) -> EventHook:
        """
        Unregister and return the ``EventHook`` associated with a topic.

        Args:
            topic: The topic to unregister.

        Returns:
            The unregistered ``EventHook``.

        Raises:
            KeyError: If no hook is registered for the given topic.
        """

    def register_handler(self, topic: Topic, handler: Callable[..., Any], deduplicate: bool = False) -> None:
        """
        Register a Python callable as a handler for a topic.

        Args:
            topic: The topic to register the handler for (can be exact or generic).
            handler: The callable to register.
            deduplicate: If ``True``, skip registration if the handler is already present in the target ``EventHook``.
        """

    def unregister_handler(self, topic: Topic, handler: Callable[..., Any]) -> None:
        """
        Unregister a handler for a topic.

        Args:
            topic: The topic (exact or generic) to unregister the handler from.
            handler: The callable to remove.

        Raises:
            KeyError: If no ``EventHook`` is registered for the given topic.

        Notes:
            - If the ``EventHook`` exists but the handler is not found, no exception is raised.
            - If the handler removal leaves the ``EventHook`` empty, the hook itself is automatically unregistered.
        """

    def event_hooks(self) -> Iterator[EventHook]:
        """
        Iterate over all registered ``EventHook`` instances.

        Returns:
            An iterator of ``EventHook`` objects.
        """

    def topics(self) -> Iterator[Topic]:
        """
        Iterate over all registered topics (both exact and generic).

        Returns:
            An iterator of ``Topic`` instances.
        """

    def items(self) -> Iterator[tuple[Topic, EventHook]]:
        """
        Iterate over all registered (topic, hook) pairs.

        Returns:
            An iterator of ``(Topic, EventHook)`` tuples.
        """

    @property
    def capacity(self) -> int:
        """
        Capacity (maximum number of ``MessagePayload`` instances) of the internal message queue.
        """

    @property
    def occupied(self) -> int:
        """
        Current number of pending messages in the internal queue.
        """

    @property
    def exact_topic_hook_map(self) -> ByteMap:
        """
        ByteMap of exact topic to ``EventHook`` mappings.
        """

    @property
    def generic_topic_hook_map(self) -> ByteMap:
        """
        ByteMap of generic topic to ``EventHook`` mappings.
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

    def run_timer(self, interval: float, topic: Topic, activate_time: datetime | None = None) -> None:
        """
        Run a blocking timer loop that periodically publishes to a topic.

        Args:
            interval: Publication interval in seconds.
            topic: The topic to publish timer events to.
            activate_time: Time at which the timer should start. If ``None``, starts immediately.

        Raises:
            RuntimeError: If engine is not activated.
        """

    def minute_timer(self, topic: Topic) -> None:
        """
        Run a blocking timer that publishes to a topic once per minute (on the minute).

        Args:
            topic: The topic to publish timer events to.

        Raises:
            RuntimeError: If engine is not activated.
        """

    def second_timer(self, topic: Topic) -> None:
        """
        Run a blocking timer that publishes to a topic once per second.

        Args:
            topic: The topic to publish timer events to.

        Raises:
            RuntimeError: If engine is not activated.
        """

    def get_timer(self, interval: float, activate_time: datetime | None = None) -> Topic:
        """
        Start a background timer thread and return its associated topic.

        The engine automatically publishes a message to this topic at each interval.
        Will not start multiple timers with the same interval.

        Args:
            interval: Timer interval in seconds.
            activate_time: Time to start the timer. If ``None``, starts immediately.

        Returns:
            A unique ``Topic`` representing the timer stream.

        Raises:
            RuntimeError: If engine is not activated.
        """

    def stop(self) -> None:
        """
        Stop the event engine and all associated timer threads.
        """

    def clear(self) -> None:
        """
        Unregister all event hooks and stop all active timer threads.
        """
