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

    def __init__(self, topic: PyTopic = None, args: tuple = None, kwargs: dict = None, alloc: bool = False) -> None:
        """
        Initialize a ``PyMessagePayload`` instance.

        Mirrors the Cython ``MessagePayload`` constructor: ``topic``, ``args``
        and ``kwargs`` may be supplied directly. When omitted (e.g. the engine
        allocating an empty payload), the fields are left ``None`` and can be
        assigned afterwards via the setters.

        Args:
            topic: Topic to associate with the payload (may be omitted).
            args: Positional arguments for the payload (may be omitted).
            kwargs: Keyword arguments for the payload (may be omitted).
            alloc: If ``True``, allocate a new message payload (always True in Python).
        """
        self._topic: PyTopic | None = topic
        self._args: tuple | None = args
        self._kwargs: dict | None = kwargs
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
    def kwargs_with_topic(self) -> dict | None:
        """
        A copy of the payload kwargs with the ``topic`` key injected
        (mirrors the Cython ``MessagePayload.kwargs_with_topic``).
        """
        if self._kwargs is None:
            return None
        aggregated = dict(self._kwargs)
        aggregated[_TOPIC_FIELD_NAME] = self._topic
        return aggregated

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

    __slots__ = ('topic', 'logger', 'retry_on_unexpected_topic', '_handlers', '_handler_loggers')

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
        self._handlers: list[tuple[Callable, bool]] = []  # (callable, with_topic)
        self._handler_loggers: dict[int, Logger] = {}

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
        Add a handler using the ``+=`` operator (deduplicated, mirroring the
        Cython ``EventHook.__iadd__``).

        Args:
            handler: The callable to register.
        Returns:
            Self, for chaining.
        """
        self.add_handler(handler, deduplicate=True)
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
        """Return the number of registered handlers."""
        return len(self._handlers)

    def __repr__(self) -> str:
        """Return a string representation of the ``EventHook``."""
        return f'<EventHook topic="{self.topic}" handlers={len(self)}>'

    def __iter__(self) -> Iterator[dict]:
        """Iterate over handler descriptor dicts (mirroring the Cython ``EventHook``)."""
        return iter(self.handlers)

    def __contains__(self, handler: Callable) -> bool:
        """Check if a handler is registered (by function identity or bound-method equivalence)."""
        for fn, _ in self._handlers:
            if fn is handler:
                return True
            if inspect.ismethod(handler) and inspect.ismethod(fn):
                if handler.__self__ is fn.__self__ and handler.__func__ is fn.__func__:
                    return True
        return False

    def trigger(self, msg: PyMessagePayload) -> None:
        """Trigger all registered handlers in registration order."""
        args = msg.args if msg.args is not None else ()
        kwargs = msg.kwargs if msg.kwargs is not None else {}
        topic = msg.topic
        kwargs_with_topic = kwargs.copy()
        kwargs_with_topic[_TOPIC_FIELD_NAME] = topic

        for handler, with_topic in self._handlers:
            try:
                if with_topic:
                    handler(*args, **kwargs_with_topic)
                else:
                    handler(*args, **kwargs)
            except TypeError as e:
                if self.retry_on_unexpected_topic and with_topic and _TOPIC_UNEXPECTED_ERROR in str(e):
                    try:
                        handler(*args, **kwargs)
                    except Exception:
                        self.logger.error(traceback.format_exc())
                else:
                    self.logger.error(traceback.format_exc())
            except Exception:
                self.logger.error(traceback.format_exc())

    def add_handler(self, py_callable: Callable, logger: Logger = None, deduplicate: bool = False) -> None:
        """
        Register a new handler.

        It is strongly recommended that handlers accept ``**kwargs`` to remain compatible with both
        with-topic and no-topic calling conventions.

        Signature mirrors the Cython ``EventHook.add_handler``: the optional
        ``logger`` is recorded per callable and surfaced through ``handlers``.

        Args:
            py_callable: The callable to register.
            logger: Optional per-handler logger (defaults to the hook logger).
            deduplicate: If ``True``, skip registration if the handler is already present.
        """
        if not callable(py_callable):
            raise TypeError(f'Handler must be callable, got {type(py_callable)}')

        # Check if handler is already registered
        if deduplicate and py_callable in self:
            return

        # Inspect the handler signature to determine if it accepts 'topic'
        with_topic = False
        try:
            sig = inspect.signature(py_callable)
            for param in sig.parameters.values():
                if param.name == _TOPIC_FIELD_NAME or param.kind == param.VAR_KEYWORD:
                    with_topic = True
                    break
        except (ValueError, TypeError):
            # Can't inspect signature, assume no topic
            pass

        self._handler_loggers[id(py_callable)] = self.logger if logger is None else logger
        self._handlers.append((py_callable, with_topic))

    def remove_handler(self, py_callable: Callable) -> EventHook:
        """
        Remove a handler from the hook.

        Only the first matching occurrence is removed. Mirrors the Cython
        ``EventHook.remove_handler``: removing an unknown callable logs a warning.
        """
        for i, (fn, _) in enumerate(self._handlers):
            if fn is py_callable or (
                    inspect.ismethod(py_callable) and inspect.ismethod(fn)
                    and py_callable.__self__ is fn.__self__
                    and py_callable.__func__ is fn.__func__):
                del self._handlers[i]
                self._handler_loggers.pop(id(py_callable), None)
                return self
        LOGGER.warning(f'{py_callable} not exist in {self} call stacks')
        return self

    def clear(self) -> None:
        """Remove all registered handlers."""
        self._handlers.clear()
        self._handler_loggers.clear()

    @property
    def handlers(self) -> list[dict]:
        """List of handler descriptor dicts in registration order (mirrors Cython)."""
        return [
            {
                'fn': fn,
                'logger': self._handler_loggers.get(id(fn), self.logger),
                'idx': i,
                'with_topic': with_topic,
            }
            for i, (fn, with_topic) in enumerate(self._handlers)
        ]


class HandlerStats(TypedDict):
    """Statistics for a handler."""
    calls: int
    total_time: float


class EventHookEx(EventHook):
    """
    Extended ``EventHook`` that tracks per-handler execution statistics.
    """

    __slots__ = ('_stats', '_hook_stats')

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
        self._hook_stats: dict = {
            'n_calls': 0,
            'last_call_start': 0.0,
            'last_call_complete': 0.0,
            'elapsed_seconds': 0.0,
        }

    def trigger(self, msg: PyMessagePayload) -> None:
        """
        Trigger all registered handlers with the given message payload, tracking execution time.

        Hook-level statistics (``stats``) accumulate across trigger calls,
        mirroring the Cython ``EventHookEx`` watcher-based stats.

        Args:
            msg: The message payload to dispatch.
        """
        self._hook_stats['n_calls'] += 1
        self._hook_stats['last_call_start'] = time.perf_counter()
        try:
            self._trigger_impl(msg)
        finally:
            self._hook_stats['last_call_complete'] = time.perf_counter()
            self._hook_stats['elapsed_seconds'] += (
                self._hook_stats['last_call_complete'] - self._hook_stats['last_call_start']
            )

    def _trigger_impl(self, msg: PyMessagePayload) -> None:
        """Per-handler dispatch and timing in registration order."""
        args = msg.args if msg.args is not None else ()
        kwargs = msg.kwargs if msg.kwargs is not None else {}
        topic = msg.topic
        kwargs_with_topic = kwargs.copy()
        kwargs_with_topic[_TOPIC_FIELD_NAME] = topic

        for handler, with_topic in self._handlers:
            handler_id = id(handler)
            if handler_id not in self._stats:
                self._stats[handler_id] = {'calls': 0, 'total_time': 0.0}

            start_time = time.perf_counter()
            try:
                if with_topic:
                    handler(*args, **kwargs_with_topic)
                else:
                    handler(*args, **kwargs)
            except TypeError as e:
                if self.retry_on_unexpected_topic and with_topic and _TOPIC_UNEXPECTED_ERROR in str(e):
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
    def stats(self) -> dict:
        """
        Hook-level execution statistics (mirroring the Cython
        ``EventHookEx.stats`` shape).

        Returns:
            A dict with keys ``'n_calls'``, ``'last_call_start'``,
            ``'last_call_complete'`` and ``'elapsed_seconds'``.
        """
        return dict(self._hook_stats)

    @property
    def handler_stats(self) -> Iterator[tuple[Callable, HandlerStats]]:
        """Iterate over all registered handlers and their per-handler stats."""
        for handler, _ in self._handlers:
            handler_id = id(handler)
            if handler_id in self._stats:
                yield handler, self._stats[handler_id]

    def clear(self) -> None:
        """
        Remove all registered handlers and clear statistics.
        """
        super().clear()
        self._stats.clear()
        self._hook_stats = {
            'n_calls': 0,
            'last_call_start': 0.0,
            'last_call_complete': 0.0,
            'elapsed_seconds': 0.0,
        }
