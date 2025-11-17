"""
Native Python fallback implementation for PyMessagePayload and EventHook classes.

This module provides a pure Python implementation that mimics the behavior of the 
Cython-based c_event module. It is used as a fallback when the Cython extension 
cannot be compiled (e.g., due to lack of Cython, GCC, or Clang).

The API is designed to match event_engine.capi.c_event as closely as possible.
"""

from __future__ import annotations

import inspect
import time
import traceback
from collections.abc import Callable, Iterator
from logging import Logger
from typing import TypedDict

from .topic import PyTopic

# Get logger from base module
try:
    from ..base import LOGGER
except ImportError:
    import logging

    LOGGER = logging.getLogger(__name__)

LOGGER = LOGGER.getChild('Event')

# Internal constants
_TOPIC_FIELD_NAME = 'topic'
_TOPIC_UNEXPECTED_ERROR = f"an unexpected keyword argument '{_TOPIC_FIELD_NAME}'"


class PyMessagePayload:
    """
    Python wrapper for a message payload structure.

    In native Python, all instances own their underlying data (owner, args_owner, kwargs_owner are always True).
    """

    __slots__ = ('_topic', '_args', '_kwargs', '_seq_id')

    def __init__(self, alloc: bool = False) -> None:
        """
        Initialize a ``PyMessagePayload`` instance.

        Args:
            alloc: If ``True``, allocate a new message payload (always True in Python).
        """
        self._topic: PyTopic | None = None
        self._args: tuple | None = None
        self._kwargs: dict | None = None
        self._seq_id: int = 0

    def __repr__(self) -> str:
        """
        Return a string representation of the payload.
        """
        if self._topic:
            return f'<PyMessagePayload "{self.topic.value}">(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'
        return f'<PyMessagePayload NO_TOPIC>(seq_id={self.seq_id}, args={self.args}, kwargs={self.kwargs})'

    @property
    def owner(self) -> bool:
        """bool: Whether this instance owns the underlying payload (always True in native Python)."""
        return True

    @property
    def args_owner(self) -> bool:
        """bool: Whether this instance owns the positional arguments (always True in native Python)."""
        return True

    @property
    def kwargs_owner(self) -> bool:
        """bool: Whether this instance owns the keyword arguments (always True in native Python)."""
        return True

    @property
    def topic(self) -> PyTopic | None:
        """
        The topic associated with this payload.
        """
        return self._topic

    @topic.setter
    def topic(self, value: PyTopic) -> None:
        """Set the topic."""
        self._topic = value

    @property
    def args(self) -> tuple | None:
        """
        The positional arguments of the payload.
        """
        return self._args

    @args.setter
    def args(self, value: tuple) -> None:
        """Set the positional arguments."""
        self._args = value

    @property
    def kwargs(self) -> dict | None:
        """
        The keyword arguments of the payload.
        """
        return self._kwargs

    @kwargs.setter
    def kwargs(self, value: dict) -> None:
        """Set the keyword arguments."""
        self._kwargs = value

    @property
    def seq_id(self) -> int:
        """
        The sequence ID of the payload.
        """
        return self._seq_id

    @seq_id.setter
    def seq_id(self, value: int) -> None:
        """Set the sequence ID."""
        self._seq_id = value


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

    __slots__ = ('topic', 'logger', 'retry_on_unexpected_topic', '_handlers_no_topic', '_handlers_with_topic')

    def __init__(self, topic: PyTopic, logger: Logger = None, retry_on_unexpected_topic: bool = False) -> None:
        """
        Initialize an ``EventHook``.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
            retry_on_unexpected_topic: If ``True``, enables retrying on unexpected topic argument errors.
        """
        self.topic: PyTopic = topic
        self.logger: Logger = LOGGER.getChild(f'EventHook.{topic}') if logger is None else logger
        self.retry_on_unexpected_topic: bool = retry_on_unexpected_topic
        self._handlers_no_topic: list[Callable] = []
        self._handlers_with_topic: list[Callable] = []

    def __call__(self, msg: PyMessagePayload) -> None:
        """
        Trigger all registered handlers with the given message payload.

        Alias for method ``trigger``.

        Args:
            msg: The message payload to dispatch to handlers.
        """
        self.trigger(msg)

    def __iadd__(self, handler: Callable) -> EventHook:
        """
        Add a handler using the ``+=`` operator.

        Args:
            handler: The callable to register.
        Returns:
            Self, for chaining.
        """
        self.add_handler(handler)
        return self

    def __isub__(self, handler: Callable) -> EventHook:
        """
        Remove a handler using the ``-=`` operator.

        Args:
            handler: The callable to unregister.
        Returns:
            Self, for chaining.
        """
        self.remove_handler(handler)
        return self

    def __len__(self) -> int:
        """
        Return the number of registered handlers.
        """
        return len(self._handlers_no_topic) + len(self._handlers_with_topic)

    def __repr__(self) -> str:
        """
        Return a string representation of the ``EventHook``.
        """
        return f'<EventHook topic="{self.topic}" handlers={len(self)}>'

    def __iter__(self) -> Iterator[Callable]:
        """
        Iterate over all registered handlers.
        """
        yield from self._handlers_no_topic
        yield from self._handlers_with_topic

    def __contains__(self, handler: Callable) -> bool:
        """
        Check if a handler is registered.

        Args:
            handler: The callable to check.
        Returns:
            ``True`` if the handler is registered; ``False`` otherwise.
        """
        return handler in self._handlers_no_topic or handler in self._handlers_with_topic

    def trigger(self, msg: PyMessagePayload) -> None:
        """
        Trigger all registered handlers with the given message payload.

        Handlers are executed in registration order:
        1. All **no-topic** handlers (called with ``*args, **kwargs`` only).
        2. All **with-topic** handlers (called with ``topic, *args, **kwargs``).
        In each group, handlers are invoked in the order they were added.

        If ``retry_on_unexpected_topic`` flag is on and a with-topic handler raises a ``TypeError`` and the error message indicates an unexpected topic argument,
        the dispatcher retries the call without the topic.

        Args:
            msg: The message payload to dispatch.
        """
        args = msg.args if msg.args is not None else ()
        kwargs = msg.kwargs if msg.kwargs is not None else {}
        topic = msg.topic

        # Trigger no-topic handlers first
        for handler in self._handlers_no_topic:
            try:
                handler(*args, **kwargs)
            except Exception:
                self.logger.error(traceback.format_exc())

        # Trigger with-topic handlers
        # Create a new kwargs dict with topic added
        kwargs_with_topic = kwargs.copy()
        kwargs_with_topic[_TOPIC_FIELD_NAME] = topic

        for handler in self._handlers_with_topic:
            try:
                handler(*args, **kwargs_with_topic)
            except TypeError as e:
                # Check if this is an "unexpected keyword argument 'topic'" error
                if self.retry_on_unexpected_topic and _TOPIC_UNEXPECTED_ERROR in str(e):
                    try:
                        handler(*args, **kwargs)
                    except Exception:
                        self.logger.error(traceback.format_exc())
                else:
                    self.logger.error(traceback.format_exc())
            except Exception:
                self.logger.error(traceback.format_exc())

    def add_handler(self, handler: Callable, deduplicate: bool = False) -> None:
        """
        Register a new handler.

        It is strongly recommended that handlers accept ``**kwargs`` to remain compatible with both
        with-topic and no-topic calling conventions.

        Args:
            handler: The callable to register.
            deduplicate: If ``True``, skip registration if the handler is already present.
        """
        if not callable(handler):
            raise TypeError(f'Handler must be callable, got {type(handler)}')

        # Check if handler is already registered
        if deduplicate and handler in self:
            return

        # Inspect the handler signature to determine if it accepts 'topic'
        with_topic = False
        try:
            sig = inspect.signature(handler)
            for param in sig.parameters.values():
                if param.name == _TOPIC_FIELD_NAME or param.kind == param.VAR_KEYWORD:
                    with_topic = True
                    break
        except (ValueError, TypeError):
            # Can't inspect signature, assume no topic
            pass

        if with_topic:
            self._handlers_with_topic.append(handler)
        else:
            self._handlers_no_topic.append(handler)

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
        try:
            self._handlers_no_topic.remove(handler)
        except ValueError:
            try:
                self._handlers_with_topic.remove(handler)
            except ValueError:
                pass  # Handler not found, silently ignore
        return self

    def clear(self) -> None:
        """
        Remove all registered handlers.
        """
        self._handlers_no_topic.clear()
        self._handlers_with_topic.clear()

    @property
    def handlers(self) -> list[Callable]:
        """
        List all registered handlers.

        Handlers are ordered as follows:
        - First, all no-topic handlers (in registration order).
        - Then, all with-topic handlers (in registration order).
        """
        return self._handlers_no_topic + self._handlers_with_topic


