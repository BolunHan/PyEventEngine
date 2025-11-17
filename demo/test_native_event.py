"""
Test the native Python fallback implementation of PyMessagePayload and EventHook.
"""

import sys
sys.path.insert(0, '/home/bolun/Projects/PyEventEngine')

from event_engine.native.event import PyMessagePayload, EventHook, EventHookEx
from event_engine.native.topic import PyTopic


def test_message_payload():
    """Test PyMessagePayload creation and properties."""
    print("Testing PyMessagePayload...")
    
    # Create a payload
    msg = PyMessagePayload(alloc=True)
    print(f"Created payload: {msg}")
    
    # Test owner properties
    assert msg.owner == True
    assert msg.args_owner == True
    assert msg.kwargs_owner == True
    print(f"  ✓ Owner properties: owner={msg.owner}, args_owner={msg.args_owner}, kwargs_owner={msg.kwargs_owner}")
    
    # Test __slots__
    try:
        msg.new_attr = 'should fail'
        print('  ✗ __slots__ not working!')
    except AttributeError:
        print('  ✓ __slots__ working correctly')
    
    # Set topic
    topic = PyTopic("Test.Topic.One")
    msg.topic = topic
    print(f"  ✓ Set topic: {msg.topic.value}")
    
    # Set args and kwargs
    msg.args = (1, 2, 3)
    msg.kwargs = {'key': 'value'}
    msg.seq_id = 42
    print(f"  ✓ Set args: {msg.args}")
    print(f"  ✓ Set kwargs: {msg.kwargs}")
    print(f"  ✓ Set seq_id: {msg.seq_id}")
    
    # Test repr
    print(f"  Repr: {repr(msg)}")
    
    print("✓ PyMessagePayload tests passed!\n")


def test_event_hook_basic():
    """Test basic EventHook functionality."""
    print("Testing EventHook basic functionality...")
    
    topic = PyTopic("Test.Event.Hook")
    hook = EventHook(topic)
    
    # Test __slots__
    try:
        hook.new_attr = 'should fail'
        print('  ✗ __slots__ not working!')
    except AttributeError:
        print('  ✓ __slots__ working correctly')
    
    # Test length
    assert len(hook) == 0
    print(f"  ✓ Initial length: {len(hook)}")
    
    # Add handlers
    call_log = []
    
    def handler_no_topic(x, y):
        call_log.append(('no_topic', x, y))
    
    def handler_with_topic(x, y, topic=None):
        call_log.append(('with_topic', topic.value if topic else None, x, y))

    def handler_kwargs(x, y, **kwargs):
        call_log.append(('kwargs', kwargs))
    
    hook.add_handler(handler_no_topic)
    hook.add_handler(handler_with_topic)
    hook.add_handler(handler_kwargs)
    
    print(f"  ✓ Added 3 handlers, length: {len(hook)}")
    
    # Test __contains__
    assert handler_no_topic in hook
    assert handler_with_topic in hook
    print("  ✓ __contains__ works")
    
    # Test __iter__
    handlers_list = list(hook)
    assert len(handlers_list) == 3
    print(f"  ✓ __iter__ works, got {len(handlers_list)} handlers")
    
    # Trigger the hook
    msg = PyMessagePayload(alloc=True)
    msg.topic = topic
    msg.args = (10, 20)
    msg.kwargs = {}
    
    hook.trigger(msg)
    
    print(f"  ✓ Triggered hook, call_log: {call_log}")
    assert len(call_log) == 3
    assert call_log[0] == ('no_topic', 10, 20)
    assert call_log[1] == ('with_topic', 'Test.Event.Hook', 10, 20)
    assert 'topic' in call_log[2][1]
    
    # Test += operator
    call_log.clear()
    def new_handler(a):
        call_log.append(('new', a))
    
    hook += new_handler
    assert len(hook) == 4
    print("  ✓ += operator works")
    
    # Test -= operator
    hook -= new_handler
    assert len(hook) == 3
    print("  ✓ -= operator works")
    
    # Test clear
    hook.clear()
    assert len(hook) == 0
    print("  ✓ clear() works")
    
    print("✓ EventHook basic tests passed!\n")


