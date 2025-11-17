"""
Test the native Python fallback implementation of EventEngine and EventEngineEx.
"""

import sys
import time
sys.path.insert(0, '/home/bolun/Projects/PyEventEngine')

from event_engine.native.engine import EventEngine, EventEngineEx, Full, Empty
from event_engine.native.event import EventHook, PyMessagePayload
from event_engine.native.topic import PyTopic


def test_engine_basic():
    """Test basic EventEngine functionality."""
    print("Testing EventEngine basic functionality...")
    
    engine = EventEngine(capacity=10)
    print(f"  Created engine: {engine}")
    
    # Test __slots__
    try:
        engine.new_attr = 'should fail'
        print('  ✗ __slots__ not working!')
    except AttributeError:
        print('  ✓ __slots__ working correctly')
    
    # Test properties
    print(f"  ✓ Capacity: {engine.capacity}")
    print(f"  ✓ Occupied: {engine.occupied}")
    print(f"  ✓ Length (hooks): {len(engine)}")
    
    # Register a hook
    topic = PyTopic("Test.Event")
    hook = EventHook(topic)
    
    results = []
    def handler(x, topic=None):
        results.append((x, topic.value if topic else None))
    
    hook.add_handler(handler)
    engine.register_hook(hook)
    
    assert len(engine) == 1
    print(f"  ✓ Registered hook, engine length: {len(engine)}")
    
    # Publish a message
    engine.put(topic, 42)
    assert engine.occupied == 1
    print(f"  ✓ Published message, occupied: {engine.occupied}")
    
    # Get and process message
    msg = engine.get(block=False)
    assert msg.topic.value == topic.value
    assert msg.args == (42,)
    print(f"  ✓ Got message: {msg}")
    
    # Trigger it manually
    hook.trigger(msg)
    assert results == [(42, 'Test.Event')]
    print(f"  ✓ Handler triggered: {results}")
    
    # Test unregister
    unregistered_hook = engine.unregister_hook(topic)
    assert unregistered_hook is hook
    assert len(engine) == 0
    print("  ✓ Unregistered hook")
    
    print("✓ EventEngine basic tests passed!\n")


def test_engine_start_stop():
    """Test starting and stopping the engine."""
    print("Testing EventEngine start/stop...")
    
    engine = EventEngine(capacity=10)
    
    # Setup hook
    topic = PyTopic("Test.StartStop")
    results = []
    
    def handler(x, topic=None):
        results.append(x)
    
    engine.register_handler(topic, handler)
    
    # Start engine
    engine.start()
    time.sleep(0.1)  # Give it time to start
    assert engine.active
    print("  ✓ Engine started")
    
    # Publish message
    engine.put(topic, 123)
    time.sleep(0.1)  # Give it time to process
    
    assert 123 in results
    print(f"  ✓ Message processed: {results}")
    
    # Stop engine
    engine.stop()
    assert not engine.active
    print("  ✓ Engine stopped")
    
    # Clear
    engine.clear()
    assert len(engine) == 0
    print("  ✓ Engine cleared")
    
    print("✓ EventEngine start/stop tests passed!\n")


def test_engine_full_empty():
    """Test Full and Empty exceptions."""
    print("Testing Full and Empty exceptions...")
    
    engine = EventEngine(capacity=2)
    topic = PyTopic("Test.Capacity")
    
    # Fill the queue
    engine.put(topic, 1, block=False)
    engine.put(topic, 2, block=False)
    
    # Try to overflow
    try:
        engine.put(topic, 3, block=False)
        print("  ✗ Should have raised Full exception!")
    except Full:
        print("  ✓ Full exception raised correctly")
    
    # Empty the queue
    engine.get(block=False)
    engine.get(block=False)
    
    # Try to underflow
    try:
        engine.get(block=False)
        print("  ✗ Should have raised Empty exception!")
    except Empty:
        print("  ✓ Empty exception raised correctly")
    
    print("✓ Full/Empty exception tests passed!\n")


