# PyEventEngine

[![docs](https://github.com/BolunHan/PyEventEngine/actions/workflows/build-page-docs.yml/badge.svg)](https://github.com/BolunHan/PyEventEngine/actions/workflows/build-page-docs.yml)
[![pypi-linux](https://github.com/BolunHan/PyEventEngine/actions/workflows/publish-posix-to-pypi.yml/badge.svg)](https://github.com/BolunHan/PyEventEngine/actions/workflows/publish-posix-to-pypi.yml)
[![pypi-windows](https://github.com/BolunHan/PyEventEngine/actions/workflows/publish-nt-to-pypi.yml/badge.svg)](https://github.com/BolunHan/PyEventEngine/actions/workflows/publish-nt-to-pypi.yml)

High-performance, topic-driven event engine for Python with a Cython-accelerated core and a native Python fallback.

- Fast publish/subscribe event routing by topic (exact + generic wildcard/pattern matching)
- Clean, typed API with drop-in fallback when C extensions are unavailable
- Built-in timers, handler stats (EventHookEx), and convenient formatting helpers

## Installation

```bash
# From PyPI (pre-compiled wheels available)
pip install PyEventEngine

# From source (requires C compiler + Cython ≥ 3.0)
git clone https://github.com/BolunHan/PyEventEngine.git
cd PyEventEngine

# Build + install
./build.sh -i

# Or via Makefile:
make build && pip install -U . --no-build-isolation

# Or step by step:
python setup.py build_ext --inplace --verbose --force
pip install -U . --no-build-isolation
```

See the [Installation Guide](https://bolunhan.github.io/PyEventEngine/installation.html) for platform-specific prerequisites, compile-time macros, and troubleshooting.

## Quick Start

```python
import time
from event_engine import EventEngine, Topic

# Create and start the engine
engine = EventEngine(capacity=8192)
engine.start()

# Register a handler for an exact topic
exact = Topic('Demo.Hello')

def hello_handler(name: str, topic=None):
    print(f"Hello {name} from {topic.value if topic else 'N/A'}")

engine.register_handler(exact, hello_handler)

# Publish a message
engine.put(exact, 'World')

# Clean up
time.sleep(0.1)
engine.stop()
engine.clear()
```

### Generic topics (wildcards/patterns)

```python
import time
from event_engine import Topic, EventEngine

engine = EventEngine()
pattern = Topic('Demo.{what}')

calls = []

def f(what: str, topic=None):
    calls.append((what, topic.value))

engine.register_handler(pattern, f)

engine.start()
engine.put(Topic('Demo.Test'), 'a test sub-topic')
engine.put(Topic('Demo.Live'), 'a live sub-topic')
time.sleep(0.1)  # allow time for processing
engine.stop()

print(calls)  # [('a test sub-topic', 'Demo.Test'), ('a live sub-topic', 'Demo.Live')]
```

### Timers (EventEngineEx)

```python
import time
from event_engine import EventEngineEx, Topic

engine = EventEngineEx(capacity=4096)
engine.start()

# Create a 1-second timer topic and subscribe
timer_topic = engine.get_timer(1.0)
engine.register_handler(timer_topic, lambda **kw: print('tick', kw))

time.sleep(3)
engine.stop()
engine.clear()
```

### Logging

By default, the package uses a colored logger under `event_engine.base`. To integrate with your
application's logging, call `set_logger` once after import — it propagates to submodules.

```python
import logging
from event_engine import set_logger

logger = logging.getLogger('MyApp')
logger.setLevel(logging.INFO)
set_logger(logger)
```

### Fallback behavior

On import, the package tries to use the Cython implementation (`event_engine.capi`). If that fails
(e.g., no compiler available), it automatically falls back to the native Python implementation
(`event_engine.native`). Check the active backend:

```python
from event_engine import USING_FALLBACK
print('Using native fallback?', USING_FALLBACK)
```

## Development

```bash
# Clone and build in-place
git clone https://github.com/BolunHan/PyEventEngine.git
cd PyEventEngine
./build.sh -i

# Run tests
python -m pytest demo/

# Performance benchmarks
python demo/native_performance_test.py
python demo/capi_performance_test.py       # requires compiled extensions
```

### Build scripts

| Command | Effect |
|---|---|
| `./build.sh -i` | Clean + build + install |
| `./build.sh -l` | List compile-time macros |
| `make build` | Clean + build in-place |
| `make clean-all` | Deep clean (removes `.c`/`.so`) |

## Documentation

Full documentation: **https://bolunhan.github.io/PyEventEngine/**

Build locally:

```bash
pip install sphinx furo sphinx-autodoc-typehints
cd docs
sphinx-build -M html . _build
# Open _build/html/index.html
```

## License

MIT — see [LICENSE](LICENSE).
