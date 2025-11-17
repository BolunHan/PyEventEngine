API Reference
=============

This page provides auto-generated API documentation from docstrings and type stubs.

.. note::
   For usage examples and conceptual guides, see:

   - :doc:`capi_python` - High-level Python API guide
   - :doc:`examples` - Practical usage examples
   - :doc:`capi_cython` - Cython API (advanced)

event_engine Module
-------------------

Top-level exports and backend selection.

.. automodule:: event_engine
   :members:
   :undoc-members:
   :show-inheritance:

Topic Classes
-------------

event_engine.capi.c_topic
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.capi.c_topic
   :members: PyTopic, PyTopicType, PyTopicPart, PyTopicPartExact, PyTopicPartAny, PyTopicPartRange, PyTopicPartPattern, PyTopicMatchResult, init_internal_map, clear_internal_map, get_internal_topic, get_internal_map, init_allocator
   :undoc-members:
   :show-inheritance:

event_engine.native.topic
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.native.topic
   :members: PyTopic, PyTopicType, PyTopicPart, PyTopicPartExact, PyTopicPartAny, PyTopicPartRange, PyTopicPartPattern, PyTopicMatchResult, init_internal_map, clear_internal_map, get_internal_topic, get_internal_map, init_allocator
   :undoc-members:
   :show-inheritance:

Event Classes
-------------

event_engine.capi.c_event
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.capi.c_event
   :members: PyMessagePayload, EventHook, EventHookEx, HandlerStats
   :undoc-members:
   :show-inheritance:

event_engine.native.event
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.native.event
   :members: PyMessagePayload, EventHook, EventHookEx, HandlerStats
   :undoc-members:
   :show-inheritance:

Engine Classes
--------------

event_engine.capi.c_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.capi.c_engine
   :members: EventEngine, EventEngineEx, Full, Empty
   :undoc-members:
   :show-inheritance:

event_engine.native.engine
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.native.engine
   :members: EventEngine, EventEngineEx, Full, Empty
   :undoc-members:
   :show-inheritance:

Fallback Engine
---------------

event_engine.capi.fallback_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.capi.fallback_engine
   :members: EventEngine, EventEngineEx, Full, Empty
   :undoc-members:
   :show-inheritance:

Type Stubs
----------
The package includes complete type stubs (``.pyi`` files) for the Cython modules:
- ``event_engine/capi/c_topic.pyi``
- ``event_engine/capi/c_event.pyi``
- ``event_engine/capi/c_engine.pyi``
These provide full type information for IDEs and type checkers like mypy.
Example mypy usage:
.. code-block:: bash
   mypy my_app.py
All public APIs are fully typed.

See Also
--------

- :doc:`capi_python` - Detailed Python API guide
- :doc:`examples` - Usage examples
- :doc:`capi_cython` - Cython-level API
- :doc:`native_fallback` - Pure Python implementation details
