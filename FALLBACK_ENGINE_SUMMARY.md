# Fallback Engine Implementation Summary

## Overview
A pure Python fallback implementation of EventEngine has been created for cross-platform compatibility, particularly for Windows systems where the Cython implementation with Linux-specific dependencies (pthread, Linux timing) cannot be used.

## Files Created

### 1. `event_engine/capi/fallback_engine.py`
Pure Python implementation providing:
- **Full** and **Empty** exception classes (matching the Cython version)
- **EventEngine** class - main event engine with dict-based topic mappings
- **EventEngineEx** class - extended engine with timer support

**Key Features:**
- Uses `threading.Lock` and `threading.Condition` for synchronization
- Dict-based topic-to-hook mappings (instead of ByteMap)
- Compatible with PyTopic, PyMessagePayload, and EventHook from c_topic and c_event modules
- Proper handling of `args_owner` and `kwargs_owner` flags:
  - When publishing: `args_owner = kwargs_owner = False`
  - When getting: `args_owner = kwargs_owner = True`

**Implementation Details:**
- Message queue: `collections.deque` with threading primitives
- Exact and generic topic hooks stored in separate dicts
- Topic matching uses PyTopic.match() for wildcard/pattern support
- Timer support for second, minute, and custom intervals

### 2. `demo/test_fallback_engine.py`
Comprehensive test suite with 12 test cases:
1. `test_basic_engine()` - Basic EventEngine functionality
2. `test_get_put()` - Get/put operations and exception handling
3. `test_wildcard_topic()` - Wildcard topic matching
4. `test_engine_ex_timers()` - EventEngineEx timer functionality
5. `test_hook_operations()` - EventHook operations
6. `test_publish_method()` - Explicit publish method
7. `test_multiple_handlers_same_topic()` - Multiple handlers per topic
8. `test_unregister_handler()` - Handler unregistration
9. `test_clear()` - Clearing all hooks
10. `test_iter_methods()` - Iteration methods (topics, hooks, items)
11. `test_second_timer()` - Second-aligned timer
12. `test_minute_timer()` - Minute-aligned timer setup

### 3. `demo/capi_performance_test.py` (Updated)
Added performance comparison between Cython and fallback implementations:
- **test_producer_consumer_throughput_and_latency** - Original Cython implementation test
- **test_fallback_producer_consumer_throughput_and_latency** - New fallback implementation test

Both tests measure:
- Throughput (messages/second)
- Latency statistics (min, avg, p50, p95, max in milliseconds)
- Wall-clock time for processing N messages

## API Compatibility

The fallback implementation provides the same API as the Cython version:

```python
# Both work identically
from event_engine.capi import EventEngine  # Cython version
from event_engine.capi.fallback_engine import EventEngine  # Pure Python version

engine = EventEngine(capacity=8192)
topic = PyTopic("test.topic")
engine.register_handler(topic, handler)
engine.start()
engine.put(topic, arg1, arg2, key="value")
engine.stop()
```

## Performance Expectations

The pure Python implementation is expected to be slower than the Cython version but should provide:
- Reasonable throughput for most use cases
- Cross-platform compatibility (Windows, macOS, Linux)
- Same functionality and API surface
- Easier debugging (pure Python, no C extensions)

## Usage Recommendations

1. **Linux systems with Cython**: Use the original `EventEngine` from `event_engine.capi`
2. **Windows or systems without Cython**: Use `FallbackEventEngine` from `event_engine.capi.fallback_engine`
3. **Development/Debugging**: Consider using the fallback version for easier debugging

## Testing

Run the tests:
```bash
# Test fallback implementation
python demo/test_fallback_engine.py

# Performance comparison
python demo/capi_performance_test.py
```

Environment variables for performance testing:
- `PEE_PERF_MSGS`: Number of messages (default: 100,000)
- `PEE_PERF_CAP`: Queue capacity (default: 8,192)
- `PEE_PERF_TIMEOUT`: Timeout in seconds (default: 20)

## Notes

- The fallback implementation does NOT use ByteMap - it uses standard Python dict
- Thread synchronization uses Python's threading module primitives
- Topic matching leverages the existing PyTopic.match() method
- All timer functionality (second, minute, custom intervals) is supported

