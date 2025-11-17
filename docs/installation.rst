Installation
============

PyEventEngine can be installed from PyPI or built from source. The package includes both a Cython-accelerated implementation and a pure Python fallback.

Quick Install (PyPI)
--------------------

The simplest way to install PyEventEngine:

.. code-block:: bash

   pip install PyEventEngine

This will install the package with pre-compiled wheels if available for your platform, or automatically fall back to the pure Python implementation.

Install from Source
-------------------

To get the latest development version:

.. code-block:: bash

   pip install git+https://github.com/BolunHan/PyEventEngine.git

Building with Cython (Linux/macOS)
-----------------------------------

To build the Cython extensions from source on Linux or macOS, you'll need:

- Python 3.12 or later
- GCC or Clang compiler
- Cython (automatically installed as build dependency)

**Step 1: Install build dependencies**

.. code-block:: bash

   # Ubuntu/Debian
   sudo apt-get update
   sudo apt-get install build-essential python3-dev

   # macOS (with Homebrew)
   xcode-select --install
   brew install python

**Step 2: Clone and build**

.. code-block:: bash

   git clone https://github.com/BolunHan/PyEventEngine.git
   cd PyEventEngine

   # Create virtual environment (recommended)
   python3 -m venv venv
   source venv/bin/activate

   # Install with Cython compilation
   pip install -e .

**Step 3: Verify installation**

.. code-block:: python

   from event_engine import USING_FALLBACK, EventEngine
   print(f"Using fallback: {USING_FALLBACK}")  # Should be False if compiled
   print(f"EventEngine: {EventEngine}")

If ``USING_FALLBACK`` is ``False``, you're using the compiled Cython version.

Building on Windows
-------------------

Building Cython extensions on Windows requires Microsoft Visual C++ Build Tools.

**Step 1: Install Visual C++ Build Tools**

Download and install from: https://visualstudio.microsoft.com/visual-cpp-build-tools/

During installation, select:
- "Desktop development with C++"
- Windows 10 SDK (or later)

**Step 2: Clone and build**

.. code-block:: powershell

   git clone https://github.com/BolunHan/PyEventEngine.git
   cd PyEventEngine

   # Create virtual environment
   python -m venv venv
   venv\Scripts\activate

   # Install with Cython compilation
   pip install -e .

**Step 3: Verify installation**

.. code-block:: python

   from event_engine import USING_FALLBACK
   print(f"Using fallback: {USING_FALLBACK}")

.. note::
   If compilation fails on Windows, PyEventEngine will automatically fall back to the pure Python implementation. All features work identically, but performance may be reduced.

Using the Pure Python Fallback
-------------------------------

If you explicitly want to use the pure Python implementation (e.g., for debugging or platforms without a C compiler):

.. code-block:: bash

   # Install without attempting compilation
   pip install --no-binary :all: PyEventEngine

Or import directly from the native module:

.. code-block:: python

   from event_engine.native import EventEngine, Topic

   # This always uses pure Python, even if Cython is available
   engine = EventEngine()

Development Installation
-------------------------

For development work with tests and documentation:

.. code-block:: bash

   git clone https://github.com/BolunHan/PyEventEngine.git
   cd PyEventEngine

   # Create and activate virtual environment
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate

   # Install development dependencies
   pip install -e ".[dev,docs]"

   # Run tests
   python -m pytest demo/

   # Build documentation
   cd docs
   make html
   # Open docs/_build/html/index.html in a browser

Requirements
------------

- **Python**: 3.10 or later
- **Required packages**: None (stdlib only for pure Python)
- **Optional build dependencies**: Cython >= 3.0, C compiler
- **Optional dev dependencies**: pytest, sphinx, furo (for docs)

Platform Support
----------------

PyEventEngine is tested on:

- **Linux**: Ubuntu 20.04+, Debian 11+, RHEL 8+
- **macOS**: 11.0+ (Big Sur and later)
- **Windows**: Windows 10/11 with Visual C++ Build Tools

Both x86_64 and ARM64 (Apple Silicon) are supported.

Troubleshooting
---------------

**Compilation fails on Linux**

.. code-block:: bash

   # Install development headers
   sudo apt-get install python3-dev

   # Or use fallback
   PEE_NO_CYTHON=1 pip install PyEventEngine

**Compilation fails on Windows**

- Ensure Visual C++ Build Tools are installed
- Try running from "Developer Command Prompt for VS"
- Or use the pure Python fallback (automatically used if compilation fails)

**Import errors**

.. code-block:: python

   # Check what's actually installed
   import event_engine
   print(event_engine.__version__)
   print(event_engine.USING_FALLBACK)

   # If imports fail, try reinstalling
   pip install --force-reinstall PyEventEngine

**Performance concerns**

If ``USING_FALLBACK`` is ``True`` and you need maximum performance:

1. Ensure you have a C compiler installed
2. Reinstall with ``pip install --force-reinstall --no-cache-dir PyEventEngine``
3. Check for compilation errors in the output

For benchmarking, see :doc:`examples` for performance test examples.

