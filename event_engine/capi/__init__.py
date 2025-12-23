import logging

LOGGER = None


from .c_topic import (
    TopicType,
    TopicPart, TopicPartExact, TopicPartAny, TopicPartRange, TopicPartPattern,
    TopicMatchResult, Topic,
    get_internal_topic, get_internal_map
)

from .c_event import MessagePayload, EventHook, EventHookEx

# Try to import the Cython implementation first, fall back to pure Python if unavailable
USING_FALLBACK = False

try:
    assert not USING_FALLBACK
    from .c_engine import Full, Empty, EventEngine, EventEngineEx

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
    from .fallback_engine import Full, Empty, EventEngine, EventEngineEx

    USING_FALLBACK = True


def set_logger(logger: logging.Logger):
    global LOGGER
    from . import c_topic, c_event, c_engine
    c_topic.LOGGER = logger
    c_event.LOGGER = logger
    c_engine.LOGGER = logger
    LOGGER = logger

    """Set the root EventEngine logger and propagate to submodules.

    This updates event_engine.base.LOGGER and the module-level LOGGER used by
    c_event/fallback_engine (if available) so subsequent logs use the provided logger.
    """
    import importlib
    base_mod = importlib.import_module('event_engine.base')
    base_mod.LOGGER = logger
    # Try to update c_event module logger
    try:
        from . import c_event as _c_event
        _c_event.LOGGER = logger.getChild('Event')
    except Exception:
        pass

    # Try to update c_engine module logger
    try:
        from . import c_engine as _c_engine
        _c_engine.LOGGER = logger.getChild('Engine')
    except Exception:
        pass

    # If capi is using fallback engine internally, update its module logger as well
    try:
        from . import fallback_engine as _c_engine_fallback
        _c_engine_fallback.LOGGER = logger.getChild('Engine')
    except Exception:
        pass


__all__ = [
    'TopicType', 'TopicPart', 'TopicPartExact', 'TopicPartAny', 'TopicPartRange', 'TopicPartPattern',
    'TopicMatchResult', 'Topic',
    'get_internal_topic', 'get_internal_map',
    'MessagePayload', 'EventHook', 'EventHookEx',
    'Full', 'Empty', 'EventEngine', 'EventEngineEx', 'USING_FALLBACK',
    'set_logger'
]
