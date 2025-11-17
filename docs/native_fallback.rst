Native Python Fallback
======================
PyEventEngine includes a pure Python implementation (``event_engine.native``) that mirrors the Cython API exactly. This fallback is automatically used when Cython extensions fail to compile or are unavailable.

Overview
--------

The native fallback provides **identical functionality** with **reduced performance** compared to the Cython version.

Architecture
~~~~~~~~~~~~

The native fallback consists of three modules:
- ``event_engine.native.topic`` - Topic parsing and matching (pure Python)
- ``event_engine.native.event`` - Event hooks and message payloads (pure Python)
- ``event_engine.native.engine`` - Event engine and queue management (``threading`` + ``deque``)
All classes use ``__slots__`` for memory efficiency and expose the same API as the Cython version.

Key Differences
~~~~~~~~~~~~~~~

1. **No C extensions** - All code is pure Python using stdlib only
2. **No custom allocators** - Uses Python's memory management
3. **No ByteMap** - Uses built-in ``dict`` for topic routing
4. **Threading-based** - Uses ``threading.Lock`` and ``threading.Condition``
5. **``owner`` property** - Always returns ``True`` (all Python objects own their data)

Performance
~~~~~~~~~~~

Expected performance characteristics:
- **Topic parsing**: ~10-20x slower than Cython
- **Event dispatch**: ~5-10x slower than Cython
- **Throughput**: ~50-200k msg/s (vs ~500k-1M+ msg/s for Cython)
- **Latency**: ~0.01-0.1ms additional overhead per message

Using the Fallback
------------------

Import Directly
~~~~~~~~~~~~~~~

.. code-block:: python
   from event_engine.native import EventEngine, Topic
   # This always uses pure Python
   engine = EventEngine()

Check Active Backend
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python
   from event_engine import USING_FALLBACK
   if USING_FALLBACK:
       print("Using pure Python fallback")
   else:
       print("Using compiled Cython extensions")

API Compatibility
-----------------

The fallback provides 100% API compatibility with the Cython version.
.. code-block:: python
   # Works identically on both backends
   topic = Topic('Market.Data.{symbol}')
   formatted = topic.format(symbol='AAPL')
   engine = EventEngine(capacity=8192)
   engine.start()
   engine.put(topic, 'data')
   engine.stop()

Performance Tips
----------------

1. **Pre-intern topics** - Parse once, reuse many times
2. **Minimize handler work** - Keep handlers fast
3. **Use exact topics** - Faster than pattern matching
4. **Batch operations** - Publish multiple items together

Testing
-------

Run native implementation tests:
.. code-block:: bash
   python demo/test_native_topic.py
   python demo/test_native_event.py
   python demo/test_native_engine.py
   python demo/native_performance_test.py

See Also
--------

- :doc:`capi_python` - Cython Python API (identical interface)
- :doc:`installation` - Building Cython extensions
- :doc:`examples` - Usage examples (work with both backends)
