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
   :members: Topic, TopicType, TopicPart, TopicPartExact, TopicPartAny, TopicPartRange, TopicPartPattern, TopicMatchResult, init_internal_map, clear_internal_map, get_internal_topic, get_internal_map, init_allocator
   :undoc-members:
   :show-inheritance:

.. note::
   The pure Python fallback (``event_engine.native.topic``) provides the same API.
   See :doc:`native_fallback` for details.

Event Classes
-------------

event_engine.capi.c_event
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.capi.c_event
   :members: MessagePayload, EventHook, EventHookEx, HandlerStats
   :undoc-members:
   :show-inheritance:

.. note::
   The pure Python fallback (``event_engine.native.event``) provides the same API.
   See :doc:`native_fallback` for details.

Engine Classes
--------------

event_engine.capi.c_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.capi.c_engine
   :members: EventEngine, EventEngineEx, Full, Empty
   :undoc-members:
   :show-inheritance:

.. note::
   The pure Python fallback (``event_engine.native.engine``) provides the same API.
   See :doc:`native_fallback` for details.

event_engine.capi.c_engine_ex
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: event_engine.capi.c_engine_ex
   :members: EventEngineEx, EventHookMap, Full, Empty, EVENT_ENGINE
   :undoc-members:
   :show-inheritance:

.. note::
   The C-backed engine (loop, dispatch and timers in C via ``evt_engine`` in
   ``c_engine.h`` / ``c_engine_gil.h``). The process-wide default
   ``EVENT_ENGINE`` singleton is an instance of this class; downstream
   Cython modules can cimport its C pointer as ``C_EVENT_ENGINE``
   (see :doc:`capi_cython`). The loop thread is pinned to the CPU selected by
   the ``EE_LOOP_CPU`` compile-time macro (default 0, ``-1`` disables).

Top-Level Default Engine
~~~~~~~~~~~~~~~~~~~~~~~~

``event_engine.EVENT_ENGINE`` is the process-wide default engine singleton,
backed by :class:`event_engine.capi.c_engine_ex.EventEngineEx` when the
Cython extension is available (falling back to the pure-Python engine).

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
- ``event_engine/capi/c_engine_ex.pyi``

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
