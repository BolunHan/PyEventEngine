Python API Reference (CAPI)
===========================

This page documents the high-level Python API provided by ``event_engine.capi``. This is the **recommended** API for most users.

.. note::
   The API is identical whether using the compiled Cython version or the pure Python fallback. See :doc:`native_fallback` for fallback-specific details.

Quick Import
------------

.. code-block:: python

   from event_engine import EventEngine, Topic, EventHook, MessagePayload

   # Or import from capi explicitly
   from event_engine.capi import EventEngine, Topic

All public classes and functions are also available at the top level (``event_engine.*``).

Topic Classes
-------------

Topic
~~~~~

.. autoclass:: event_engine.capi.PyTopic
   :members:
   :undoc-members:
   :show-inheritance:

The ``Topic`` alias points to ``PyTopic``.

**Constructor**

.. code-block:: python

   Topic(topic_str: str) -> Topic

Parse a topic string into a structured topic.

**Examples:**

.. code-block:: python

   # Exact topic
   exact = Topic('Market.Data.AAPL')
   assert exact.is_exact == True

   # Wildcard topic
   pattern = Topic('Market.Data.{symbol}')
   assert pattern.is_exact == False

   # Range topic
   range_topic = Topic('Market.(Equity|Futures).Trade')

   # Pattern topic
   regex = Topic(r'Market.Data./^[A-Z]{4}$/')

**Properties**

- ``value: str`` - Full topic string
- ``is_exact: bool`` - True if all parts are exact (no wildcards/patterns)
- ``hash_value: int`` - Hash of the topic for fast comparison
- ``addr: int`` - Memory address of underlying C structure

**Methods**

- ``__len__() -> int`` - Number of topic parts
- ``__getitem__(index: int) -> TopicPart`` - Get part by index
- ``__iter__() -> Iterator[TopicPart]`` - Iterate over parts
- ``__eq__(other: Topic) -> bool`` - Equality comparison
- ``__hash__() -> int`` - Hash for use in dicts/sets
- ``__repr__() -> str`` - String representation

- ``match(other: Topic) -> TopicMatchResult`` - Match against another topic
- ``format(**kwargs) -> Topic`` - Replace wildcards with values
- ``append(part: TopicPart) -> Topic`` - Append a part (returns new topic)
- ``update_literal() -> Topic`` - Recalculate literal string after modification

**Class Methods**

- ``Topic.join(parts: Iterable[str]) -> Topic`` - Join strings with default separator
- ``Topic.from_parts(parts: Iterable[TopicPart]) -> Topic`` - Build from parts

TopicPart Classes
~~~~~~~~~~~~~~~~~

Base class for topic parts:

.. code-block:: python

   class TopicPart:
       @property
       def ttype(self) -> TopicType  # Type of this part

       @property
       def addr(self) -> int  # C memory address

Subclasses:

- ``TopicPartExact`` - Exact literal match

  - ``part: str`` - The literal string

- ``TopicPartAny`` - Wildcard match (``{name}``)

  - ``name: str`` - The wildcard name

- ``TopicPartRange`` - One of multiple options (``(opt1|opt2)``)

  - ``options() -> Iterator[str]`` - Iterate over options

- ``TopicPartPattern`` - Regex match (``/pattern/``)

  - ``pattern: str`` - The regex string
  - ``regex: re.Pattern`` - Compiled regex

TopicMatchResult
~~~~~~~~~~~~~~~~

Result of matching two topics:

.. code-block:: python

   result = pattern.match(exact_topic)

   if result.matched:  # All parts matched
       for node in result:
           print(node['part_a'], node['part_b'], node['literal'])

   # Convert to dict of matched values
   values = result.to_dict()  # {part_name: part_value}

**Properties**

- ``matched: bool`` - True if all parts matched
- ``length: int`` - Number of match nodes

**Methods**

- ``__len__() -> int`` - Number of nodes
- ``__getitem__(index: int) -> TopicMatchNode`` - Get node by index
- ``__iter__() -> Iterator[TopicMatchNode]`` - Iterate nodes
- ``__bool__() -> bool`` - Same as ``matched``
- ``to_dict() -> dict[str, TopicPart]`` - Convert to dict

