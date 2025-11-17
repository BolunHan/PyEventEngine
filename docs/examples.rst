Examples
========

This page provides practical examples of using PyEventEngine.

Basic Usage
-----------

Creating and Starting an Engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from event_engine import EventEngine, Topic

   # Create engine with queue capacity of 8192 messages
   engine = EventEngine(capacity=8192)

   # Start the event loop in a background thread
   engine.start()

   # ... use the engine ...

   # Clean shutdown
   engine.stop()
   engine.clear()

Simple Publish/Subscribe
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from event_engine import EventEngine, Topic

   engine = EventEngine()
   engine.start()

   # Define a handler
   def on_message(text: str, topic=None):
       print(f"Received: {text} on {topic.value if topic else 'unknown'}")

   # Register handler for exact topic
   topic = Topic('App.Messages')
   engine.register_handler(topic, on_message)

   # Publish a message
   engine.put(topic, 'Hello, World!')

   import time
   time.sleep(0.1)  # Give handler time to process

   engine.stop()

Topic Patterns
--------------

Wildcard Topics
~~~~~~~~~~~~~~~

Use ``{name}`` syntax for named wildcards:

.. code-block:: python

   from event_engine import EventEngine, Topic

   engine = EventEngine()
   engine.start()

   # Register handler for wildcard topic
   pattern = Topic('Market.Data.{symbol}')

   results = []
   def on_tick(price: float, symbol: str, topic=None):
       results.append((symbol, price))

   engine.register_handler(pattern, on_tick)

   # Publish to specific topics (they match the pattern)
   engine.put(Topic('Market.Data.AAPL'), 150.25, symbol='AAPL')
   engine.put(Topic('Market.Data.TSLA'), 680.50, symbol='TSLA')

   import time
   time.sleep(0.1)

   print(results)  # [('AAPL', 150.25), ('TSLA', 680.50)]

   engine.stop()

Range Topics
~~~~~~~~~~~~

Use ``(option1|option2|...)`` for multiple choices:

.. code-block:: python

   from event_engine import Topic

   # This topic matches either Equity or Futures
   topic = Topic('Market.(Equity|Futures).Trade')

   engine.register_handler(topic, lambda **kw: print(f"Trade: {kw}"))

   engine.start()
   engine.put(Topic('Market.Equity.Trade'), symbol='AAPL')
   engine.put(Topic('Market.Futures.Trade'), symbol='ES')
   # Does NOT match:
   # engine.put(Topic('Market.Options.Trade'), symbol='AAPL')

   import time
   time.sleep(0.1)
   engine.stop()

Pattern Topics (Regex)
~~~~~~~~~~~~~~~~~~~~~~

Use ``/regex/`` for complex matching:

.. code-block:: python

   from event_engine import Topic

   # Match 4-letter stock symbols
   pattern = Topic(r'Market.Data./^[A-Z]{4}$/')

   engine.register_handler(pattern, lambda symbol, **kw: print(f"Symbol: {symbol}"))

   engine.start()
   engine.put(Topic('Market.Data.AAPL'), symbol='AAPL')  # Matches
   engine.put(Topic('Market.Data.TSLA'), symbol='TSLA')  # Matches
   engine.put(Topic('Market.Data.A'), symbol='A')        # Does NOT match (too short)

   import time
   time.sleep(0.1)
   engine.stop()

Topic Formatting
~~~~~~~~~~~~~~~~

Format topics with wildcards by providing values:

.. code-block:: python

   from event_engine import Topic

   template = Topic('Market.{market}.{symbol}')

   # Format the template
   specific = template.format(market='Equity', symbol='AAPL')
   print(specific.value)  # 'Market.Equity.AAPL'
   print(specific.is_exact)  # True

   # Or use call syntax
   specific2 = template(market='Futures', symbol='ES')
   print(specific2.value)  # 'Market.Futures.ES'

Event Hooks
-----------

Direct Hook Registration
~~~~~~~~~~~~~~~~~~~~~~~~~

For more control, register ``EventHook`` objects directly:

.. code-block:: python

   from event_engine import EventEngine, EventHook, Topic

   engine = EventEngine()

   # Create a hook
   topic = Topic('App.Events')
   hook = EventHook(topic)

   # Add handlers to the hook
   hook.add_handler(lambda msg: print(f"Handler 1: {msg}"))
   hook.add_handler(lambda msg: print(f"Handler 2: {msg}"))

   # Register the hook with the engine
   engine.register_hook(hook)

   engine.start()
   engine.put(topic, 'Test message')

   import time
   time.sleep(0.1)
   engine.stop()

Handler with Statistics
~~~~~~~~~~~~~~~~~~~~~~~

Use ``EventHookEx`` to track execution stats:

.. code-block:: python

   from event_engine import EventHookEx, Topic

   topic = Topic('Perf.Test')
   hook = EventHookEx(topic)

   def slow_handler(x):
       import time
       time.sleep(0.01)  # Simulate work
       return x * 2

   hook.add_handler(slow_handler)

   # Trigger multiple times
   from event_engine import PyMessagePayload
   for i in range(10):
       msg = PyMessagePayload(alloc=True)
       msg.topic = topic
       msg.args = (i,)
       hook.trigger(msg)

   # Check stats
   stats = hook.get_stats(slow_handler)
   print(f"Calls: {stats['calls']}")
   print(f"Total time: {stats['total_time']:.4f}s")

