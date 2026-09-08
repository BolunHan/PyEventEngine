from collections.abc import Iterator
from datetime import datetime
from logging import Logger
from threading import Thread
from typing import Any

from .c_event import MessagePayload, EventHook
from .c_topic import Topic


class Full(Exception):
    """Raised when attempting to publish to a full event queue."""


class Empty(Exception):
    """Raised when attempting to retrieve from an empty event queue."""


class EventHookMap(dict[str, EventHook]):
    """Synchronized topic -> ``EventHook`` mapping backed by a C bytemap.

    The C bytemap stores the raw ``evt_hook*`` pointer as the value, so the
    C engine's trigger can dispatch entries directly while this dict keeps
    the Python-facing ``EventHook`` object identity. Subclass of
    ``cbase.bytemap.BoundByteMap`` (itself a ``dict`` subclass); the hook
    maps of :class:`EventEngineEx` are instances of this type.
    """


class EventEngineEx:
    """
    Standalone event engine backed by the C ``evt_engine`` structure.

    Unlike ``event_engine.capi.EventEngineEx`` (a Python-side subclass of
    ``EventEngine`` with thread-based timers), this class moves the loop,
    dispatch, sequence counter and timers into C (``c_engine.h`` /
    ``c_engine_gil.h``):

      - The dispatch loop runs in C with the GIL held; the GIL is released
        only around blocking queue waits.
      - Timers are C ``evt_engine_timer_ctx`` tasks polled by the loop; a
        different interval replaces the previous timer task.
      - Hook registries are ``EventHookMap`` instances (``BoundByteMap``
        subclasses) backed by the C bytemaps.

    The loop thread is pinned to the CPU selected by the ``EE_LOOP_CPU``
    compile-time macro (default 0; ``-1`` disables).

    Attributes:
        capacity (int): Maximum number of messages the internal queue can hold.
        logger (Logger): Logger instance used for diagnostics.
        active (bool): Indicates whether the engine is currently running.
        seq_id (int): Monotonically increasing sequence ID for published messages.
        engine (Thread | None): The background loop thread once started.
        timer (dict[float, Topic]): Registered timer intervals mapped to their topics.
    """

    capacity: int
    logger: Logger
    active: bool
    seq_id: int
    engine: Thread | None
    timer: dict[float, Topic]

    def __init__(self, capacity: int = ..., logger: Logger = None) -> None:
        """
        Initialize an ``EventEngineEx``.

        Allocates the C ``evt_engine`` structure, its message queue and the
        two hook-registry bytemaps.

        Args:
            capacity: Maximum number of pending messages.
            logger: Optional logger. If ``None``, a default logger is created.

        Raises:
            MemoryError: If internal C structures fail to allocate.
        """
        ...

    def __len__(self) -> int:
        """
        Return the total number of registered topics (both exact and generic).
        """
        ...

    def __getitem__(self, topic: Topic) -> list[EventHook]:
        """
        Retrieve the list of ``EventHook`` instances that match the given topic.

        Args:
            topic: The topic to look up (exact or generic).

        Returns:
            A list of ``EventHook`` instances registered for the topic.
        """
        ...

    def activate(self) -> None:
        """
        Activate the event engine.

        This method is called automatically when ``start`` is invoked.
        It can also be called manually to prepare the engine for operation.
        """
        ...

    def deactivate(self) -> None:
        """
        Deactivate the event engine.

        This method is called automatically when ``stop`` is invoked.
        It can also be called manually to halt the engine's operation.
        """
        ...

    def run(self) -> None:
        """
        Run the event loop in the current thread (blocking).
        """
        ...

    def start(self) -> None:
        """
        Start the event loop in a dedicated background thread.

        If the engine is already running, this method has no effect.
        """
        ...

    def stop(self) -> None:
        """
        Stop the event loop and wait for the background thread to terminate.

        If the engine is already stopped, this method has no effect.
        """
        ...

    def clear(self) -> None:
        """
        Unregister all event hooks and timer tasks.

        Notes:
            This method only works when the engine is stopped. If called while
            running, an error is logged and no action is taken.
        """
        ...

    def get(self, block: bool = True, max_spin: int = ..., timeout: float = 0.0) -> MessagePayload:
        """
        Retrieve an event from the internal queue.

        Args:
            block: If ``True``, wait until an event is available.
            max_spin: Maximum number of spin-loop iterations before blocking (hybrid wait strategy).
            timeout: Maximum wait time in seconds when blocking (``0.0`` means indefinite wait).

        Returns:
            A ``MessagePayload`` instance that owns its internal buffer, ``args``,
            and ``kwargs`` to prevent memory leaks.

        Raises:
            Empty: If ``block=False`` and the queue is empty.
        """
        ...

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
        ...

    def publish(self, topic: Topic, args: tuple, kwargs: dict, block: bool = True, max_spin: int = ..., timeout: float = 0.0) -> None:
        """
        Publish an event to the queue.

        Args:
            topic: Must be an **exact** ``Topic`` (i.e., ``topic.is_exact`` must be ``True``).
            args: Positional arguments for the event.
            kwargs: Keyword arguments for the event.
            block: If ``True``, wait if the queue is full.
            max_spin: Spin count before blocking (hybrid strategy).
            timeout: Maximum wait time in seconds when blocking (``0.0`` = indefinite).

        Raises:
            Full: If ``block=False`` and the queue is full.
            ValueError: If ``topic`` is not an exact topic.
        """
        ...

    def get_hook(self, topic: Topic) -> EventHook:
        """
        Retrieve the ``EventHook`` associated with a topic.

        Args:
            topic: The topic to look up (exact or generic).

        Returns:
            The ``EventHook`` registered for the topic.

        Raises:
            KeyError: If no hook is registered for the given topic.
        """
        ...

    def register_hook(self, hook: EventHook) -> None:
        """
        Register an ``EventHook`` for its associated topic.

        Args:
            hook: The hook to register.

        Raises:
            KeyError: If a hook is already registered for the same topic (exact or generic).
        """
        ...

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
        ...

    def register_handler(self, topic: Topic, handler: Any, deduplicate: bool = False) -> None:
        """
        Register a Python callable as a handler for a topic.

        Args:
            topic: The topic to register the handler for (can be exact or generic).
            handler: The callable to register.
            deduplicate: If ``True``, skip registration if the handler is already present in the target ``EventHook``.
        """
        ...

    def unregister_handler(self, topic: Topic, handler: Any) -> None:
        """
        Unregister a handler for a topic.

        Args:
            topic: The topic (exact or generic) to unregister the handler from.
            handler: The callable to remove.

        Notes:
            - If the ``EventHook`` exists but the handler is not found, no exception is raised.
            - If the handler removal leaves the ``EventHook`` empty, the hook itself is automatically unregistered.
        """
        ...

    def event_hooks(self) -> Iterator[EventHook]:
        """
        Iterate over all registered ``EventHook`` instances.

        Returns:
            An iterator of ``EventHook`` objects.
        """
        ...

    def topics(self) -> Iterator[Topic]:
        """
        Iterate over all registered topics (both exact and generic).

        Returns:
            An iterator of ``Topic`` instances.
        """
        ...

    def items(self) -> Iterator[tuple[Topic, EventHook]]:
        """
        Iterate over all registered (topic, hook) pairs.

        Returns:
            An iterator of ``(Topic, EventHook)`` tuples.
        """
        ...

    def get_timer(self, interval: float, activate_time: datetime | None = None) -> Topic:
        """
        Register (or reuse) a timer task and return its associated topic.

        The engine publishes to this topic at each interval. A different
        interval replaces the previous timer task.

        Args:
            interval: Timer interval in seconds. Special values: ``1``
                (second-aligned) and ``60`` (minute-aligned) use the dedicated
                timer topics.
            activate_time: Time at which the timer starts. If ``None``,
                starts immediately. Ignored when the interval is already
                registered.

        Returns:
            A unique ``Topic`` representing the timer stream.

        Raises:
            RuntimeError: If engine is not activated.
        """
        ...

    @property
    def capacity(self) -> int:
        """
        Capacity (maximum number of ``MessagePayload`` instances) of the internal message queue.
        """
        ...

    @property
    def occupied(self) -> int:
        """
        Current number of pending messages in the internal queue.
        """
        ...

    @property
    def exact_topic_hooks(self) -> EventHookMap:
        """
        The live exact-topic hook map (``EventHookMap`` bound to the C bytemap).
        """
        ...

    @property
    def generic_topic_hooks(self) -> EventHookMap:
        """
        The live generic-topic hook map (``EventHookMap`` bound to the C bytemap).
        """
        ...

    @property
    def exact_topic_hook_map(self) -> dict[Topic, EventHook]:
        """
        Copy of exact topic to ``EventHook`` mappings.
        """
        ...

    @property
    def generic_topic_hook_map(self) -> dict[Topic, EventHook]:
        """
        Copy of generic topic to ``EventHook`` mappings.
        """
        ...


