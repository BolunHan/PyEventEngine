Native Python Fallback
======================

PyEventEngine includes a pure Python implementation (``event_engine.native``)
that mirrors the Cython API exactly.  This fallback is automatically used when
Cython extensions fail to compile or are unavailable — no code changes needed.

Overview
--------

The native fallback provides **identical functionality** with **reduced
performance** compared to the Cython version.  It is designed for:

- Platforms without a C compiler (e.g., some Windows or container environments)
- Development and debugging (pure Python is easier to introspect)
- CI/CD pipelines that don't build Cython extensions
- Quick prototyping without the build step

.. note::
   All examples and API documentation apply to both backends.  The top-level
   ``from event_engine import ...`` automatically selects the fastest
   available implementation.

Architecture
~~~~~~~~~~~~

The native fallback consists of three modules:

- ``event_engine.native.topic`` — Topic parsing and matching (pure Python)
- ``event_engine.native.event`` — Event hooks and message payloads (pure Python)
- ``event_engine.native.engine`` — Event engine and queue management
  (``threading`` + ``collections.deque``)

All classes use ``__slots__`` for memory efficiency and expose the same API as
the Cython version.

Internal Data Structures
~~~~~~~~~~~~~~~~~~~~~~~~

Unlike the Cython backend which uses C-level ``ByteMap``, ``MemoryAllocator``,
and ``MessageQueue``, the native backend uses Python built-ins:

.. list-table::
   :header-rows: 1

   * - Component
     - Cython (capi)
     - Native (fallback)
   * - Topic routing (exact)
     - ``ByteMap`` (xxHash3)
     - ``dict[str, EventHook]``
   * - Topic routing (generic)
     - ``ByteMap`` (xxHash3)
     - ``dict[str, EventHook]``
   * - Message queue
     - Lock-free ring buffer
     - ``deque`` + ``threading.Condition``
   * - Payload allocation
     - ``MemoryAllocator`` pool
     - Python ``__new__`` / GC
   * - Handler lists
     - Linked list (``EventHandler*``)
     - Python ``list[Callable]``
   * - Statistics tracking
     - ``ByteMap`` (handler→stats)
     - ``dict[int, HandlerStats]``

Key Differences
~~~~~~~~~~~~~~~

1. **No C extensions** — All code is pure Python using stdlib only
2. **No custom allocators** — Uses Python's memory management (``__new__`` / GC)
3. **No ByteMap** — Uses built-in ``dict`` for topic routing
4. **Threading-based** — Uses ``threading.Lock`` and ``threading.Condition``
   instead of lock-free queues
5. **``owner`` property** — Always returns ``True`` (Python objects always own
   their data)
6. **No GIL release** — All operations hold the GIL; no ``nogil`` sections

Performance
~~~~~~~~~~~

Expected performance characteristics (ballpark figures, YMMV):

.. list-table::
   :header-rows: 1

   * - Metric
     - Cython (capi)
     - Native (fallback)
   * - Topic parsing
     - 1× (baseline)
     - ~10–20× slower
   * - Event dispatch
     - 1× (baseline)
     - ~5–10× slower
   * - Throughput (msg/s)
     - ~500k–1M+
     - ~50k–200k
   * - P99 latency (ms)
     - ~0.001–0.01
     - ~0.01–0.1
   * - Memory per payload
     - ~64–128 bytes
     - ~200–400 bytes

Actual numbers depend on handler complexity, topic pattern usage, and system
load.  Run ``demo/native_performance_test.py`` and
``demo/capi_performance_test.py`` for your specific environment.

Using the Fallback
------------------

Import Directly
~~~~~~~~~~~~~~~

To force the pure Python implementation regardless of whether Cython
extensions are available:

.. code-block:: python

   from event_engine.native import EventEngine, Topic

   # This always uses pure Python
   engine = EventEngine()

Check Active Backend
~~~~~~~~~~~~~~~~~~~~

Query which backend is currently active:

.. code-block:: python

   from event_engine import USING_FALLBACK

   if USING_FALLBACK:
       print("Using pure Python fallback")
   else:
       print("Using compiled Cython extensions")

The ``USING_FALLBACK`` flag is set at import time and reflects the state of
the top-level ``event_engine`` package.  Direct imports from
``event_engine.native`` always use the fallback regardless of this flag.

API Compatibility
-----------------

The fallback provides **100% API compatibility** with the Cython version.
All classes, methods, properties, and exceptions have identical signatures:

.. code-block:: python

   # Works identically on both backends
   topic = Topic('Market.Data.{symbol}')
   formatted = topic.format(symbol='AAPL')
   engine = EventEngine(capacity=8192)
   engine.start()
   engine.put(topic, 'data')
   engine.stop()

The only observable difference is performance.  Behaviour (topic matching,
handler dispatch, error handling, timer semantics) is tested to be identical.

Thread Safety
-------------

The native fallback uses ``threading.Lock`` and ``threading.Condition`` for
synchronisation:

- **Queue operations** (``put`` / ``get``): Protected by a single re-entrant
  lock with condition variables for not-empty / not-full signalling.
- **Hook registration** (``register_handler`` / ``unregister_handler``): Uses
  a separate lock for the topic→hook dictionaries.
- **Handler execution** (``trigger``): Iterates a snapshot of handlers under
  lock, then calls each handler outside the lock (handlers run concurrently
  with queue operations).

This design matches the Cython backend's thread-safety guarantees:
multiple producers and consumers can safely interact with the engine from
different threads.

.. warning::
   Handlers are called outside the engine lock.  If a handler modifies
   the engine's hooks (e.g., calls ``register_handler``), the
   modification is safe but may not affect the current dispatch cycle.

Performance Tips
----------------

1. **Pre-intern topics** — Parse once, reuse many times.  Each ``Topic()``
   call parses the string and builds a part tree.
2. **Minimize handler work** — Keep handlers fast; offload heavy work to a
   separate thread or queue.
3. **Use exact topics** — Exact matching is O(1) dict lookup; pattern matching
   iterates the generic map and tests each pattern.
4. **Batch operations** — Publishing multiple items in a tight loop is more
   efficient than interleaving with other work.
5. **Right-size the queue** — The default capacity (4095) is fine for most
   use cases.  Larger queues use more memory; smaller queues risk ``Full``
   exceptions under load.

When to Use Which Backend
--------------------------

==================== ========================================================
Scenario             Recommendation
==================== ========================================================
Production (Linux)   Cython (``./build.sh -i``) — maximum throughput
Production (Windows) Cython if MSVC is available; native otherwise
Development          Either — native is easier to debug with ``pdb``
CI/CD                Native — avoids Cython build time and dependencies
Prototyping          Native — zero build step, ``pip install`` and go
==================== ========================================================

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

- :doc:`capi_python` — Cython Python API (identical interface)
- :doc:`installation` — Building Cython extensions
- :doc:`examples` — Usage examples (work with both backends)
- :doc:`api_reference` — Auto-generated API reference
