"""
Test the native Python fallback implementation of PyTopic.
"""

import sys
sys.path.insert(0, '/home/bolun/Projects/PyEventEngine')

from event_engine.native.topic import (
    PyTopic,
    PyTopicPartExact,
    PyTopicPartAny,
    PyTopicPartRange,
    PyTopicPartPattern,
    PyTopicType,
    init_internal_map,
    clear_internal_map,
    get_internal_topic,
    get_internal_map,
    init_allocator,
)


def test_basic_topic():
    """Test basic topic creation and parsing."""
    print("Testing basic topic creation...")
    
    # Create a simple topic
    topic = PyTopic("Realtime.TickData.600010.SH")
    print(f"Topic: {topic}")
    print(f"Value: {topic.value}")
    print(f"Number of parts: {len(topic)}")
    print(f"Is exact: {topic.is_exact}")
    
    # Iterate over parts
    print("\nParts:")
    for i, part in enumerate(topic):
        print(f"  {i}: {part}")
    
    assert len(topic) == 4
    assert topic.is_exact
    assert topic.value == "Realtime.TickData.600010.SH"
    print("✓ Basic topic test passed!")


def test_wildcard_topic():
    """Test topic with wildcards."""
    print("\n\nTesting wildcard topic...")
    
    topic = PyTopic("Realtime.{datatype}.{ticker}")
    print(f"Topic: {topic}")
    print(f"Is exact: {topic.is_exact}")
    
    # Iterate over parts
    print("\nParts:")
    for i, part in enumerate(topic):
        print(f"  {i}: {part} (type: {part.ttype.name})")
    
    assert len(topic) == 3
    assert not topic.is_exact
    print("✓ Wildcard topic test passed!")


def test_range_topic():
    """Test topic with ranges."""
    print("\n\nTesting range topic...")
    
    topic = PyTopic("Realtime.(TickData|TradeData).600010.SH")
    print(f"Topic: {topic}")
    
    # Check parts
    print("\nParts:")
    for i, part in enumerate(topic):
        print(f"  {i}: {part} (type: {part.ttype.name})")
        if isinstance(part, PyTopicPartRange):
            print(f"     Options: {list(part.options())}")
    
    assert len(topic) == 4
    assert not topic.is_exact
    print("✓ Range topic test passed!")


def test_pattern_topic():
    """Test topic with regex patterns."""
    print("\n\nTesting pattern topic...")
    
    topic = PyTopic(r"Realtime.TickData./^[0-9]{6}$/.(SH|SZ)")
    print(f"Topic: {topic}")
    
    # Check parts
    print("\nParts:")
    for i, part in enumerate(topic):
        print(f"  {i}: {part} (type: {part.ttype.name})")
    
    assert len(topic) == 4
    assert not topic.is_exact
    print("✓ Pattern topic test passed!")


def test_topic_format():
    """Test topic formatting."""
    print("\n\nTesting topic formatting...")
    
    template = PyTopic("Realtime.{datatype}.{ticker}")
    print(f"Template: {template}")
    
    formatted = template.format(datatype="TickData", ticker="600010.SH")
    print(f"Formatted: {formatted}")
    print(f"Is exact: {formatted.is_exact}")
    
    assert formatted.value == "Realtime.TickData.600010.SH"
    assert formatted.is_exact
    print("✓ Topic formatting test passed!")


def test_topic_match():
    """Test topic matching."""
    print("\n\nTesting topic matching...")
    
    pattern = PyTopic("Realtime.{datatype}.600010.SH")
    exact = PyTopic("Realtime.TickData.600010.SH")
    
    print(f"Pattern: {pattern}")
    print(f"Exact: {exact}")
    
    result = pattern.match(exact)
    print(f"Match result: {result}")
    print(f"Matched: {result.matched}")
    
    # Check individual matches
    print("\nMatch details:")
    for i, node in enumerate(result):
        print(f"  Part {i}: matched={node['matched']}, literal={node['literal']}")
    
    assert result.matched
    assert len(result) == 4
    print("✓ Topic matching test passed!")


def test_topic_join():
    """Test PyTopic.join() method."""
    print("\n\nTesting PyTopic.join()...")
    
    topic = PyTopic.join(["Realtime", "TickData", "600010.SH"])
    print(f"Joined topic: {topic}")
    
    assert topic.value == "Realtime.TickData.600010.SH"
    assert topic.is_exact
    assert len(topic) == 3
    print("✓ PyTopic.join() test passed!")


def test_topic_from_parts():
    """Test PyTopic.from_parts() method."""
    print("\n\nTesting PyTopic.from_parts()...")
    
    parts = [
        PyTopicPartExact("Realtime", alloc=True),
        PyTopicPartAny("datatype", alloc=True),
        PyTopicPartExact("600010.SH", alloc=True),
    ]
    
    topic = PyTopic.from_parts(parts)
    print(f"Topic from parts: {topic}")
    
    assert len(topic) == 3
    assert not topic.is_exact
    print("✓ PyTopic.from_parts() test passed!")


def test_internal_map():
    """Test internal map functions."""
    print("\n\nTesting internal map...")
    
    # Initialize map (dummy in Python)
    init_allocator()
    internal_map = init_internal_map()
    print(f"Internal map type: {type(internal_map)}")
    
    # Create a topic (should be internalized)
    topic1 = PyTopic("Test.Topic.One")
    
    # Get it back from internal map
    topic2 = get_internal_topic("Test.Topic.One")
    print(f"Retrieved topic: {topic2}")
    
    assert topic2 is not None
    assert topic2.value == "Test.Topic.One"
    
    # Get all internal topics
    all_topics = get_internal_map()
    print(f"Number of internalized topics: {len(all_topics)}")
    
    # Clear map
    clear_internal_map()
    all_topics_after = get_internal_map()
    print(f"After clear: {len(all_topics_after)} topics")
    
    print("✓ Internal map test passed!")


def test_topic_operations():
    """Test topic addition operations."""
    print("\n\nTesting topic operations...")
    
    topic1 = PyTopic("Realtime.TickData")
    topic2 = PyTopic("600010.SH")
    
    # Test __add__
    combined = topic1 + topic2
    print(f"Combined: {combined}")
    assert combined.value == "Realtime.TickData.600010.SH"
    
    # Test __iadd__
    topic3 = PyTopic("Realtime")
    topic3 += PyTopicPartExact("TickData", alloc=True)
    print(f"After +=: {topic3}")
    assert len(topic3) == 2
    
    print("✓ Topic operations test passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Native Python PyTopic Implementation")
    print("=" * 60)
    
    test_basic_topic()
    test_wildcard_topic()
    test_range_topic()
    test_pattern_topic()
    test_topic_format()
    test_topic_match()
    test_topic_join()
    test_topic_from_parts()
    test_internal_map()
    test_topic_operations()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED! ✓")
    print("=" * 60)