# Process-wide default engine, backed by the C ``evt_engine`` structure.
# Created idle at import time; downstream Cython modules can cimport its C
# pointer as ``C_EVENT_ENGINE`` (declared in ``c_engine_ex.pxd``).
EVENT_ENGINE: EventEngineEx


class EngineTestToolkit:
    """Relays internal C engine / hook-map / timer state to Python for test validation.

    Note:
        Test-only class. Not declared in any ``.pxd``; not part of the
        public package API.
    """

    @staticmethod
    def get_mq_capacity(engine: EventEngineEx) -> int:
        """Capacity of the engine's C message queue."""
        ...

    @staticmethod
    def get_mq_head(engine: EventEngineEx) -> int:
        """Head index of the engine's C message queue."""
        ...

    @staticmethod
    def get_mq_tail(engine: EventEngineEx) -> int:
        """Tail index of the engine's C message queue."""
        ...

    @staticmethod
    def get_mq_count(engine: EventEngineEx) -> int:
        """Occupancy counter of the engine's C message queue."""
        ...

    @staticmethod
    def get_exact_hook_map_size(engine: EventEngineEx) -> int:
        """Number of entries in the exact-topic hook map."""
        ...

    @staticmethod
    def get_generic_hook_map_size(engine: EventEngineEx) -> int:
        """Number of entries in the generic-topic hook map."""
        ...

    @staticmethod
    def get_exact_hook_map_keys(engine: EventEngineEx) -> list[str]:
        """Keys of all entries in the exact-topic hook map."""
        ...

    @staticmethod
    def get_generic_hook_map_keys(engine: EventEngineEx) -> list[str]:
        """Keys of all entries in the generic-topic hook map."""
        ...

    @staticmethod
    def get_timer_interval(engine: EventEngineEx) -> int:
        """Interval of the head timer ctx, 0 when none."""
        ...

    @staticmethod
    def get_timer_intervals(engine: EventEngineEx) -> list[int]:
        """Intervals of all timer ctxs, in next-due (linked list) order."""
        ...

    @staticmethod
    def get_timer_task_count(engine: EventEngineEx) -> int:
        """Number of registered C timer tasks."""
        ...

    @staticmethod
    def get_timer_payload_topic(engine: EventEngineEx) -> Topic | None:
        """Topic of the first registered C timer task payload, None when none."""
        ...

    @staticmethod
    def register_raw_timer(engine: EventEngineEx, topic: Topic, interval: float) -> MessagePayload | None:
        """Register a timer task directly on the C engine, bypassing get_timer.

        Returns the payload wrapper keeping the task alive, or None when the
        timer topic is rejected (e.g. duplicate topic).
        """
        ...

    @staticmethod
    def bench_mq_put_get(n: int, capacity: int = ...) -> float:
        """Average seconds per put/get round trip on a raw C message queue."""
        ...
