import logging

LOGGER = None

# Indicate we are using the native (fallback) implementation
USING_FALLBACK = True

from .topic import (
    PyTopicType, PyTopicPart, PyTopicPartExact, PyTopicPartAny, PyTopicPartRange, PyTopicPartPattern,
    PyTopicMatchResult, PyTopic,
    init_internal_map, clear_internal_map, get_internal_topic, get_internal_map, init_allocator,
)

from .event import PyMessagePayload, EventHook as EventHookBase, EventHookEx
from .engine import Full, Empty, EventEngine as EventEngineBase, EventEngineEx


def set_logger(logger: logging.Logger):
    """Set the root EventEngine logger and propagate to native submodules."""
    global LOGGER
    from . import topic, event, engine
    topic.LOGGER = logger
    event.LOGGER = logger
    engine.LOGGER = logger
    LOGGER = logger

    # Update native submodules if they expose LOGGER
    try:
        from . import event as _event
        _event.LOGGER = logger.getChild('Event')
    except Exception:
        pass
    try:
        from . import engine as _engine
        _engine.LOGGER = logger.getChild('Engine')
    except Exception:
        pass


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
    'Full', 'Empty', 'EventEngineBase', 'EventEngine', 'USING_FALLBACK',
    'set_logger'
]
