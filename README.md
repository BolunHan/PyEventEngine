# PyEventEngine

High-performance, topic-driven event engine for Python with a Cython-accelerated core and a native Python fallback.

- Fast publish/subscribe event routing by topic (exact + generic wildcard/pattern matching)
- Clean, typed API with drop-in fallback when C extensions are unavailable
- Built-in timers, handler stats (EventHookEx), and convenient formatting helpers

## Installation

```bash
pip install PyEventEngine
```

Or install from source:

```bash
pip install git+https://github.com/BolunHan/PyEventEngine.git
```

## Quick Start

```python
import time

from event_engine import EventEngine, Topic, EventHook

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
time.sleep(0.1)  # allow some time for processing
engine.stop()

print(calls)  # [('a test sub-topic', 'Demo.Test'), ('a live sub-topic', 'Demo.Live')]
```

### Timers (EventEngineEx)

```python
from event_engine import EventEngine, EventEngineBase, EventEngine as EventEngineEx, Topic

engine = EventEngineEx(capacity=4096)
engine.start()

# Create a 1-second timer topic and subscribe
timer_topic = engine.get_timer(1.0)
engine.register_handler(timer_topic, lambda **kw: print('tick', kw))

# ... run a little while
import time; time.sleep(3)
engine.stop(); engine.clear()
```

### Logging

By default, the package uses a colored logger under `event_engine.base`. To integrate with your
application's logging, call `set_logger` once after import. It will propagate to submodules.

```python
import logging
from event_engine import set_logger

logger = logging.getLogger('MyApp')
logger.setLevel(logging.INFO)
set_logger(logger)
```

### Fallback behavior

On import, the package tries to use the Cython implementation (`event_engine.capi`). If that fails
(e.g., no compiler available), it automatically falls back to the native Python implementation (`event_engine.native`).
You can check the active backend via:

```python
from event_engine import USING_FALLBACK
print('Using native fallback?' , USING_FALLBACK)
```

## Development

- Run unit tests and demos under `demo/`
- Native performance test: `python demo/native_performance_test.py`
- CAPI performance test (requires compiled extensions): `python demo/capi_performance_test.py`

## Documentation

Full documentation is available at: **https://bolunhan.github.io/PyEventEngine/** *(auto-generated from main branch)*

To build documentation locally, see [`docs/BUILD.md`](docs/BUILD.md).

---

See `demo/` for more examples: matching, timers, performance. Issues and PRs welcome!
