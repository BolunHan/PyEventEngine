import logging

LOGGER = None

# Try to import the Cython implementation first, fall back to pure Python if unavailable
USING_FALLBACK = False

from .c_topic import (PyTopicType, PyTopicPart, PyTopicPartExact, PyTopicPartAny, PyTopicPartRange, PyTopicPartPattern,
                      PyTopicMatchResult, PyTopic,
                      init_internal_map, clear_internal_map, get_internal_topic, get_internal_map, init_allocator)

from .c_event import PyMessagePayload, EventHook as EventHookBase, EventHookEx

try:
    assert not USING_FALLBACK
    from .c_engine import Full, Empty, EventEngine as EventEngineBase, EventEngineEx

    USING_FALLBACK = False
except (ImportError, AssertionError) as e:
    # Cython module not available (e.g., on Windows or not compiled)
    # Use the pure Python fallback implementation
    import warnings

    warnings.warn(
        f"Cython c_engine module not available ({e}), using pure Python fallback implementation. "
        "Performance may be reduced compared to the Cython version.",
        ImportWarning,
        stacklevel=2
    )
    from .fallback_engine import Full, Empty, EventEngine as EventEngineBase, EventEngineEx

    USING_FALLBACK = True


def set_logger(logger: logging.Logger):
    global LOGGER
    from . import c_topic, c_event, c_engine
    c_topic.LOGGER = logger
    c_event.LOGGER = logger
    c_engine.LOGGER = logger
    LOGGER = logger


# alias for consistency
TopicType = PyTopicType
TopicPart = PyTopicPart
TopicPartExact = PyTopicPartExact
TopicPartAny = PyTopicPartAny
TopicPartRange = PyTopicPartRange
TopicPartPattern = PyTopicPartPattern
TopicMatchResult = PyTopicMatchResult
Topic = PyTopic
MessagePayload = PyMessagePayload
EventHook = EventHookEx
EventEngine = EventEngineEx

__all__ = [
    'TopicType', 'TopicPart', 'TopicPartExact', 'TopicPartAny', 'TopicPartRange', 'TopicPartPattern',
    'TopicMatchResult', 'Topic',
    'init_internal_map', 'clear_internal_map', 'get_internal_topic', 'get_internal_map', 'init_allocator',
    'MessagePayload', 'EventHookBase', 'EventHook',
    'Full', 'Empty', 'EventEngineBase', 'EventEngine', 'USING_FALLBACK'
]
