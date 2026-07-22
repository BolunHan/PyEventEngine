Installation
============

PyEventEngine is a **Cython extension package** — extensions must be
compiled in-place before installation.  Pre-compiled wheels are
available on PyPI for common platforms; building from source requires
a C11 compiler and Cython ≥ 3.0.

Quick Install (PyPI)
--------------------

.. code-block:: bash

   pip install PyEventEngine

This installs the package with pre-compiled wheels if available for your
platform, or falls back to the pure Python implementation if compilation
fails.

Install from Source
-------------------

Quick Build (POSIX)
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/BolunHan/PyEventEngine.git
   cd PyEventEngine

   # Build + install (recommended)
   ./build.sh -i

   # Or via Makefile:
   make build && pip install -U . --no-build-isolation

   # Or step by step:
   python setup.py build_ext --inplace --verbose --force
   pip install -U . --no-build-isolation

.. important::
   ``pip install -e .`` (editable mode) is **not** recommended for
   PyEventEngine.  Editable installs may interfere with ``.pxd``
   resolution for downstream Cython projects.  Always use
   ``setup.py build_ext --inplace`` followed by
   ``pip install -U . --no-build-isolation``.

Build Script Reference
----------------------

``build.sh``
~~~~~~~~~~~~

The primary build script for POSIX (Linux/macOS).  Supports venv
activation, clean/rebuild/all-clean modes, optional pip install, and
compile-time macro introspection.

.. code-block:: bash

   ./build.sh [options]

Options:

========  ============================================================
``-v``    Path to virtual environment to activate before building
``-i``    ``pip install .`` after build
``-r``    Force-reinstall (uninstall + ``pip install --force-reinstall``)
``-c``    Clean build artifacts only (no build)
``-a``    Deep clean — remove ``.c`` and ``.so`` files, then exit
``-l``    List all compile-time macros and their default values
``-h``    Show help
========  ============================================================

``Makefile``
~~~~~~~~~~~~

Convenience targets wrapping ``build.sh``:

=============  =====================================================
Target         Effect
=============  =====================================================
``build``      Clean + ``build_ext --inplace --verbose --force``
``dev``        Alias for ``build``
``install``    Build + ``pip install .``
``reinstall``  Build + force-reinstall (uninstall first)
``clean``      Remove ``build/``, ``*.egg-info``, ``includes/``
``clean-all``  ``clean`` + delete all ``.c`` and ``.so`` files
``list-args``  List compile-time macros (delegates to ``build.sh -l``)
=============  =====================================================

``build.ps1`` (Windows)
~~~~~~~~~~~~~~~~~~~~~~~

PowerShell build script for Windows NT.  Activates a specified venv,
cleans artifacts, and runs ``build_ext --inplace --verbose --force``.

.. code-block:: powershell

   .\build.ps1 -VenvPath "C:\Users\...\venv_313"

Compile-Time Macros
-------------------

PyEventEngine exposes ``#define`` macros that control allocation
behaviour, page sizes, and queue defaults.  Override any macro at
compile time by setting an environment variable of the same name:

.. code-block:: bash

   DEBUG=1 ./build.sh            # Enable debug mode
   AP_ALLOC_VIGILANT=0 make build # Disable vigilant/canary checks

**Listing available macros:**

.. code-block:: bash

   ./build.sh -l        # Reads macros.json; auto-generates via probe.py if missing
   make list-args       # Same, via Makefile
   python probe.py      # Run the probe manually

``probe.py`` scans Cython ``.pxd`` files for ``cdef extern from``
headers, extracts every ``#define`` macro from those headers, and
writes a JSON inventory to ``macros.json``.

**Key macros** (see ``macros.json`` for the full list):

======================================== ===================== ==========================================
Macro                                    Default               Description
======================================== ===================== ==========================================
``AP_ALLOC_VIGILANT``                    ``1``                 Enable bounds/canary validation
``AP_ALLOC_MAGIC``                       ``0xCFBBBBFCULL``     Magic sentinel for live allocations
``AP_DEALLOC_MAGIC``                     ``0xDEADDEADULL``     Magic sentinel for freed memory
``AP_HEAP_AUTOPAGE_CAPACITY``            ``64 KiB``            Default heap page size
``AP_HEAP_AUTOPAGE_CAPACITY_MAX``        ``16 MiB``            Max heap page size
``AP_HEAP_AUTOPAGE_ALIGNMENT``           ``4 KiB``             Heap page alignment
``DEFAULT_MQ_CAPACITY``                  ``0x0fff`` (4095)     Default message queue capacity
``DEFAULT_MQ_SPIN_LIMIT``                ``0xffff`` (65535)    Spin-lock limit for non-blocking ops
======================================== ===================== ==========================================