def test_engine_topic_matching():
    """Test exact and generic topic matching."""
    print("Testing topic matching...")
    
    engine = EventEngine(capacity=10)
    
    # Register exact topic
    exact_topic = PyTopic("Exact.Topic")
    exact_results = []
    
    def exact_handler(topic=None):
        exact_results.append('exact')
    
    engine.register_handler(exact_topic, exact_handler)
    
    # Register generic topic with wildcard
    generic_topic = PyTopic("Generic.{wildcard}")
    generic_results = []
    
    def generic_handler(topic=None):
        generic_results.append('generic')
    
    engine.register_handler(generic_topic, generic_handler)
    
    assert len(engine) == 2
    print(f"  ✓ Registered 2 hooks")
    
    # Start engine
    engine.start()
    time.sleep(0.1)
    
    # Publish to exact topic
    engine.put(exact_topic)
    time.sleep(0.1)
    assert 'exact' in exact_results
    print(f"  ✓ Exact topic matched: {exact_results}")
    
    # Publish to generic topic (formatted)
    formatted_topic = generic_topic.format(wildcard='Test')
    engine.put(formatted_topic)
    time.sleep(0.1)
    assert 'generic' in generic_results
    print(f"  ✓ Generic topic matched: {generic_results}")
    
    engine.stop()
    engine.clear()
    
    print("✓ Topic matching tests passed!\n")


def test_engine_ex_timers():
    """Test EventEngineEx timer functionality."""
    print("Testing EventEngineEx timers...")
    
    engine = EventEngineEx(capacity=10)
    
    # Start engine
    engine.start()
    time.sleep(0.1)
    
    # Get a timer
    timer_topic = engine.get_timer(0.1)  # 100ms timer
    print(f"  ✓ Created timer topic: {timer_topic.value}")
    
    # Register handler for timer
    timer_results = []
    
    def timer_handler(interval=None, trigger_time=None, **kwargs):
        timer_results.append(interval)
    
    engine.register_handler(timer_topic, timer_handler)
    
    # Wait for a few timer events
    time.sleep(0.35)
    
    # Should have triggered at least 2-3 times
    assert len(timer_results) >= 2
    print(f"  ✓ Timer triggered {len(timer_results)} times")
    
    # Stop engine
    engine.stop()
    engine.clear()
    
    print("✓ EventEngineEx timer tests passed!\n")


def test_engine_properties():
    """Test engine properties."""
    print("Testing engine properties...")
    
    engine = EventEngine(capacity=10)
    
    # Add hooks
    topic1 = PyTopic("Topic.One")
    topic2 = PyTopic("Topic.{wildcard}")
    
    engine.register_handler(topic1, lambda: None)
    engine.register_handler(topic2, lambda: None)
    
    # Test exact_topic_hook_map
    exact_map = engine.exact_topic_hook_map
    assert len(exact_map) == 1
    assert "Topic.One" in exact_map
    print(f"  ✓ Exact topic map: {list(exact_map.keys())}")
    
    # Test generic_topic_hook_map  
    generic_map = engine.generic_topic_hook_map
    assert len(generic_map) == 1
    print(f"  ✓ Generic topic map: {list(generic_map.keys())}")
    
    # Test iterators
    topics = list(engine.topics())
    assert len(topics) == 2
    print(f"  ✓ Topics iterator: {len(topics)} topics")
    
    hooks = list(engine.event_hooks())
    assert len(hooks) == 2
    print(f"  ✓ Hooks iterator: {len(hooks)} hooks")
    
    items = list(engine.items())
    assert len(items) == 2
    print(f"  ✓ Items iterator: {len(items)} items")
    
    print("✓ Engine properties tests passed!\n")


def test_engine_deduplicate():
    """Test handler deduplication."""
    print("Testing handler deduplication...")
    
    engine = EventEngine(capacity=10)
    topic = PyTopic("Test.Dedup")
    
    def handler():
        pass
    
    # Register without deduplicate
    engine.register_handler(topic, handler, deduplicate=False)
    engine.register_handler(topic, handler, deduplicate=False)
    
    hook = engine._exact_topic_hooks[topic.value]
    assert len(hook) == 2
    print("  ✓ Without deduplicate: 2 handlers")
    
    # Clear and register with deduplicate
    engine.clear()
    engine.register_handler(topic, handler, deduplicate=True)
    engine.register_handler(topic, handler, deduplicate=True)
    
    hook = engine._exact_topic_hooks[topic.value]
    assert len(hook) == 1
    print("  ✓ With deduplicate: 1 handler")
    
    print("✓ Deduplication tests passed!\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Native Python EventEngine Implementation")
    print("=" * 60)
    print()
    
    test_engine_basic()
    test_engine_start_stop()
    test_engine_full_empty()
    test_engine_topic_matching()
    test_engine_ex_timers()
    test_engine_properties()
    test_engine_deduplicate()
    
    print("=" * 60)
    print("ALL TESTS PASSED! ✓")
    print("=" * 60)