class HandlerStats(TypedDict):
    """Statistics for a handler."""
    calls: int
    total_time: float


class EventHookEx(EventHook):
    """
    Extended ``EventHook`` that tracks per-handler execution statistics.
    """

    __slots__ = ('_stats',)

    def __init__(self, topic: PyTopic, logger: Logger = None, retry_on_unexpected_topic: bool = False) -> None:
        """
        Initialize an ``EventHookEx``.

        Args:
            topic: The topic associated with this hook.
            logger: Optional logger instance.
            retry_on_unexpected_topic: If ``True``, enables retrying on unexpected topic argument errors.
        """
        super().__init__(topic, logger, retry_on_unexpected_topic)
        self._stats: dict[int, HandlerStats] = {}

    def trigger(self, msg: PyMessagePayload) -> None:
        """
        Trigger all registered handlers with the given message payload, tracking execution time.

        Args:
            msg: The message payload to dispatch.
        """
        args = msg.args if msg.args is not None else ()
        kwargs = msg.kwargs if msg.kwargs is not None else {}
        topic = msg.topic

        # Trigger no-topic handlers first
        for handler in self._handlers_no_topic:
            handler_id = id(handler)
            if handler_id not in self._stats:
                self._stats[handler_id] = {'calls': 0, 'total_time': 0.0}

            start_time = time.perf_counter()
            try:
                handler(*args, **kwargs)
            except Exception:
                self.logger.error(traceback.format_exc())
            finally:
                elapsed = time.perf_counter() - start_time
                self._stats[handler_id]['calls'] += 1
                self._stats[handler_id]['total_time'] += elapsed

        # Trigger with-topic handlers
        # Create a new kwargs dict with topic added
        kwargs_with_topic = kwargs.copy()
        kwargs_with_topic[_TOPIC_FIELD_NAME] = topic

        for handler in self._handlers_with_topic:
            handler_id = id(handler)
            if handler_id not in self._stats:
                self._stats[handler_id] = {'calls': 0, 'total_time': 0.0}

            start_time = time.perf_counter()
            try:
                handler(*args, **kwargs_with_topic)
            except TypeError as e:
                # Check if this is an "unexpected keyword argument 'topic'" error
                if self.retry_on_unexpected_topic and _TOPIC_UNEXPECTED_ERROR in str(e):
                    try:
                        handler(*args, **kwargs)
                    except Exception:
                        self.logger.error(traceback.format_exc())
                else:
                    self.logger.error(traceback.format_exc())
            except Exception:
                self.logger.error(traceback.format_exc())
            finally:
                elapsed = time.perf_counter() - start_time
                self._stats[handler_id]['calls'] += 1
                self._stats[handler_id]['total_time'] += elapsed

    def get_stats(self, py_callable: Callable) -> HandlerStats | None:
        """
        Retrieve execution statistics for a specific handler.

        Args:
            py_callable: The handler to query.
        Returns:
            A dictionary with keys ``'calls'`` (number of invocations) and ``'total_time'`` (cumulative execution time in seconds),
            or ``None`` if the handler is not registered or the HandlerStats is not registered.
        """
        handler_id = id(py_callable)
        return self._stats.get(handler_id)

    @property
    def stats(self) -> Iterator[tuple[Callable, HandlerStats]]:
        """
        Iterate over all registered handlers and their execution statistics.

        Returns:
            An iterator yielding ``(handler, stats_dict)`` pairs.
        """
        for handler in self._handlers_no_topic:
            handler_id = id(handler)
            if handler_id in self._stats:
                yield handler, self._stats[handler_id]

        for handler in self._handlers_with_topic:
            handler_id = id(handler)
            if handler_id in self._stats:
                yield handler, self._stats[handler_id]

    def clear(self) -> None:
        """
        Remove all registered handlers and clear statistics.
        """
        super().clear()
        self._stats.clear()