Prerequisites
-------------

- **Python**: 3.10 or later
- **Build**: Cython ≥ 3.0, C11 compiler (GCC/Clang on Linux, MSVC on Windows)
- **Runtime**: No external Python dependencies (stdlib only for pure Python)
- **Docs** (optional): ``sphinx`` + ``furo`` + ``sphinx-autodoc-typehints``

Linux
~~~~~

.. code-block:: bash

   # Ubuntu/Debian
   sudo apt-get install build-essential python3-dev

   # Arch/Manjaro
   sudo pacman -S base-devel

macOS
~~~~~

.. code-block:: bash

   xcode-select --install
   brew install python

Windows
~~~~~~~

- Visual C++ Build Tools (`download <https://visualstudio.microsoft.com/visual-cpp-build-tools/>`_)
- Select "Desktop development with C++" and Windows SDK during install

Verifying the Build
-------------------

.. code-block:: python

   from event_engine import __version__, USING_FALLBACK

   print(__version__)
   print(f"Using fallback: {USING_FALLBACK}")  # False if Cython compiled

   from event_engine import EventEngine, Topic, EventHook
   engine = EventEngine()
   engine.start()
   engine.stop()
   print("OK")

If ``USING_FALLBACK`` is ``False``, the compiled Cython version is active.

Using ``get_include()`` in Downstream Projects
----------------------------------------------

PyEventEngine provides ``event_engine.get_include()`` to help downstream
Cython extensions find ``.pxd`` and ``.h`` files:

.. code-block:: python

   from setuptools import setup, Extension
   from Cython.Build import cythonize
   import event_engine

   ext = Extension(
       "my_module",
       sources=["my_module.pyx"],
       include_dirs=event_engine.get_include(),
   )
   setup(ext_modules=cythonize([ext]))

This returns a list of absolute paths to the package directory, the
``base/`` and ``capi/`` subdirectories, and the ``includes/`` mirror
tree — everything the Cython compiler needs to ``cimport`` from
PyEventEngine.

Using the Pure Python Fallback
------------------------------

If you explicitly want to use the pure Python implementation (e.g., for
debugging or platforms without a C compiler):

.. code-block:: bash

   # Install without attempting compilation
   pip install --no-binary :all: PyEventEngine

Or import directly from the native module:

.. code-block:: python

   from event_engine.native import EventEngine, Topic

   # This always uses pure Python, even if Cython is available
   engine = EventEngine()

See :doc:`native_fallback` for details on the fallback implementation.

Building the Documentation
--------------------------

.. code-block:: bash

   pip install sphinx furo sphinx-autodoc-typehints
   cd docs
   sphinx-build -M html . _build

Open ``docs/_build/html/index.html`` in a browser.

Troubleshooting
---------------

**Compilation fails with missing Python.h**

.. code-block:: bash

   sudo apt-get install python3-dev

**Cython version mismatch**

.. code-block:: bash

   pip install -U cython

**Binary incompatibility after rebuild**

If you see ``ValueError: ... size changed, may indicate binary
incompatibility``, do a deep clean and rebuild:

.. code-block:: bash

   ./build.sh -a            # Remove all .c and .so files
   ./build.sh -i            # Rebuild and install

**Build fails or no compiler available**

Pre-compiled wheels are available on PyPI for common platforms.  If
building from source fails, install from PyPI and the pure Python
fallback will be used automatically:

.. code-block:: bash

   pip install PyEventEngine

   python -c "from event_engine import USING_FALLBACK; print(USING_FALLBACK)"  # True

All features work identically in the fallback; only throughput is lower.

**Performance concerns**

If ``USING_FALLBACK`` is ``True`` and you need maximum performance:

1. Ensure you have a C compiler installed
2. Reinstall with ``pip install --force-reinstall --no-cache-dir PyEventEngine``
3. Check for compilation errors in the output
4. Or build from source with ``./build.sh -i``

For benchmarking, see :doc:`examples` for performance test examples.
