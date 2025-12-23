"""
Pure Python fallback implementation of EventEngine for cross-platform compatibility.

This module provides Python-native implementations of EventEngine and EventEngineEx
that work on Windows and other platforms without requiring Cython/C extensions.

Uses:
- threading.Lock, threading.Condition for synchronization
- dict for topic-to-hook mappings (instead of ByteMap)
- Topic, MessagePayload, EventHook from c_topic and c_event modules
"""

import threading
from collections import deque
from datetime import datetime, timedelta
from logging import Logger
from threading import Thread
from time import sleep, time
from typing import Optional

from .c_event import EventHook, EventHookEx, MessagePayload
from .c_topic import Topic
from ..base import LOGGER

LOGGER = LOGGER.getChild('Event')

# Default constants (matching c_engine defaults)
DEFAULT_MQ_CAPACITY = 0x0fff
DEFAULT_MQ_SPIN_LIMIT = 0xffff
DEFAULT_MQ_TIMEOUT_SECONDS = 1.0


class Full(Exception):
    """Exception raised when the message queue is full."""
    pass


class Empty(Exception):
    """Exception raised when the message queue is empty."""
    pass


class EventEngine:
    """
    Pure Python implementation of EventEngine.

    Uses dict-based topic-to-hook mappings and threading primitives for synchronization.
    Compatible with Windows and all platforms supporting the threading module.
    """

    def __init__(self, capacity: int = DEFAULT_MQ_CAPACITY, logger: Optional[Logger] = None):
        """
        Initialize EventEngine.

        Args:
            capacity: Maximum capacity of the message queue
            logger: Optional logger instance
        """
        self.logger = LOGGER.getChild('EventEngine') if logger is None else logger

        # Message queue using deque with threading primitives
        self._capacity = capacity
        self._queue = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._not_full = threading.Condition(self._lock)

        # Topic-to-hook mappings using dict (key: topic.value string)
        self._exact_topic_hooks: dict[str, EventHook] = {}
        self._generic_topic_hooks: dict[str, EventHook] = {}

        # Sequence ID counter
        self._seq_id = 0

        # Engine state
        self.active = False
        self.engine: Optional[Thread] = None

    def __len__(self) -> int:
        """Return the total number of registered hooks."""
        return len(self._exact_topic_hooks) + len(self._generic_topic_hooks)

    def __repr__(self) -> str:
        """String representation of the engine."""
        return f'<{self.__class__.__name__} {"active" if self.active else "idle"}>(capacity={self.capacity})'

    def _loop(self):
        """Main event loop - consumes and processes messages."""
        while self.active:
            msg = self._get_message(block=True, timeout=DEFAULT_MQ_TIMEOUT_SECONDS)
            if msg is not None:
                self._trigger(msg)

    def _get_message(self, block: bool = True, timeout: float = 0.0) -> Optional[MessagePayload]:
        """
        Get a message from the queue.

        Args:
            block: Whether to block if queue is empty
            timeout: Timeout in seconds (0 means no timeout)

        Returns:
            MessagePayload or None if timeout/non-blocking and queue is empty
        """
        with self._not_empty:
            if not block:
                if len(self._queue) == 0:
                    return None
                return self._queue.popleft()

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

    def _publish(self, topic: Topic, args: tuple, kwargs: dict, block: bool = True, max_spin: int = DEFAULT_MQ_SPIN_LIMIT, timeout: float = 0.0) -> int:
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
        payload = MessagePayload(alloc=True)
        payload.topic = topic
        payload.args = args
        payload.kwargs = kwargs
        payload.seq_id = self._seq_id

        # Note: args_owner and kwargs_owner must be False when publishing
        payload.args_owner = False
        payload.kwargs_owner = False

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

    def _trigger(self, msg: MessagePayload):
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
        for hook_topic_str, hook in self._generic_topic_hooks.items():
            # Use topic matching from Topic
            if hook.topic.match(msg_topic).matched:
                hook.trigger(msg)

    def _register_hook(self, hook: EventHook):
        """
        Register an event hook.

        Args:
            hook: EventHook to register
        """
        topic = hook.topic
        topic_str = topic.value

        if topic.is_exact:
            if topic_str in self._exact_topic_hooks and self._exact_topic_hooks[topic_str] is not hook:
                raise KeyError(f'Another EventHook already registered for {topic_str}')
            self._exact_topic_hooks[topic_str] = hook
        else:
            if topic_str in self._generic_topic_hooks and self._generic_topic_hooks[topic_str] is not hook:
                raise KeyError(f'Another EventHook already registered for {topic_str}')
            self._generic_topic_hooks[topic_str] = hook

    def _unregister_hook(self, topic: Topic) -> EventHook:
        """
        Unregister an event hook by topic.

        Args:
            topic: Topic of the hook to unregister

        Returns:
            The unregistered EventHook
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

    def _register_handler(self, topic: Topic, handler, deduplicate: bool = False):
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

    def _unregister_handler(self, topic: Topic, handler):
        """
        Unregister a handler from a topic.

        Args:
            topic: Topic to unregister handler from
            handler: Callable handler to remove
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

    def _clear(self):
        """Clear all hooks and handlers."""
        # Clear all hooks
        for hook in self._exact_topic_hooks.values():
            hook.clear()
        self._exact_topic_hooks.clear()

        for hook in self._generic_topic_hooks.values():
            hook.clear()
        self._generic_topic_hooks.clear()

    # --- Public API ---

    def activate(self):
        """Activate the engine (sets active flag to True)."""
        self.active = True

    def deactivate(self):
        """Deactivate the engine (sets active flag to False)."""
        self.active = False

    def run(self):
        """Run the event loop (blocking call)."""
        self._loop()

    def start(self):
        """Start the engine in a background thread."""
        if self.active:
            self.logger.warning(f'{self} already started!')
            return
        self.active = True
        self.engine = Thread(target=self.run, name='EventEngine')
        self.engine.start()
        self.logger.info(f'{self} started.')

    def stop(self):
        """Stop the engine and wait for the background thread to finish."""
        if not self.active:
            self.logger.warning('EventEngine already stopped!')
            return

        self.active = False

        # Wake up the event loop if it's waiting
        with self._not_empty:
            self._not_empty.notify_all()

        if self.engine:
            self.engine.join()

    def clear(self):
        """Clear all hooks and handlers (engine must be stopped first)."""
        if self.active:
            self.logger.error('EventEngine must be stopped before cleared!')
            return

        self._clear()

    def get(self, block: bool = True, max_spin: int = DEFAULT_MQ_SPIN_LIMIT, timeout: float = 0.0) -> MessagePayload:
        """
        Get a message from the queue.

        Args:
            block: Whether to block if queue is empty
            max_spin: Spin limit (ignored in pure Python)
            timeout: Timeout in seconds

        Returns:
            MessagePayload

        Raises:
            Empty: If no message available
        """
        msg = self._get_message(block=block, timeout=timeout)
        if msg is None:
            raise Empty()

        # When getting, payload must have args_owner = kwargs_owner = True
        msg.args_owner = True
        msg.kwargs_owner = True
        return msg

    def put(self, topic: Topic, *args, block: bool = True, max_spin: int = DEFAULT_MQ_SPIN_LIMIT, timeout: float = 0.0, **kwargs):
        """
        Put a message into the queue.

        Args:
            topic: Topic for the message
            *args: Positional arguments
            block: Whether to block if queue is full
            max_spin: Spin limit (ignored)
            timeout: Timeout in seconds
            **kwargs: Keyword arguments

        Raises:
            Full: If queue is full
        """
        ret_code = self._publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code:
            raise Full()

    def publish(self, topic: Topic, args: tuple, kwargs: dict, block: bool = True, max_spin: int = DEFAULT_MQ_SPIN_LIMIT, timeout: float = 0.0):
        """
        Publish a message to the queue.

        Args:
            topic: Topic for the message
            args: Positional arguments tuple
            kwargs: Keyword arguments dict
            block: Whether to block if queue is full
            max_spin: Spin limit (ignored)
            timeout: Timeout in seconds

        Raises:
            Full: If queue is full
        """
        ret_code = self._publish(topic, args, kwargs, block, max_spin, timeout)
        if ret_code:
            raise Full()

    def register_hook(self, hook: EventHook):
        """
        Register an event hook.

        Args:
            hook: EventHook instance to register
        """
        self._register_hook(hook)

    def unregister_hook(self, topic: Topic) -> EventHook:
        """
        Unregister a hook by topic.

        Args:
            topic: Topic of the hook to unregister

        Returns:
            The unregistered EventHook
        """
        return self._unregister_hook(topic)

    def register_handler(self, topic: Topic, handler, deduplicate: bool = False):
        """
        Register a handler for a topic.

        Args:
            topic: Topic to register handler for
            handler: Callable handler
            deduplicate: Skip if handler already registered
        """
        self._register_handler(topic, handler, deduplicate)

    def unregister_handler(self, topic: Topic, handler):
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
        """Get the exact topic hook mapping."""
        return self._exact_topic_hooks.copy()

    @property
    def generic_topic_hook_map(self) -> dict:
        """Get the generic topic hook mapping."""
        return self._generic_topic_hooks.copy()


