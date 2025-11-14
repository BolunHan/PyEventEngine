"""
Test script for fallback_engine.py to verify cross-platform compatibility.
"""
from event_engine.capi.fallback_engine import EventEngine, EventEngineEx, Full, Empty
from event_engine.capi.c_topic import PyTopic
from event_engine.capi.c_event import EventHook


def test_basic_engine():
    """Test basic EventEngine functionality."""
    print("Testing basic EventEngine...")
    # Create engine
    engine = EventEngine(capacity=100)
    print(f"Created: {engine}")
    # Create topics
    topic1 = PyTopic("test.topic.one")
    topic2 = PyTopic("test.topic.two")
    # Register handlers
    results = []

    def handler1(*args, **kwargs):
        results.append(('handler1', args, kwargs))
        print(f"Handler1 called: args={args}, kwargs={kwargs}")

    def handler2(*args, **kwargs):
        results.append(('handler2', args, kwargs))
        print(f"Handler2 called: args={args}, kwargs={kwargs}")

    engine.register_handler(topic1, handler1)
    engine.register_handler(topic2, handler2)
    print(f"Registered handlers. Total hooks: {len(engine)}")
    # Start engine
    engine.start()
    # Publish messages
    engine.put(topic1, 1, 2, 3, key1="value1")
    engine.put(topic2, "hello", key2="world")
    print("Published 2 messages")
    # Wait a bit for processing
    import time
    time.sleep(0.5)
    # Stop engine
    engine.stop()
    print(f"Results: {results}")
    assert len(results) == 2
    assert results[0][0] == 'handler1'
    assert results[1][0] == 'handler2'
    print("✓ Basic engine test passed!")


def test_get_put():
    """Test get/put operations."""
    print("\nTesting get/put operations...")
    engine = EventEngine(capacity=10)
    topic = PyTopic("test.message")
    # Test put without starting engine
    engine.put(topic, "arg1", "arg2", kwarg1="value1")
    print(f"Queue occupied: {engine.occupied}")
    assert engine.occupied == 1
    # Test get
    msg = engine.get(block=False)
    print(f"Got message: {msg}")
    assert msg.topic.value == "test.message"
    assert msg.args == ("arg1", "arg2")
    assert msg.kwargs == {"kwarg1": "value1"}
    # Test empty exception
    try:
        engine.get(block=False)
        assert False, "Should raise Empty"
    except Empty:
        print("✓ Empty exception raised correctly")
    # Test full exception
    for i in range(11):
        try:
            engine.put(topic, i, block=False)
        except Full:
            print(f"✓ Full exception raised at message {i}")
            break
    print("✓ Get/put test passed!")


def test_wildcard_topic():
    """Test wildcard topic matching."""
    print("\nTesting wildcard topic matching...")
    engine = EventEngine()
    # Create a wildcard topic pattern
    pattern_topic = PyTopic("test.{category}.data")
    exact_topic1 = PyTopic("test.stock.data")
    exact_topic2 = PyTopic("test.forex.data")
    exact_topic3 = PyTopic("test.crypto.info")  # Should not match
    results = []

    def wildcard_handler(*args, **kwargs):
        results.append(kwargs.get('value', 'unknown'))
        print(f"Wildcard handler: {kwargs}")

    engine.register_handler(pattern_topic, wildcard_handler)
    engine.start()
    # Publish messages
    engine.put(exact_topic1, value="stock_data")
    engine.put(exact_topic2, value="forex_data")
    engine.put(exact_topic3, value="crypto_info")  # Should not trigger handler
    import time
    time.sleep(0.5)
    engine.stop()
    print(f"Results: {results}")
    assert len(results) == 2  # Only first two should match
    assert "stock_data" in results
    assert "forex_data" in results
    print("✓ Wildcard topic test passed!")


def test_engine_ex_timers():
    """Test EventEngineEx timer functionality."""
    print("\nTesting EventEngineEx timers...")
    engine = EventEngineEx(capacity=100)
    timer_results = []

    def timer_handler(*args, **kwargs):
        timer_results.append(kwargs.get('interval'))
        print(f"Timer triggered: {kwargs}")

    engine.start()
    # Get a 0.5 second timer
    timer_topic = engine.get_timer(0.5)
    engine.register_handler(timer_topic, timer_handler)
    print("Waiting for timer events...")
    import time
    time.sleep(1.5)  # Should get 3 timer events
    engine.stop()
    print(f"Timer events received: {len(timer_results)}")
    assert len(timer_results) >= 2  # At least 2 timer events
    print("✓ EventEngineEx timer test passed!")


def test_hook_operations():
    """Test EventHook operations."""
    print("\nTesting EventHook operations...")
    engine = EventEngine()
    topic = PyTopic("test.hook")
    # Create hook manually
    hook = EventHook(topic)
    handler_calls = []

    def handler(*args, **kwargs):
        handler_calls.append(True)

    # Add handler to hook
    hook.add_handler(handler)
    # Register hook to engine
    engine.register_hook(hook)
    engine.start()
    engine.put(topic, test="value")
    import time
    time.sleep(0.3)
    engine.stop()
    assert len(handler_calls) == 1
    print("✓ Hook operations test passed!")


