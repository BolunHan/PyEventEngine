Welcome
=======

Welcome to PyEventEngine!

Overview
--------

PyEventEngine is a high-performance, topic-driven event engine designed for Python applications that need:

- **Fast Event Routing**: Publish/subscribe pattern with minimal overhead
- **Flexible Topic Matching**: Exact topics, wildcards (``{name}``), ranges (``(opt1|opt2)``), and regex patterns
- **Performance Options**: Cython-accelerated core with automatic Python fallback
- **Built-in Features**: Timers, handler statistics, and comprehensive logging

Key Features
------------

Performance
~~~~~~~~~~~

- **Cython Core**: C-level performance for critical paths (topic parsing, event dispatching, queue management)
- **Automatic Fallback**: Pure Python implementation when compilation is unavailable
- **Lock-Free Queues**: High-throughput message passing with minimal contention
- **Zero-Copy**: Efficient payload handling with reference counting

Topic System
~~~~~~~~~~~~

PyEventEngine supports multiple topic matching strategies:

- **Exact**: ``"Market.Data.AAPL"`` matches only exactly that topic
- **Wildcard**: ``"Market.Data.{symbol}"`` matches any symbol (e.g., ``Market.Data.TSLA``)
- **Range**: ``"Market.(Equity|Futures).Data"`` matches either Equity or Futures
- **Pattern**: ``"Market.Data./^[A-Z]{4}$/"`` matches 4-letter symbols using regex

Engine Features
~~~~~~~~~~~~~~~

- **Typed API**: Full type hints and stub files (``.pyi``) for IDE support
- **Thread-Safe**: Safe concurrent access from multiple threads
- **Hook Statistics**: Track handler execution time and call counts (``EventHookEx``)
- **Timer Support**: Built-in timer topics at various intervals (second, minute, custom)
- **Graceful Degradation**: Automatic fallback to Python when Cython unavailable

Use Cases
---------

PyEventEngine is ideal for:

- **Trading Systems**: Low-latency market data distribution and order routing
- **Real-time Analytics**: Stream processing with topic-based filtering
- **Microservices**: Inter-service communication with topic-based routing
- **Event-Driven Applications**: Decoupled components communicating via events
- **Monitoring & Telemetry**: High-throughput metric collection and distribution

Architecture
------------

PyEventEngine consists of three main layers:

1. **Topic Layer** (``event_engine.capi.c_topic`` / ``event_engine.native.topic``)

   - Topic parsing and representation
   - Pattern matching and comparison
   - Internal string pool for deduplication

2. **Event Layer** (``event_engine.capi.c_event`` / ``event_engine.native.event``)

   - Message payload encapsulation
   - Event hooks and handler registration
   - Handler execution with error handling
   - Optional statistics tracking

3. **Engine Layer** (``event_engine.capi.c_engine`` / ``event_engine.native.engine``)

   - Message queue management
   - Event loop and threading
   - Topic-to-hook routing (exact + generic maps)
   - Timer support (EventEngineEx)

Getting Started
---------------

See the :doc:`installation` guide to install PyEventEngine, then check out the :doc:`examples` for common usage patterns.

For detailed API documentation, see:

- :doc:`capi_python` - High-level Python API (recommended)
- :doc:`capi_cython` - Cython API for advanced users
- :doc:`capi_c` - C API for extension developers
- :doc:`native_fallback` - Pure Python fallback implementation
- :doc:`api_reference` - Complete API reference

Community
---------

- **GitHub**: https://github.com/BolunHan/PyEventEngine
- **Issues**: https://github.com/BolunHan/PyEventEngine/issues
- **PyPI**: https://pypi.org/project/PyEventEngine/

License
-------

PyEventEngine is released under the MIT License. See the LICENSE file for details.

