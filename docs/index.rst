.. PyEventEngine documentation master file

PyEventEngine Documentation
============================

High-performance, topic-driven event engine for Python with a
Cython-accelerated core and a native Python fallback.

**PyEventEngine** provides fast publish/subscribe event routing by topic
with exact and generic wildcard/pattern matching.  It features a clean,
typed API with automatic fallback when C extensions are unavailable,
plus built-in timers, handler statistics, and convenient formatting
helpers.

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   welcome
   installation
   examples

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   capi_python
   capi_cython
   capi_c
   native_fallback

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api_reference

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