Timers
------

Using Built-in Timers (EventEngineEx)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from event_engine import EventEngine, EventEngineEx

   # Use EventEngineEx for timer support
   engine = EventEngineEx(capacity=4096)
   engine.start()

   # Get a 1-second timer
   timer_topic = engine.get_timer(interval=1.0)

   tick_count = [0]
   def on_tick(interval, trigger_time, **kwargs):
       tick_count[0] += 1
       print(f"Tick #{tick_count[0]} at {trigger_time}")

   engine.register_handler(timer_topic, on_tick)

   # Let it run for a few seconds
   import time
   time.sleep(3.5)

   print(f"Total ticks: {tick_count[0]}")  # Should be ~3

   engine.stop()

Minute and Second Timers
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from event_engine import EventEngineEx

   engine = EventEngineEx()
   engine.start()

   # Second-aligned timer (fires exactly on the second)
   sec_timer = engine.get_timer(interval=1)
   engine.register_handler(sec_timer, lambda **kw: print(f"Second: {kw['timestamp']}"))

   # Minute-aligned timer (fires exactly on the minute)
   min_timer = engine.get_timer(interval=60)
   engine.register_handler(min_timer, lambda **kw: print(f"Minute: {kw['timestamp']}"))

   import time
   time.sleep(65)  # Wait for at least one minute tick

   engine.stop()

Advanced Usage
--------------

Multiple Handlers per Topic
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from event_engine import EventEngine, Topic

   engine = EventEngine()
   topic = Topic('Multi.Handler')

   # Register multiple handlers
   engine.register_handler(topic, lambda x: print(f"Handler A: {x}"))
   engine.register_handler(topic, lambda x: print(f"Handler B: {x}"))
   engine.register_handler(topic, lambda x: print(f"Handler C: {x}"))

   engine.start()
   engine.put(topic, 'broadcast')
   # All three handlers will be called

   import time
   time.sleep(0.1)
   engine.stop()

Deduplication
~~~~~~~~~~~~~

Prevent registering the same handler multiple times:

.. code-block:: python

   from event_engine import EventEngine, Topic

   engine = EventEngine()
   topic = Topic('Dedupe.Test')

   def my_handler(x):
       print(x)

   # Without deduplication
   engine.register_handler(topic, my_handler, deduplicate=False)
   engine.register_handler(topic, my_handler, deduplicate=False)
   # Handler is registered twice

   # With deduplication
   engine.register_handler(topic, my_handler, deduplicate=True)
   engine.register_handler(topic, my_handler, deduplicate=True)
   # Handler is only registered once

Custom Logging
~~~~~~~~~~~~~~

Integrate with your application's logger:

.. code-block:: python

   import logging
   from event_engine import set_logger

   # Create your logger
   logger = logging.getLogger('MyApp')
   logger.setLevel(logging.DEBUG)

   handler = logging.StreamHandler()
   handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(message)s'))
   logger.addHandler(handler)

   # Tell PyEventEngine to use it
   set_logger(logger)

   # Now all PyEventEngine logs go through your logger
   from event_engine import EventEngine
   engine = EventEngine()
   engine.start()  # Will log via your logger
   engine.stop()

Performance Testing
-------------------

Basic Throughput Test
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import time
   import threading
   from event_engine import EventEngine, Topic

   engine = EventEngine(capacity=8192)
   topic = Topic('Perf.Test')

   received = []
   done = threading.Event()

   def handler(msg_id: int):
       received.append(msg_id)
       if msg_id >= 99999:
           done.set()

   engine.register_handler(topic, handler)
   engine.start()

   # Send 100k messages
   start = time.perf_counter()
   for i in range(100_000):
       engine.put(topic, i)

   # Wait for all processed
   done.wait(timeout=10)
   elapsed = time.perf_counter() - start

   print(f"Throughput: {len(received) / elapsed:.0f} msg/s")
   print(f"Latency: {elapsed / len(received) * 1000:.3f} ms/msg")

   engine.stop()

Latency Measurement
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import time
   from event_engine import EventEngine, Topic

   engine = EventEngine()
   topic = Topic('Latency.Test')

   latencies = []

   def handler(send_time: float):
       latency = time.perf_counter() - send_time
       latencies.append(latency * 1000)  # Convert to ms

   engine.register_handler(topic, handler)
   engine.start()

   # Send 1000 messages with timestamps
   for _ in range(1000):
       engine.put(topic, time.perf_counter())
       time.sleep(0.001)  # 1ms between sends

   time.sleep(0.5)  # Let queue drain
   engine.stop()

   # Calculate statistics
   latencies.sort()
   print(f"Min: {latencies[0]:.3f} ms")
   print(f"P50: {latencies[len(latencies)//2]:.3f} ms")
   print(f"P95: {latencies[int(len(latencies)*0.95)]:.3f} ms")
   print(f"Max: {latencies[-1]:.3f} ms")

See Also
--------

- :doc:`api_reference` for complete API documentation
- ``demo/`` folder in the repository for more examples
- ``demo/native_performance_test.py`` for comprehensive performance tests
- ``demo/capi_performance_test.py`` for Cython performance comparison