class EventEngineEx(EventEngine):
    """
    Extended EventEngine with timer support.

    Provides timer functionality for periodic event triggering.
    """

    def __init__(self, capacity: int = DEFAULT_MQ_CAPACITY, logger: Optional[Logger] = None):
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
        return (f'<{self.__class__.__name__} {"active" if self.active else "idle"}>'
                f'(capacity={self.capacity}, timers={list(self.timer.keys())})')

    def _timer_loop(self, interval: float, topic: Topic, activate_time: Optional[datetime]):
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

    def _minute_timer_loop(self, topic: Topic):
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

    def _second_timer_loop(self, topic: Topic):
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

    def run_timer(self, interval: float, topic: Topic, activate_time: Optional[datetime] = None):
        """
        Run a timer with custom interval (blocking call).

        Args:
            interval: Interval in seconds
            topic: Topic to publish on
            activate_time: Optional activation time
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self._timer_loop(interval, topic, activate_time)

    def minute_timer(self, topic: Topic):
        """
        Run minute-aligned timer (blocking call).

        Args:
            topic: Topic to publish on
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self._minute_timer_loop(topic)

    def second_timer(self, topic: Topic):
        """
        Run second-aligned timer (blocking call).

        Args:
            topic: Topic to publish on
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')
        self._second_timer_loop(topic)

    def get_timer(self, interval: float, activate_time: Optional[datetime] = None) -> Topic:
        """
        Get or create a timer with the specified interval.

        Args:
            interval: Interval in seconds
            activate_time: Optional activation time

        Returns:
            Topic for the timer
        """
        if not self.active:
            raise RuntimeError('EventEngine must be started before getting timer!')

        if interval == 1:
            topic = Topic('EventEngine.Internal.Timer.Second')
            timer = Thread(target=self.second_timer, kwargs={'topic': topic})
        elif interval == 60:
            topic = Topic('EventEngine.Internal.Timer.Minute')
            timer = Thread(target=self.minute_timer, kwargs={'topic': topic})
        else:
            topic = Topic.join(['EventEngine', 'Internal', 'Timer', str(interval)])
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

    def stop(self):
        """Stop the engine and all timers."""
        super().stop()

        for timer in self.timer.values():
            timer.join()

    def clear(self):
        """Clear all hooks and timers."""
        super().clear()

        for t in self.timer.values():
            t.join(timeout=0)
        self.timer.clear()