TopicMatchNode TypedDict
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   class TopicMatchNode(TypedDict):
       matched: bool              # Did this node match?
       part_a: TopicPart | None   # Part from pattern topic
       part_b: TopicPart | None   # Part from target topic
       literal: str | None        # Matched literal value

Topic Helper Functions
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Initialize internal topic map
   init_internal_map(capacity: int = 1024) -> dict

   # Clear internal map
   clear_internal_map() -> None

   # Get topic from internal map
   get_internal_topic(key: str, owner: bool = False) -> Topic | None

   # Get all internalized topics
   get_internal_map() -> dict[str, Topic]

   # Initialize allocator (no-op in pure Python)
   init_allocator(capacity: int = 4096, with_shm: bool = False) -> None

Event Classes
-------------

MessagePayload
~~~~~~~~~~~~~~

Container for event data:

.. code-block:: python

   msg = MessagePayload(alloc=True)
   msg.topic = Topic('My.Topic')
   msg.args = (1, 2, 3)
   msg.kwargs = {'key': 'value'}
   msg.seq_id = 42

**Properties**

- ``topic: Topic`` - Associated topic
- ``args: tuple | None`` - Positional arguments
- ``kwargs: dict | None`` - Keyword arguments
- ``seq_id: int`` - Sequence ID

All properties are read-write. In the pure Python version, ``owner``, ``args_owner``, and ``kwargs_owner`` are always ``True``.

EventHook
~~~~~~~~~

Event dispatcher for a specific topic:

.. code-block:: python

   topic = Topic('App.Events')
   hook = EventHook(topic, logger=my_logger, retry_on_unexpected_topic=False)

   # Add handlers
   hook.add_handler(my_handler, deduplicate=True)
   hook += another_handler  # Operator shorthand

   # Trigger
   msg = MessagePayload(alloc=True)
   msg.topic = topic
   msg.args = (123,)
   hook.trigger(msg)

   # Remove handlers
   hook -= my_handler
   hook.clear()  # Remove all

**Constructor**

.. code-block:: python

   EventHook(topic: Topic,
             logger: Logger = None,
             retry_on_unexpected_topic: bool = False)

**Attributes**

- ``topic: Topic`` - Associated topic
- ``logger: Logger`` - Logger instance
- ``retry_on_unexpected_topic: bool`` - Retry without topic on TypeError

**Methods**

- ``trigger(msg: MessagePayload)`` - Dispatch to all handlers
- ``__call__(msg: MessagePayload)`` - Alias for ``trigger``
- ``add_handler(handler: Callable, deduplicate: bool = False)`` - Register handler
- ``remove_handler(handler: Callable) -> EventHook`` - Unregister handler
- ``__iadd__(handler: Callable) -> EventHook`` - ``hook += handler``
- ``__isub__(handler: Callable) -> EventHook`` - ``hook -= handler``
- ``__len__() -> int`` - Number of handlers
- ``__iter__() -> Iterator[Callable]`` - Iterate handlers
- ``__contains__(handler: Callable) -> bool`` - Check if handler registered
- ``clear()`` - Remove all handlers

**Properties**

- ``handlers: list[Callable]`` - All registered handlers (ordered: no-topic first, then with-topic)

EventHookEx
~~~~~~~~~~~

Extended hook with statistics tracking:

.. code-block:: python

   hook = EventHookEx(topic, logger=my_logger)

   # ... register and trigger ...

   # Get stats for a specific handler
   stats = hook.get_stats(my_handler)
   print(stats['calls'])       # Number of calls
   print(stats['total_time'])  # Total execution time in seconds

   # Iterate all stats
   for handler, stats in hook.stats:
       print(f"{handler.__name__}: {stats}")

**Additional Methods**

- ``get_stats(handler: Callable) -> HandlerStats | None`` - Get stats for handler
- ``stats: Iterator[tuple[Callable, HandlerStats]]`` - Iterate (handler, stats) pairs

**HandlerStats TypedDict**

.. code-block:: python

   class HandlerStats(TypedDict):
       calls: int          # Number of times called
       total_time: float   # Total execution time (seconds)

Engine Classes
--------------

EventEngine
~~~~~~~~~~~

Main event engine with message queue and routing:

.. code-block:: python

   engine = EventEngine(capacity=8192, logger=my_logger)

   # Register handlers
   topic = Topic('My.Topic')
   engine.register_handler(topic, my_handler)

   # Start event loop
   engine.start()

   # Publish messages
   engine.put(topic, 'arg1', 'arg2', key='value')

   # Stop and clean up
   engine.stop()
   engine.clear()

**Constructor**

.. code-block:: python

   EventEngine(capacity: int = 4095, logger: Logger = None)

**Attributes**

- ``capacity: int`` - Maximum queue size
- ``logger: Logger`` - Logger instance
- ``active: bool`` - Engine running state
- ``occupied: int`` - Current queue size

**Methods**

- ``start()`` - Start event loop in background thread
- ``stop()`` - Stop event loop and join thread
- ``run()`` - Run event loop in current thread (blocking)
- ``activate()`` - Mark engine as active (called by ``start()``)
- ``deactivate()`` - Mark engine as inactive (called by ``stop()``)
- ``clear()`` - Remove all hooks (must be stopped first)

- ``put(topic: Topic, *args, block: bool = True, max_spin: int = 65535, timeout: float = 0.0, **kwargs)``
  - Publish event (raises ``Full`` if queue full and non-blocking)

- ``publish(topic: Topic, args: tuple, kwargs: dict, block: bool = True, timeout: float = 0.0)``
  - Publish with explicit args/kwargs

- ``get(block: bool = True, max_spin: int = 65535, timeout: float = 0.0) -> MessagePayload``
  - Get message from queue (raises ``Empty`` if empty and non-blocking)

- ``register_hook(hook: EventHook)`` - Register an EventHook
- ``unregister_hook(topic: Topic) -> EventHook`` - Unregister and return hook
- ``register_handler(topic: Topic, handler: Callable, deduplicate: bool = False)`` - Register handler (creates hook if needed)
- ``unregister_handler(topic: Topic, handler: Callable)`` - Unregister handler

- ``__len__() -> int`` - Total number of registered topics

**Properties**

- ``exact_topic_hook_map: dict`` - Copy of exact topic hooks
- ``generic_topic_hook_map: dict`` - Copy of generic topic hooks

**Iterators**

- ``event_hooks()`` - Iterate all hooks
- ``topics()`` - Iterate all topics
- ``items()`` - Iterate (topic, hook) pairs

EventEngineEx
~~~~~~~~~~~~~

Extended engine with timer support:

.. code-block:: python

   engine = EventEngineEx(capacity=4096)
   engine.start()

   # Get a timer topic
   timer_topic = engine.get_timer(interval=1.0)
   engine.register_handler(timer_topic, on_timer)

   # Timer fires every 1 second

**Additional Methods**

- ``get_timer(interval: float, activate_time: datetime = None) -> Topic``
  - Get or create timer topic
  - Special intervals: ``1`` (second-aligned), ``60`` (minute-aligned)

- ``run_timer(interval: float, topic: Topic, activate_time: datetime = None)``
  - Run timer loop (blocking)

- ``second_timer(topic: Topic)`` - Second-aligned timer loop (blocking)
- ``minute_timer(topic: Topic)`` - Minute-aligned timer loop (blocking)

**Timer Behavior**

- Timers publish events with ``interval`` and ``trigger_time`` (or ``timestamp``) in kwargs
- Multiple calls to ``get_timer()`` with same interval return the same topic
- Timers stop when engine stops

Exceptions
----------

.. code-block:: python

   class Full(Exception):
       """Raised when queue is full and non-blocking put"""

   class Empty(Exception):
       """Raised when queue is empty and non-blocking get"""

Module Functions
----------------

.. code-block:: python

   # Check if using fallback
   from event_engine import USING_FALLBACK
   print(USING_FALLBACK)  # True if pure Python, False if Cython

   # Set logger
   from event_engine import set_logger
   import logging
   set_logger(logging.getLogger('MyApp'))

See Also
--------

- :doc:`examples` - Practical usage examples
- :doc:`capi_cython` - Lower-level Cython API
- :doc:`native_fallback` - Pure Python implementation details
- :doc:`api_reference` - Auto-generated API reference

