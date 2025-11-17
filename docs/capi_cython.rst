Cython API Reference
====================

This page documents the Cython-level API in ``event_engine.capi``. These are ``cdef`` classes and methods exposed by the ``.pyx`` files.

.. note::
   For typical Python usage, see :doc:`capi_python`. The Cython API is primarily for performance-critical code or extending PyEventEngine in Cython.

Overview
--------

The Cython API provides typed access to the underlying C structures with minimal Python overhead. All Cython classes are defined in ``.pyx`` files with corresponding ``.pxd`` declaration files.

Importing Cython Definitions
-----------------------------

To use the Cython API in your own Cython code:

.. code-block:: cython

   # my_module.pyx
   from event_engine.capi.c_topic cimport PyTopic, PyTopicPart
   from event_engine.capi.c_event cimport PyMessagePayload, EventHook
   from event_engine.capi.c_engine cimport EventEngine

Or import everything:

.. code-block:: cython

   from event_engine.capi cimport *

Topic Classes (c_topic.pyx)
----------------------------

PyTopicType
~~~~~~~~~~~

.. code-block:: cython

   cpdef enum PyTopicType:
       TOPIC_PART_EXACT = 0
       TOPIC_PART_ANY = 1
       TOPIC_PART_RANGE = 2
       TOPIC_PART_PATTERN = 3

PyTopicPart
~~~~~~~~~~~

Base class for topic parts:

.. code-block:: cython

   cdef class PyTopicPart:
       cdef TopicPart* header
       cdef bint owner

       cdef PyTopicPart c_next(self)
       cpdef PyTopicType ttype(self)
       cpdef uint64_t addr(self)

PyTopicPartExact
~~~~~~~~~~~~~~~~

.. code-block:: cython

   cdef class PyTopicPartExact(PyTopicPart):
       @staticmethod
       cdef PyTopicPartExact c_from_header(TopicPart* header, bint owner=*)

       cpdef str part(self)  # Get the literal string

PyTopicPartAny
~~~~~~~~~~~~~~

.. code-block:: cython

   cdef class PyTopicPartAny(PyTopicPart):
       cpdef str name(self)  # Get the wildcard name

PyTopicPartRange
~~~~~~~~~~~~~~~~

.. code-block:: cython

   cdef class PyTopicPartRange(PyTopicPart):
       cpdef options(self)  # Iterator over option strings

PyTopicPartPattern
~~~~~~~~~~~~~~~~~~

.. code-block:: cython

   cdef class PyTopicPartPattern(PyTopicPart):
       cpdef str pattern(self)
       cpdef object regex(self)  # Returns re.Pattern

PyTopic
~~~~~~~

Main topic class:

.. code-block:: cython

   cdef class PyTopic:
       cdef Topic* header
       cdef bint owner

       @staticmethod
       cdef PyTopic c_from_header(Topic* header, bint owner=*)

       cpdef str value(self)
       cpdef bint is_exact(self)
       cpdef uint64_t hash_value(self)
       cpdef uint64_t addr(self)

       cpdef PyTopicPart get_part(self, int index)
       cpdef int length(self)

       cpdef PyTopic format(self, **kwargs)
       cpdef PyTopicMatchResult match(self, PyTopic other)

Example usage:

.. code-block:: cython

   cdef PyTopic topic = PyTopic("Market.Data.AAPL")
   cdef uint64_t topic_hash = topic.hash_value()

   # Access parts
   cdef int n_parts = topic.length()
   cdef PyTopicPart part0 = topic.get_part(0)

Event Classes (c_event.pyx)
---------------------------

PyMessagePayload
~~~~~~~~~~~~~~~~

.. code-block:: cython

   cdef class PyMessagePayload:
       cdef MessagePayload* header
       cdef bint owner
       cdef bint args_owner
       cdef bint kwargs_owner

       @staticmethod
       cdef PyMessagePayload c_from_header(MessagePayload* header,
                                           bint owner=*,
                                           bint args_owner=*,
                                           bint kwargs_owner=*)

       cpdef PyTopic topic(self)
       cpdef tuple args(self)
       cpdef dict kwargs(self)
       cpdef uint64_t seq_id(self)

EventHook
~~~~~~~~~

.. code-block:: cython

   cdef class EventHook:
       cdef EventHandler* handlers_no_topic
       cdef EventHandler* handlers_with_topic
       cdef public PyTopic topic
       cdef public object logger
       cdef public bint retry_on_unexpected_topic

       cdef void c_safe_call_no_topic(self, EventHandler* handler, tuple args, dict kwargs)
       cdef void c_safe_call_with_topic(self, EventHandler* handler, tuple args, dict kwargs)

       @staticmethod
       cdef inline void c_free_handlers(EventHandler* handlers)

       cpdef void trigger(self, PyMessagePayload msg)
       cpdef void add_handler(self, object handler, bint deduplicate=*)
       cpdef EventHook remove_handler(self, object handler)
       cpdef void clear(self)
       cpdef list handlers(self)

EventHookEx
~~~~~~~~~~~

Extended hook with statistics:

.. code-block:: cython

   cdef class EventHookEx(EventHook):
       cdef ByteMap* stats_map

       cpdef void trigger(self, PyMessagePayload msg)
       cpdef dict get_stats(self, object py_callable)
       cpdef object stats(self)  # Returns iterator

Engine Classes (c_engine.pyx)
------------------------------

