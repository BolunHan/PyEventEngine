"""
Native Python fallback implementation for EventEngine and EventEngineEx.

This module provides a pure Python implementation that mimics the behavior of the 
Cython-based c_engine module. It is used as a fallback when the Cython extension 
cannot be compiled (e.g., due to lack of Cython, GCC, or Clang).

The API is designed to match event_engine.capi.c_engine as closely as possible.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timedelta
from logging import Logger
from threading import Thread
from time import sleep, time
from typing import Optional

from .event import EventHook, EventHookEx, PyMessagePayload
from .topic import PyTopic

# Get logger from base module
try:
    from ..base import LOGGER
except ImportError:
    import logging

    LOGGER = logging.getLogger(__name__)

LOGGER = LOGGER.getChild('Event')

# Default constants (matching c_engine defaults)
DEFAULT_MQ_CAPACITY = 0x0fff  # 4095
DEFAULT_MQ_SPIN_LIMIT = 0xffff  # 65535
DEFAULT_MQ_TIMEOUT_SECONDS = 1.0


class Full(Exception):
    """Raised when attempting to publish to a full event queue."""
    pass


class Empty(Exception):
    """Raised when attempting to retrieve from an empty event queue."""
    pass


class EventEngine:
    """
    High-performance, topic-driven event dispatcher backed by threading primitives.

    The engine manages an internal message queue and dispatches events to registered handlers
    based on topic matching rules. In this native Python implementation:
      - A threading-based event loop consumes messages and triggers callbacks
      - Message queue uses deque with threading.Lock and Condition variables
      - Two dict instances for exact and generic topic routing

    **Matching priority**: exact topic matches take precedence over generic matches.
    Exact matches are based on the topic's literal key.
    Generic matches are evaluated by testing whether the published topic matches a registered pattern.

    Attributes:
        capacity (int): Maximum number of messages the internal queue can hold.
        logger (Logger): Logger instance used for diagnostics.
    """

    __slots__ = ('logger', '_capacity', '_queue', '_lock', '_not_empty', '_not_full', '_exact_topic_hooks', '_generic_topic_hooks', '_seq_id', 'active', 'engine')

    def __init__(self, capacity: int = DEFAULT_MQ_CAPACITY, logger: Optional[Logger] = None) -> None:
        """
        Initialize an ``EventEngine``.

        Args:
            capacity: Maximum number of pending messages.
            logger: Optional logger. If ``None``, a default logger is created.
        """
        self.logger: Logger = LOGGER.getChild('EventEngine') if logger is None else logger

        # Message queue using deque with threading primitives
        self._capacity: int = capacity
        self._queue: deque[PyMessagePayload] = deque()
        self._lock: threading.Lock = threading.Lock()
        self._not_empty: threading.Condition = threading.Condition(self._lock)
        self._not_full: threading.Condition = threading.Condition(self._lock)

        # Topic-to-hook mappings using dict (key: topic.value string)
        self._exact_topic_hooks: dict[str, EventHook] = {}
        self._generic_topic_hooks: dict[str, EventHook] = {}

        # Sequence ID counter
        self._seq_id: int = 0

        # Engine state
        self.active: bool = False
        self.engine: Optional[Thread] = None

    def __len__(self) -> int:
        """Return the total number of registered topics (both exact and generic)."""
        return len(self._exact_topic_hooks) + len(self._generic_topic_hooks)

    def __repr__(self) -> str:
        """String representation of the engine."""
        status = "active" if self.active else "idle"
        return f'<{self.__class__.__name__} {status}>(capacity={self.capacity})'

    def _loop(self) -> None:
        """Main event loop - consumes and processes messages."""
        while self.active:
            msg = self._get_message(block=True, timeout=DEFAULT_MQ_TIMEOUT_SECONDS)
            if msg is not None:
                self._trigger(msg)

    def _get_message(self, block: bool = True, timeout: float = 0.0) -> Optional[PyMessagePayload]:
        """
        Get a message from the queue.

        Args:
            block: Whether to block if queue is empty
            timeout: Timeout in seconds (0 means no timeout)

        Returns:
            PyMessagePayload or None if timeout/non-blocking and queue is empty
        """
        with self._not_empty:
            if not block:
                if len(self._queue) == 0:
                    return None
                msg = self._queue.popleft()
                self._not_full.notify()
                return msg

            # Blocking mode
            if timeout > 0:
                end_time = time() + timeout
                while len(self._queue) == 0 and self.active:
                    remaining = end_time - time()
                    if remaining <= 0:
                        return None
                    self._not_empty.wait(timeout=remaining)
            else:
                # No timeout - wait indefinitely
                while len(self._queue) == 0 and self.active:
                    self._not_empty.wait(timeout=DEFAULT_MQ_TIMEOUT_SECONDS)

            if len(self._queue) == 0:
                return None

            msg = self._queue.popleft()
            self._not_full.notify()
            return msg

    def _publish(self, topic: PyTopic, args: tuple, kwargs: dict, block: bool = True, max_spin: int = DEFAULT_MQ_SPIN_LIMIT, timeout: float = 0.0) -> int:
        """
        Publish a message to the queue.

        Args:
            topic: Topic for the message
            args: Positional arguments
            kwargs: Keyword arguments
            block: Whether to block if queue is full
            max_spin: Spin limit (ignored in pure Python implementation)
            timeout: Timeout in seconds

        Returns:
            0 on success, non-zero on failure
        """
        if not topic.is_exact:
            raise ValueError('Topic must be all of exact parts')

        # Create payload
        payload = PyMessagePayload(alloc=True)
        payload.topic = topic
        payload.args = args
        payload.kwargs = kwargs
        payload.seq_id = self._seq_id

        with self._not_full:
            if not block:
                if len(self._queue) >= self._capacity:
                    return 1  # Queue full
                self._queue.append(payload)
                self._seq_id += 1
                self._not_empty.notify()
                return 0

            # Blocking mode
            if timeout > 0:
                end_time = time() + timeout
                while len(self._queue) >= self._capacity:
                    remaining = end_time - time()
                    if remaining <= 0:
                        return 1  # Timeout
                    self._not_full.wait(timeout=remaining)
            else:
                # No timeout - wait indefinitely
                while len(self._queue) >= self._capacity:
                    self._not_full.wait(timeout=DEFAULT_MQ_TIMEOUT_SECONDS)

            if len(self._queue) >= self._capacity:
                return 1  # Failed

            self._queue.append(payload)
            self._seq_id += 1
            self._not_empty.notify()
            return 0

    def _trigger(self, msg: PyMessagePayload) -> None:
        """
        Trigger event hooks matching the message topic.

        Args:
            msg: Message payload to dispatch
        """
        msg_topic = msg.topic

        # Step 1: Match exact topic hooks
        hook = self._exact_topic_hooks.get(msg_topic.value)
        if hook:
            hook.trigger(msg)

        # Step 2: Match generic topic hooks (wildcards, patterns, etc.)
        for hook in self._generic_topic_hooks.values():
            # Use topic matching from PyTopic
            if hook.topic.match(msg_topic).matched:
                hook.trigger(msg)

    def _register_hook(self, hook: EventHook) -> None:
        """
        Register an event hook.

        Args:
            hook: EventHook to register

        Raises:
            KeyError: If a hook is already registered for the same topic
        """
        topic = hook.topic
        topic_str = topic.value

        if topic.is_exact:
            if topic_str in self._exact_topic_hooks:
                raise KeyError(f'Another EventHook already registered for {topic_str}')
            self._exact_topic_hooks[topic_str] = hook
        else:
            if topic_str in self._generic_topic_hooks:
                raise KeyError(f'Another EventHook already registered for {topic_str}')
            self._generic_topic_hooks[topic_str] = hook

    def _unregister_hook(self, topic: PyTopic) -> EventHook:
        """
        Unregister an event hook by topic.

        Args:
            topic: Topic of the hook to unregister

        Returns:
            The unregistered EventHook

        Raises:
            KeyError: If no hook is registered for the given topic
        """
        topic_str = topic.value

        if topic.is_exact:
            if topic_str not in self._exact_topic_hooks:
                raise KeyError(f'No EventHook registered for {topic_str}')
            return self._exact_topic_hooks.pop(topic_str)
        else:
            if topic_str not in self._generic_topic_hooks:
                raise KeyError(f'No EventHook registered for {topic_str}')
            return self._generic_topic_hooks.pop(topic_str)

    def _register_handler(self, topic: PyTopic, handler, deduplicate: bool = False) -> None:
        """
        Register a handler for a topic (creates hook if needed).

        Args:
            topic: Topic to register handler for
            handler: Callable handler
            deduplicate: Whether to skip if handler already registered
        """
        topic_str = topic.value

        if topic.is_exact:
            hook_map = self._exact_topic_hooks
        else:
            hook_map = self._generic_topic_hooks

        if topic_str not in hook_map:
            hook = EventHook(topic, self.logger)
            hook_map[topic_str] = hook
        else:
            hook = hook_map[topic_str]

        hook.add_handler(handler, deduplicate=deduplicate)

    def _unregister_handler(self, topic: PyTopic, handler) -> None:
        """
        Unregister a handler from a topic.

        Args:
            topic: Topic to unregister handler from
            handler: Callable handler to remove

        Raises:
            KeyError: If no hook is registered for the given topic
        """
        topic_str = topic.value

        if topic.is_exact:
            hook_map = self._exact_topic_hooks
        else:
            hook_map = self._generic_topic_hooks

        if topic_str not in hook_map:
            raise KeyError(f'No EventHook registered for {topic_str}')

        hook = hook_map[topic_str]
        hook.remove_handler(handler)

        # Remove hook if no handlers left
        if len(hook) == 0:
            del hook_map[topic_str]

    def _clear(self) -> None:
        """Clear all hooks and handlers."""
        # Clear all hooks
        for hook in self._exact_topic_hooks.values():
            hook.clear()
        self._exact_topic_hooks.clear()

        for hook in self._generic_topic_hooks.values():
            hook.clear()
        self._generic_topic_hooks.clear()

    # --- Public API ---

    def activate(self) -> None:
        """
        Activate the event engine.

        This method is called automatically when ``start`` is invoked.
        It can also be called manually to prepare the engine for operation.
        """
        self.active = True

    def deactivate(self) -> None:
        """
        Deactivate the event engine.

        This method is called automatically when ``stop`` is invoked.
        It can also be called manually to halt the engine's operation.
        """
        self.active = False

    def run(self) -> None:
        """
        Run the event loop in the current thread (blocking).
        """
        self._loop()

    def start(self) -> None:
        """
        Start the event loop in a dedicated background thread.

        If the engine is already running, this method has no effect.
        """
        if self.active:
            self.logger.warning(f'{self} already started!')
            return

        self.active = True
        self.engine = Thread(target=self.run, name='EventEngine')
        self.engine.start()
        self.logger.info(f'{self} started.')

    def stop(self) -> None:
        """
        Stop the event loop and wait for the background thread to terminate.

        If the engine is already stopped, this method has no effect.
        """
        if not self.active:
            self.logger.warning('EventEngine already stopped!')
            return

        self.active = False

        # Wake up the event loop if it's waiting
        with self._not_empty:
            self._not_empty.notify_all()

        if self.engine:
            self.engine.join()
            self.engine = None

    def clear(self) -> None:
        """
        Unregister all event hooks.

        Notes:
            This method only works when the engine is stopped. If called while running,
            an error is logged and no action is taken.
        """
        if self.active:
            self.logger.error('EventEngine must be stopped before cleared!')
            return

        self._clear()

    def get(self, block: bool = True, max_spin: int = DEFAULT_MQ_SPIN_LIMIT, timeout: float = 0.0) -> PyMessagePayload:
        """
        Retrieve an event from the internal queue.

        Args:
            block: If ``True``, wait until an event is available.
            max_spin: Maximum number of spin-loop iterations before blocking (ignored in pure Python).
            timeout: Maximum wait time in seconds when blocking (``0.0`` means indefinite wait).

        Returns:
            A ``PyMessagePayload`` instance.

        Raises:
            Empty: If ``block=False`` and the queue is empty.
        """
        msg = self._get_message(block=block, timeout=timeout)
        if msg is None:
            raise Empty()
        return msg

    def put(self, topic: PyTopic, *args, block: bool = True, max_spin: int = DEFAULT_MQ_SPIN_LIMIT, timeout: float = 0.0, **kwargs) -> None:
        """
        Publish an event to the queue (convenience alias for ``publish``).

        Args:
            topic: Must be an **exact** ``PyTopic`` (i.e., ``topic.is_exact`` must be ``True``).
            *args: Positional arguments for the event.
            block: If ``True``, wait if the queue is full.
            max_spin: Spin count before blocking (ignored in pure Python).
            timeout: Maximum wait time in seconds when blocking (``0.0`` = indefinite).
            **kwargs: Keyword arguments for the event.

        Raises:
            Full: If ``block=False`` and the queue is full.
            ValueError: If ``topic`` is not an exact topic.
        """
        ret_code = self._publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code:
            raise Full()

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
        ret_code = self._publish(topic, args, kwargs, block, DEFAULT_MQ_SPIN_LIMIT, timeout)
        if ret_code:
            raise Full()

    def register_hook(self, hook: EventHook) -> None:
        """
        Register an ``EventHook`` for its associated topic.

        Args:
            hook: The hook to register.

        Raises:
            KeyError: If a hook is already registered for the same topic (exact or generic).
        """
        self._register_hook(hook)

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
        return self._unregister_hook(topic)

    def register_handler(self, topic: PyTopic, handler, deduplicate: bool = False) -> None:
        """
        Register a handler for a topic (creates hook if needed).

        Args:
            topic: Topic to register handler for
            handler: Callable handler
            deduplicate: Skip if handler already registered
        """
        self._register_handler(topic, handler, deduplicate)

    def unregister_handler(self, topic: PyTopic, handler) -> None:
        """
        Unregister a handler from a topic.

        Args:
            topic: Topic to unregister handler from
            handler: Callable handler to remove
        """
        self._unregister_handler(topic, handler)

    def event_hooks(self):
        """Iterate over all registered event hooks."""
        yield from self._exact_topic_hooks.values()
        yield from self._generic_topic_hooks.values()

    def topics(self):
        """Iterate over all registered topics."""
        for hook in self.event_hooks():
            yield hook.topic

    def items(self):
        """Iterate over (topic, hook) pairs."""
        for hook in self.event_hooks():
            yield (hook.topic, hook)

    @property
    def capacity(self) -> int:
        """Get the queue capacity."""
        return self._capacity

    @property
    def occupied(self) -> int:
        """Get the current number of messages in the queue."""
        with self._lock:
            return len(self._queue)

    @property
    def exact_topic_hook_map(self) -> dict:
        """Get a copy of the exact topic hook mapping."""
        return self._exact_topic_hooks.copy()

    @property
    def generic_topic_hook_map(self) -> dict:
        """Get a copy of the generic topic hook mapping."""
        return self._generic_topic_hooks.copy()


class EventEngineEx(EventEngine):
    """
    Extended EventEngine with timer support and statistics tracking.

    Provides timer functionality for periodic event triggering and uses EventHookEx
    for handler statistics.
    """

    __slots__ = ('timer',)

    def __init__(self, capacity: int = DEFAULT_MQ_CAPACITY, logger: Optional[Logger] = None) -> None:
        """
        Initialize EventEngineEx.

        Args:
            capacity: Maximum capacity of the message queue
            logger: Optional logger instance
        """
        super().__init__(capacity, logger)
        self.timer: dict[float, Thread] = {}

    def __repr__(self) -> str:
        """String representation including active timers."""
        status = "active" if self.active else "idle"
        timer_intervals = list(self.timer.keys())
        return f'<{self.__class__.__name__} {status}>(capacity={self.capacity}, timers={timer_intervals})'

    def _timer_loop(self, interval: float, topic: PyTopic, activate_time: Optional[datetime]) -> None:
        """
        Timer loop for custom intervals.

        Args:
            interval: Interval in seconds
            topic: Topic to publish on
            activate_time: Optional activation time
        """
        if activate_time is None:
            scheduled_time = datetime.now()
        else:
            scheduled_time = activate_time

        kwargs = {'interval': interval, 'trigger_time': scheduled_time}

        while self.active:
            sleep_time = (scheduled_time - datetime.now()).total_seconds()

            if sleep_time > 0:
                sleep(sleep_time)

            self._publish(topic, (), kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

            while scheduled_time < datetime.now():
                scheduled_time += timedelta(seconds=interval)
            kwargs['trigger_time'] = scheduled_time

    def _minute_timer_loop(self, topic: PyTopic) -> None:
        """
        Minute-aligned timer loop.

        Args:
            topic: Topic to publish on
        """
        kwargs = {'interval': 60}

        while self.active:
            t = time()
            scheduled_time = t // 60 * 60
            next_time = scheduled_time + 60
            sleep_time = next_time - t
            sleep(sleep_time)
            kwargs['timestamp'] = scheduled_time
            self._publish(topic, (), kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

    def _second_timer_loop(self, topic: PyTopic) -> None:
        """
        Second-aligned timer loop.

        Args:
            topic: Topic to publish on
        """
        kwargs = {'interval': 1}

        while self.active:
            t = time()
            scheduled_time = t // 1
            next_time = scheduled_time + 1
            sleep_time = next_time - t
            sleep(sleep_time)
            kwargs['timestamp'] = scheduled_time
            self._publish(topic, (), kwargs, True, DEFAULT_MQ_SPIN_LIMIT, 0.0)

    def run_timer(self, interval: float, topic: PyTopic, activate_time: Optional[datetime] = None) -> None:
        """
        Run a timer with custom interval (blocking call).

        Args:
            interval: Interval in seconds
            topic: Topic to publish on
            activate_time: Optional activation time

        Raises:
            RuntimeError: If the engine is not active
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self._timer_loop(interval, topic, activate_time)

    def minute_timer(self, topic: PyTopic) -> None:
        """
        Run minute-aligned timer (blocking call).

        Args:
            topic: Topic to publish on

        Raises:
            RuntimeError: If the engine is not active
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self._minute_timer_loop(topic)

    def second_timer(self, topic: PyTopic) -> None:
        """
        Run second-aligned timer (blocking call).

        Args:
            topic: Topic to publish on

        Raises:
            RuntimeError: If the engine is not active
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self._second_timer_loop(topic)

    def get_timer(self, interval: float, activate_time: Optional[datetime] = None) -> PyTopic:
        """
        Get or create a timer with the specified interval.

        Args:
            interval: Interval in seconds
            activate_time: Optional activation time

        Returns:
            PyTopic for the timer

        Raises:
            RuntimeError: If the engine is not active
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')

        if interval == 1:
            topic = PyTopic('EventEngine.Internal.Timer.Second')
            timer = Thread(target=self.second_timer, kwargs={'topic': topic})
        elif interval == 60:
            topic = PyTopic('EventEngine.Internal.Timer.Minute')
            timer = Thread(target=self.minute_timer, kwargs={'topic': topic})
        else:
            topic = PyTopic.join(['EventEngine', 'Internal', 'Timer', str(interval)])
            timer = Thread(target=self.run_timer,
                           kwargs={'interval': interval, 'topic': topic, 'activate_time': activate_time})

        if interval not in self.timer:
            self.timer[interval] = timer
            timer.start()
        else:
            if activate_time is not None:
                self.logger.debug(
                    f'Timer thread with interval [{timedelta(seconds=interval)}] already initialized! '
                    f'Argument [activate_time] takes no effect!'
                )

        return topic

    def stop(self) -> None:
        """Stop the engine and all timers."""
        super().stop()

        for timer in self.timer.values():
            timer.join()

    def clear(self) -> None:
        """Clear all hooks and timers."""
        super().clear()

        for t in self.timer.values():
            t.join(timeout=0)
        self.timer.clear()