def test_event_hook_retry():
    """Test EventHook retry_on_unexpected_topic feature."""
    print("Testing EventHook retry_on_unexpected_topic...")
    
    topic = PyTopic("Test.Retry")
    hook = EventHook(topic, retry_on_unexpected_topic=True)
    
    call_log = []
    
    # This handler doesn't accept topic, but we'll call it with topic
    def handler_no_topic_param(x):
        call_log.append(('called', x))
    
    # Manually add to with_topic list to simulate the retry scenario
    hook._handlers_with_topic.append(handler_no_topic_param)
    
    msg = PyMessagePayload(alloc=True)
    msg.topic = topic
    msg.args = (42,)
    msg.kwargs = {}
    
    hook.trigger(msg)
    
    # Should have been called (retry mechanism)
    print(f"  Call log: {call_log}")
    assert len(call_log) == 1
    print("  ✓ Retry mechanism works")
    
    print("✓ EventHook retry tests passed!\n")


def test_event_hook_ex():
    """Test EventHookEx with statistics."""
    print("Testing EventHookEx...")
    
    topic = PyTopic("Test.Stats")
    hook = EventHookEx(topic)
    
    call_count = []
    
    def handler1(x):
        call_count.append(1)
    
    def handler2(x, topic=None):
        call_count.append(2)
    
    hook.add_handler(handler1)
    hook.add_handler(handler2)
    
    # Trigger multiple times
    for i in range(5):
        msg = PyMessagePayload(alloc=True)
        msg.topic = topic
        msg.args = (i,)
        msg.kwargs = {}
        hook.trigger(msg)
    
    print(f"  ✓ Triggered 5 times, call_count: {len(call_count)}")
    assert len(call_count) == 10  # 2 handlers * 5 calls
    
    # Check stats
    stats1 = hook.get_stats(handler1)
    stats2 = hook.get_stats(handler2)
    
    assert stats1 is not None
    assert stats2 is not None
    assert stats1['calls'] == 5
    assert stats2['calls'] == 5
    assert stats1['total_time'] > 0
    assert stats2['total_time'] > 0
    
    print(f"  ✓ handler1 stats: calls={stats1['calls']}, time={stats1['total_time']:.6f}s")
    print(f"  ✓ handler2 stats: calls={stats2['calls']}, time={stats2['total_time']:.6f}s")
    
    # Test stats iterator
    stats_list = list(hook.stats)
    assert len(stats_list) == 2
    print(f"  ✓ Stats iterator works, got {len(stats_list)} entries")
    
    # Test clear
    hook.clear()
    assert len(hook) == 0
    stats1_after = hook.get_stats(handler1)
    assert stats1_after is None
    print("  ✓ clear() removes handlers and stats")
    
    print("✓ EventHookEx tests passed!\n")


def test_handlers_property():
    """Test the handlers property."""
    print("Testing handlers property...")
    
    topic = PyTopic("Test.Handlers")
    hook = EventHook(topic)
    
    def h1(x): pass
    def h2(topic, x): pass
    def h3(**kwargs): pass
    
    hook.add_handler(h1)
    hook.add_handler(h2)
    hook.add_handler(h3)
    
    handlers = hook.handlers
    assert len(handlers) == 3
    assert h1 in handlers
    assert h2 in handlers
    assert h3 in handlers
    print(f"  ✓ handlers property returns all {len(handlers)} handlers")
    
    print("✓ handlers property test passed!\n")


def test_deduplicate():
    """Test deduplicate feature."""
    print("Testing deduplicate feature...")
    
    topic = PyTopic("Test.Dedup")
    hook = EventHook(topic)
    
    def handler(x): pass
    
    hook.add_handler(handler, deduplicate=False)
    hook.add_handler(handler, deduplicate=False)
    assert len(hook) == 2
    print("  ✓ Without deduplicate: 2 handlers")
    
    hook.clear()
    hook.add_handler(handler, deduplicate=True)
    hook.add_handler(handler, deduplicate=True)
    assert len(hook) == 1
    print("  ✓ With deduplicate: 1 handler")
    
    print("✓ deduplicate test passed!\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Native Python Event Implementation")
    print("=" * 60)
    print()
    
    test_message_payload()
    test_event_hook_basic()
    test_event_hook_retry()
    test_event_hook_ex()
    test_handlers_property()
    test_deduplicate()
    
    print("=" * 60)
    print("ALL TESTS PASSED! ✓")
    print("=" * 60)

