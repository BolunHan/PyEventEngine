# PyEventEngine

python native event engine

# Install

```shell
pip install git+https://github.com/BolunHan/PyEventEngine.git
```

or

```shell
pip install PyEventEngine
```

# Use

## basic usage

```python
# init event engine
import time
from EventEngine import EventEngine, Topic

EVENT_ENGINE = EventEngine()
EVENT_ENGINE.start()


# register handler
def test_handler(msg, **kwargs):
    print(msg)


EVENT_ENGINE.register_handler(topic=Topic('SimpleTopic'), handler=test_handler)

# publish message
EVENT_ENGINE.put(topic=Topic('SimpleTopic'), msg='topic called')
time.sleep(1)
EVENT_ENGINE.stop()
```

## regular topic

```python
# init event engine
import time
from EventEngine import EventEngine, Topic, RegularTopic

EVENT_ENGINE = EventEngine()
EVENT_ENGINE.start()


# register handler
def test_handler(msg, **kwargs):
    print(msg)


EVENT_ENGINE.register_handler(topic=RegularTopic('RegularTopic.*'), handler=test_handler)

# publish message
EVENT_ENGINE.put(topic=Topic('RegularTopic.ChildTopic0'), msg='topic called')
time.sleep(1)
EVENT_ENGINE.stop()
```

## timer topic

```python
# init event engine
import time
from EventEngine import EventEngine, Topic, RegularTopic

EVENT_ENGINE = EventEngine()
EVENT_ENGINE.start()


# register handler
def test_handler(**kwargs):
    print(kwargs)


topic = EVENT_ENGINE.get_timer(interval=1)
EVENT_ENGINE.register_handler(topic=topic, handler=test_handler)

# publish message
time.sleep(5)
EVENT_ENGINE.stop()
```

See more advanced usage at .Demo