EventEngine
~~~~~~~~~~~

.. code-block:: cython

   cdef class EventEngine:
       cdef MessageQueue* queue
       cdef ByteMap* exact_topic_hooks
       cdef ByteMap* generic_topic_hooks
       cdef MemoryAllocator* allocator
       cdef public object logger
       cdef public bint active
       cdef public object engine
       cdef int capacity
       cdef uint64_t seq_id

       cdef int c_publish(self, PyTopic topic, tuple args, dict kwargs,
                         bint block, int max_spin, double timeout) nogil
       cdef PyMessagePayload c_get(self, bint block, int max_spin, double timeout) nogil
       cdef void c_trigger(self, PyMessagePayload msg)
       cdef void c_loop(self)

       cpdef void register_hook(self, EventHook hook)
       cpdef EventHook unregister_hook(self, PyTopic topic)
       cpdef void register_handler(self, PyTopic topic, object handler, bint deduplicate=*)
       cpdef void unregister_handler(self, PyTopic topic, object handler)

``nogil`` Methods
~~~~~~~~~~~~~~~~~

Several performance-critical methods release the GIL:

- ``c_publish()``: Publishing can happen without GIL
- ``c_get()``: Queue operations don't need GIL
- ``c_loop()``: Main event loop releases GIL while waiting

This allows other Python threads to run concurrently with the engine.

Performance Tips
----------------

Avoiding Python Overhead
~~~~~~~~~~~~~~~~~~~~~~~~

When possible, use typed Cython code:

.. code-block:: cython

   # Slower (Python)
   topic = PyTopic("Market.Data.AAPL")
   value = topic.value  # Calls Python __get__

   # Faster (Cython)
   cdef PyTopic topic = PyTopic("Market.Data.AAPL")
   cdef str value = topic.value()  # Direct C call

Type Declarations
~~~~~~~~~~~~~~~~~

Declare types for best performance:

.. code-block:: cython

   cdef EventEngine engine = EventEngine(capacity=8192)
   cdef PyTopic topic = PyTopic("Test.Topic")
   cdef PyMessagePayload msg

   # Fast loop
   cdef int i
   for i in range(10000):
       engine.put(topic, i)  # Minimal overhead

Using Static Methods
~~~~~~~~~~~~~~~~~~~~

The ``c_from_header`` static methods create Python wrappers around existing C structures efficiently:

.. code-block:: cython

   cdef Topic* c_topic = topic_parse(b"My.Topic", 8)
   cdef PyTopic py_topic = PyTopic.c_from_header(c_topic, owner=True)

Memory Management
-----------------

Owner Flag
~~~~~~~~~~

The ``owner`` flag determines memory management:

- ``owner=True``: Python object owns C memory, will free on ``__dealloc__``
- ``owner=False``: Python object is a view, C memory managed elsewhere

.. code-block:: cython

   cdef PyTopic owned = PyTopic("Test")  # owner=True
   # Will call topic_free() in __dealloc__

   cdef PyTopic view = PyTopic.c_from_header(some_topic, owner=False)
   # Will NOT free some_topic

Reference Counting
~~~~~~~~~~~~~~~~~~

For Python objects in C structures (e.g., ``args`` in ``MessagePayload``):

.. code-block:: cython

   # When setting args
   Py_INCREF(args)
   payload.header.args = <void*><PyObject*>args

   # When clearing/deallocating
   if payload.header.args:
       Py_XDECREF(<object>payload.header.args)
       payload.header.args = NULL

The Cython classes handle this automatically in their ``__init__``/``__dealloc__`` methods.

Exception Handling
------------------

Cython methods can raise Python exceptions:

.. code-block:: cython

   cdef PyTopic topic
   try:
       topic = PyTopic("Invalid..{")  # May raise ValueError
   except ValueError as e:
       print(f"Parse error: {e}")

For ``nogil`` functions, exceptions are deferred:

.. code-block:: cython

   cdef int result
   with nogil:
       result = engine.c_publish(topic, args, kwargs, True, 1000, 0.0)

   if result != 0:
       raise Full("Queue is full")

Building Cython Extensions
---------------------------

To build your own Cython extension using PyEventEngine:

**setup.py:**

.. code-block:: python

   from setuptools import setup, Extension
   from Cython.Build import cythonize
   import event_engine

   extensions = [
       Extension(
           "my_module",
           sources=["my_module.pyx"],
           include_dirs=[event_engine.get_include()],
           language="c++",  # If using C++ features
       )
   ]

   setup(
       ext_modules=cythonize(extensions, compiler_directives={'language_level': 3})
   )

**my_module.pyx:**

.. code-block:: cython

   from event_engine.capi.c_topic cimport PyTopic
   from event_engine.capi.c_event cimport PyMessagePayload
   from event_engine.capi.c_engine cimport EventEngine

   cpdef void my_function():
       cdef EventEngine engine = EventEngine(capacity=1024)
       cdef PyTopic topic = PyTopic("Test.Topic")

       engine.start()
       engine.put(topic, 123, block=True)
       engine.stop()

See Also
--------

- :doc:`capi_c` - Low-level C API
- :doc:`capi_python` - High-level Python API
- `Cython documentation <https://cython.readthedocs.io/>`_ - General Cython usage
- Source: ``event_engine/capi/*.pyx`` and ``event_engine/capi/*.pxd``

