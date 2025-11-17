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


def test_format_map_strict_true():
    """Test format_map with strict=True."""
    print("\n\nTesting format_map with strict=True...")

    # Test with all keys present
    template = PyTopic("realtime.{ticker}.{dtype}")
    formatted = template.format_map({'ticker': '600010.SH', 'dtype': 'TickData'}, strict=True)
    print(f"Template: {template}")
    print(f"Formatted (all keys): {formatted}")
    assert formatted.value == "realtime.600010.SH.TickData"
    assert formatted.is_exact

    # Test with missing key - should raise KeyError
    try:
        formatted = template.format_map({'ticker': '600010.SH'}, strict=True)
        assert False, "Should have raised KeyError"
    except KeyError as e:
        print(f"Expected KeyError raised: {e}")
        assert str(e) == "'dtype'"

    print("✓ format_map strict=True test passed!")


def test_format_map_strict_false():
    """Test format_map with strict=False (keeps unmatched wildcards)."""
    print("\n\nTesting format_map with strict=False...")

    # Test with all keys present
    template = PyTopic("realtime.{ticker}.{dtype}")
    formatted = template.format_map({'ticker': '600010.SH', 'dtype': 'TickData'}, strict=False)
    print(f"Template: {template}")
    print(f"Formatted (all keys): {formatted}")
    assert formatted.value == "realtime.600010.SH.TickData"
    assert formatted.is_exact

    # Test with missing key - should keep wildcard
    formatted = template.format_map({'ticker': '600010.SH'}, strict=False)
    print(f"Formatted (missing dtype): {formatted}")
    assert formatted.value == "realtime.600010.SH.{dtype}"
    assert not formatted.is_exact  # Still has a wildcard
    assert formatted.match(PyTopic.join(["realtime", "600010.SH", "TickData"]))

    # Check parts
    parts = list(formatted)
    print(f"Number of parts: {len(parts)}")
    for i, part in enumerate(parts):
        print(f"  Part {i}: {part}")

    assert len(parts) == 3
    assert isinstance(parts[0], PyTopicPartExact)
    assert parts[0].part == "realtime"
    assert isinstance(parts[1], PyTopicPartExact)
    assert parts[1].part == "600010.SH"
    assert isinstance(parts[2], PyTopicPartAny)
    assert parts[2].name == "dtype"

    # Test with no keys - should keep all wildcards
    formatted = template.format_map({}, strict=False)
    print(f"Formatted (no keys): {formatted}")
    assert formatted.value == "realtime.{ticker}.{dtype}"
    assert not formatted.is_exact
    assert len(formatted) == 3

    print("✓ format_map strict=False test passed!")


def test_format_map_partial_replacement():
    """Test format_map with partial replacement in strict=False mode."""
    print("\n\nTesting format_map with partial replacement...")

    template = PyTopic("{env}.{service}.{region}.{instance}")
    formatted = template.format_map({'env': 'prod', 'region': 'us-east'}, strict=False)
    print(f"Template: {template}")
    print(f"Formatted: {formatted}")

    assert formatted.value == "prod.{service}.us-east.{instance}"
    assert not formatted.is_exact
    assert len(formatted) == 4

    # Check parts
    parts = list(formatted)
    assert isinstance(parts[0], PyTopicPartExact)
    assert parts[0].part == "prod"
    assert isinstance(parts[1], PyTopicPartAny)
    assert parts[1].name == "service"
    assert isinstance(parts[2], PyTopicPartExact)
    assert parts[2].part == "us-east"
    assert isinstance(parts[3], PyTopicPartAny)
    assert parts[3].name == "instance"

    print("✓ Partial replacement test passed!")


def test_format_default_strict_false():
    """Test that format() and __call__() default to strict=False."""
    print("\n\nTesting format() and __call__() default to strict=False...")

    template = PyTopic("realtime.{ticker}.{dtype}")

    # Test format() method
    formatted1 = template.format(ticker='600010.SH')
    print(f"Using format(): {formatted1}")
    assert formatted1.value == "realtime.600010.SH.{dtype}"
    assert not formatted1.is_exact

    # Test __call__() method
    formatted2 = template(ticker='600010.SH')
    print(f"Using __call__(): {formatted2}")
    assert formatted2.value == "realtime.600010.SH.{dtype}"
    assert not formatted2.is_exact

    print("✓ Default strict=False test passed!")


def test_format_map_internalized_parameter():
    """Test that internalized parameter works correctly."""
    print("\n\nTesting format_map internalized parameter...")

    template = PyTopic("realtime.{ticker}")

    # With internalized=True (default)
    formatted1 = template.format_map({'ticker': '600010.SH'}, internalized=True, strict=False)
    print(f"Formatted (internalized=True): {formatted1}, owner={formatted1.owner}")
    # In pure Python, owner is always True

    # With internalized=False
    formatted2 = template.format_map({'ticker': '600010.SH'}, internalized=False, strict=False)
    print(f"Formatted (internalized=False): {formatted2}, owner={formatted2.owner}")
    # In pure Python, owner is always True

    print("✓ Internalized parameter test passed!")


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
    test_format_map_strict_true()
    test_format_map_strict_false()
    test_format_map_partial_replacement()
    test_format_default_strict_false()
    test_format_map_internalized_parameter()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED! ✓")
    print("=" * 60)