def test_publish_method():
    """Test the publish method with explicit args/kwargs."""
    print("\nTesting publish method...")
    engine = EventEngine()
    topic = PyTopic("test.publish")
    results = []

    def handler(*args, **kwargs):
        results.append((args, kwargs))
        print(f"Handler called: args={args}, kwargs={kwargs}")

    engine.register_handler(topic, handler)
    engine.start()
    # Use publish method
    engine.publish(topic, ("arg1", "arg2"), {"key": "value"})
    import time
    time.sleep(0.3)
    engine.stop()
    assert len(results) == 1
    assert results[0][0] == ("arg1", "arg2")
    assert results[0][1] == {"key": "value", 'topic': topic}
    print("✓ Publish method test passed!")


def test_multiple_handlers_same_topic():
    """Test multiple handlers on the same topic."""
    print("\nTesting multiple handlers on same topic...")
    engine = EventEngine()
    topic = PyTopic("test.multi")
    calls = []

    def handler1(*args, **kwargs):
        calls.append("handler1")

    def handler2(*args, **kwargs):
        calls.append("handler2")

    def handler3(*args, **kwargs):
        calls.append("handler3")

    engine.register_handler(topic, handler1)
    engine.register_handler(topic, handler2)
    engine.register_handler(topic, handler3)
    engine.start()
    engine.put(topic, test="value")
    import time
    time.sleep(0.3)
    engine.stop()
    assert len(calls) == 3
    assert "handler1" in calls
    assert "handler2" in calls
    assert "handler3" in calls
    print("✓ Multiple handlers test passed!")


def test_unregister_handler():
    """Test unregistering handlers."""
    print("\nTesting unregister handler...")
    engine = EventEngine()
    topic = PyTopic("test.unregister")
    calls = []

    def handler1(*args, **kwargs):
        calls.append("handler1")

    def handler2(*args, **kwargs):
        calls.append("handler2")

    engine.register_handler(topic, handler1)
    engine.register_handler(topic, handler2)
    # Unregister handler1
    engine.unregister_handler(topic, handler1)
    engine.start()
    engine.put(topic, test="value")
    import time
    time.sleep(0.3)
    engine.stop()
    # Only handler2 should have been called
    assert len(calls) == 1
    assert calls[0] == "handler2"
    print("✓ Unregister handler test passed!")


def test_clear():
    """Test clearing all hooks."""
    print("\nTesting clear...")
    engine = EventEngine()
    topic1 = PyTopic("test.clear.one")
    topic2 = PyTopic("test.clear.two")

    def handler(*args, **kwargs):
        pass

    engine.register_handler(topic1, handler)
    engine.register_handler(topic2, handler)
    assert len(engine) == 2
    engine.clear()
    assert len(engine) == 0
    print("✓ Clear test passed!")


def test_iter_methods():
    """Test iteration methods."""
    print("\nTesting iteration methods...")
    engine = EventEngine()
    topic1 = PyTopic("test.iter.one")
    topic2 = PyTopic("test.iter.two")
    topic3 = PyTopic("test.iter.{wildcard}")

    def handler(*args, **kwargs):
        pass

    engine.register_handler(topic1, handler)
    engine.register_handler(topic2, handler)
    engine.register_handler(topic3, handler)
    # Test topics()
    topics = list(engine.topics())
    assert len(topics) == 3
    # Test event_hooks()
    hooks = list(engine.event_hooks())
    assert len(hooks) == 3
    # Test items()
    items = list(engine.items())
    assert len(items) == 3
    print("✓ Iteration methods test passed!")


def test_second_timer():
    """Test second-aligned timer."""
    print("\nTesting second timer...")
    engine = EventEngineEx()
    timer_results = []

    def timer_handler(*args, **kwargs):
        timer_results.append(kwargs.get('timestamp'))
        print(f"Second timer: {kwargs}")

    engine.start()
    timer_topic = engine.get_timer(1)
    engine.register_handler(timer_topic, timer_handler)
    import time
    time.sleep(2.5)
    engine.stop()
    print(f"Second timer events: {len(timer_results)}")
    assert len(timer_results) >= 2
    print("✓ Second timer test passed!")


def test_minute_timer():
    """Test minute-aligned timer (quick test)."""
    print("\nTesting minute timer (quick)...")
    # This would take too long in real tests, just verify setup
    engine = EventEngineEx()
    engine.start()
    # Just verify the timer can be created
    timer_topic = engine.get_timer(60)
    assert timer_topic.value == "EventEngine.Internal.Timer.Minute"
    engine.stop()
    print("✓ Minute timer setup test passed!")


if __name__ == '__main__':
    test_basic_engine()
    test_get_put()
    test_wildcard_topic()
    test_engine_ex_timers()
    test_hook_operations()
    test_publish_method()
    test_multiple_handlers_same_topic()
    test_unregister_handler()
    test_clear()
    test_iter_methods()
    test_second_timer()
    test_minute_timer()
    print("\n" + "=" * 50)
    print("All tests passed! ✓")
    print("=" * 50)
