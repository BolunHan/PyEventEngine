C API Reference
===============

This page documents the low-level C API exposed by PyEventEngine's Cython extensions. These APIs are used internally by the Cython layer and are generally not needed for typical Python usage.

.. warning::
   The C API is considered advanced/internal. Most users should use the :doc:`capi_python` instead. Direct C API usage requires Cython or C extension knowledge.

Overview
--------

PyEventEngine's C layer provides the following components:

- **Topic structures**: Fast topic parsing and matching
- **Message payloads**: Zero-copy message passing
- **Event hooks**: Low-overhead handler dispatch
- **Queue primitives**: Lock-free/hybrid message queues
- **Memory allocators**: Pool-based allocation for payloads

All C structures are exposed to Python via Cython ``cdef`` classes in the ``.pyx`` files.

Header Files
------------

The C API is declared in the following headers under ``event_engine/capi/``:

c_topic.h
~~~~~~~~~

Topic data structures and parsing:

.. code-block:: c

   typedef enum {
       TOPIC_PART_EXACT = 0,
       TOPIC_PART_ANY = 1,
       TOPIC_PART_RANGE = 2,
       TOPIC_PART_PATTERN = 3
   } TopicType;

   typedef struct TopicPart {
       TopicType type;
       char* data;
       size_t data_len;
       struct TopicPart* next;
   } TopicPart;

   typedef struct Topic {
       char* literal;
       size_t literal_len;
       uint64_t hash;
       TopicPart* parts;
       int is_exact;
   } Topic;

Key functions:

- ``Topic* topic_parse(const char* topic_str, size_t len)`` - Parse a topic string
- ``int topic_match(Topic* pattern, Topic* target)`` - Check if target matches pattern
- ``void topic_free(Topic* topic)`` - Free topic memory

c_event.h
~~~~~~~~~

Event structures for message passing:

.. code-block:: c

   typedef struct MessagePayload {
       Topic* topic;
       void* args;        // PyObject* (tuple)
       void* kwargs;      // PyObject* (dict)
       uint64_t seq_id;
       struct MemoryAllocator* allocator;
   } MessagePayload;

.. note::
   ``args`` and ``kwargs`` are opaque ``void*`` in C but point to Python objects (``PyObject*``). Reference counting is managed by the Cython layer.

c_allocator.h
~~~~~~~~~~~~~

Custom memory allocator for payload objects:

.. code-block:: c

   typedef struct MemoryAllocator {
       void* pool;
       size_t capacity;
       size_t block_size;
       int active;
   } MemoryAllocator;

   MemoryAllocator* c_allocator_new(size_t capacity, size_t block_size);
   void* c_heap_alloc(MemoryAllocator* alloc, size_t size);
   void c_heap_recycle(MemoryAllocator* alloc, void* ptr);
   void c_allocator_free(MemoryAllocator* alloc);

c_bytemap.h
~~~~~~~~~~~

Hash map for topic-to-hook lookups:

.. code-block:: c

   typedef struct MapEntry {
       const char* key;
       void* value;
       uint64_t hash;
       struct MapEntry* next;
   } MapEntry;

   typedef struct ByteMap {
       MapEntry** buckets;
       size_t capacity;
       size_t size;
   } ByteMap;

   ByteMap* c_bytemap_new(size_t capacity);
   void c_bytemap_set(ByteMap* map, const char* key, void* value);
   void* c_bytemap_get(ByteMap* map, const char* key);
   void* c_bytemap_pop(ByteMap* map, const char* key);
   void c_bytemap_free(ByteMap* map);

xxhash.h
~~~~~~~~

Fast hashing (xxHash3) for topic strings:

.. code-block:: c

   uint64_t XXH3_64bits(const void* data, size_t len);

This is a vendored copy of the xxHash library for consistent, fast hashing.

Memory Management
-----------------

Ownership Rules
~~~~~~~~~~~~~~~

1. **Topics**:

   - Topics created via ``topic_parse()`` must be freed with ``topic_free()``
   - Topics from the internal pool (``c_bytemap``) are managed by the pool
   - Python ``PyTopic`` wrappers manage C ``Topic*`` via ``owner`` flag

2. **MessagePayload**:

   - Payloads allocated via ``MemoryAllocator`` are recycled to the pool
   - ``args`` and ``kwargs`` (Python objects) use CPython reference counting
   - The Cython layer calls ``Py_INCREF``/``Py_DECREF`` as needed

3. **ByteMap**:

   - The map owns keys (copied strings) but not values (just pointers)
   - Caller must manage value lifetime (e.g., hooks)

Allocator Usage
~~~~~~~~~~~~~~~

Example from ``c_engine.pyx``:

.. code-block:: cython

   cdef MemoryAllocator* allocator = c_allocator_new(4096, sizeof(MessagePayload))

   # Allocate a payload
   cdef MessagePayload* payload = <MessagePayload*>c_heap_alloc(allocator, sizeof(MessagePayload))
   payload.topic = some_topic
   payload.args = <void*>args_tuple
   Py_INCREF(args_tuple)

   # ... use payload ...

   # Recycle when done
   Py_XDECREF(<object>payload.args)
   c_heap_recycle(allocator, payload)

   # Clean up allocator on shutdown
   c_allocator_free(allocator)

Thread Safety
-------------

- **Topic parsing**: Thread-safe (no shared state)
- **ByteMap**: **NOT** thread-safe (must be externally locked)
- **MemoryAllocator**: **NOT** thread-safe (designed for single-threaded use or per-thread pools)
- **MessagePayload**: Thread-safe if reference counting is correct

The Cython layer (``c_engine.pyx``) uses Python's GIL and threading primitives to ensure thread safety at the Python API level.

Using from Cython
-----------------

To use the C API in your own Cython extensions:

1. Add ``event_engine.capi`` to your ``include_path``
2. ``cimport`` the relevant ``.pxd`` files

Example:

.. code-block:: cython

   # my_extension.pyx
   from event_engine.capi.c_topic cimport Topic, topic_parse, topic_free

   cdef Topic* t = topic_parse(b"My.Topic.String", 15)
   try:
       print(f"Parsed topic with hash: {t.hash}")
   finally:
       topic_free(t)

See ``event_engine/capi/*.pxd`` for full ``cimport`` declarations.

Performance Considerations
--------------------------

- **Topic parsing**: O(n) in string length; results are cached in ByteMap
- **Topic matching**: O(k) where k = number of parts (~3-5 typically)
- **ByteMap lookups**: O(1) expected, O(n) worst-case (hash collisions)
- **Allocator**: O(1) alloc/recycle when pool is not exhausted

For maximum performance:

- Pre-parse and intern topics (``init_internal_map()``)
- Use exact topics where possible (faster than wildcards)
- Size ByteMap capacity to ~2x expected topics to minimize collisions

Debugging
---------

Enable debug output in Cython:

.. code-block:: python

   import os
   os.environ['CYTHON_TRACE'] = '1'

   # Rebuild and run with profiling/tracing enabled

Use gdb/lldb for C-level debugging:

.. code-block:: bash

   # Build with debug symbols
   CFLAGS="-g -O0" pip install -e .

   # Run under gdb
   gdb --args python my_test.py
   (gdb) break c_topic.c:topic_parse
   (gdb) run

For memory issues, use valgrind:

.. code-block:: bash

   valgrind --leak-check=full python -m pytest demo/

See Also
--------

- :doc:`capi_cython` - Cython API (higher-level, Python-friendly)
- :doc:`capi_python` - Python API (recommended for most users)
- Source code: ``event_engine/capi/*.c`` and ``event_engine/capi/*.h``

