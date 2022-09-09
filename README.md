# PyEventEngine

python native event engine

# Install

```shell
pip install git+https://github.com/BolunHan/PyEventEngine.git
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

See more advanced usage at .Demo