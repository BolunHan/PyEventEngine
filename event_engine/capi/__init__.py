from .c_topic import (PyTopicType, PyTopicPart, PyTopicPartExact, PyTopicPartAny, PyTopicPartRange, PyTopicPartPattern,
                      PyTopicMatchResult, PyTopic,
                      init_internal_map, clear_internal_map, get_internal_topic, get_internal_map, init_allocator)

from .c_event import PyMessagePayload, EventHook, EventHookEx

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

__all__ = [
    'PyTopicType', 'PyTopicPart', 'PyTopicPartExact', 'PyTopicPartAny', 'PyTopicPartRange', 'PyTopicPartPattern',
    'PyTopicMatchResult', 'PyTopic',
    'init_internal_map', 'clear_internal_map', 'get_internal_topic', 'get_internal_map', 'init_allocator',
    'PyMessagePayload', 'EventHook', 'EventHookEx',
    'Full', 'Empty', 'EventEngine', 'EventEngineEx', 'USING_FALLBACK'
]
