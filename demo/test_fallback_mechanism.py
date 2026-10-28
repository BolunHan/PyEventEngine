"""
Test script to verify the fallback mechanism works correctly.

This script demonstrates that the module can automatically fall back to the
pure Python implementation when the Cython module is not available.
"""

import os
import sys

# Ensure project root is on sys.path for direct execution
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Test 1: Import and check which implementation is being used
print("=" * 60)
print("Testing fallback mechanism...")
print("=" * 60)

from event_engine.capi import EventEngine, EventEngineEx, Full, Empty, USING_FALLBACK, Topic

if USING_FALLBACK:
    print("✓ Using FALLBACK (Pure Python) implementation")
    print("  This is expected on Windows or when c_engine is not compiled")
else:
    print("✓ Using CYTHON implementation")
    print("  This is the high-performance version")

print(f"\nEventEngine class: {EventEngine.__module__}")
print(f"Full exception: {Full.__module__}")
print(f"Empty exception: {Empty.__module__}")

# Test 2: Verify basic functionality works
print("\n" + "=" * 60)
print("Testing basic functionality...")
print("=" * 60)

try:
    # Create an engine
    engine = EventEngine(capacity=100)
    print(f"✓ Created engine: {engine}")
    
    # Create a topic
    topic = Topic("test.fallback.check")
    print(f"✓ Created topic: {topic.value}")
    
    # Register a handler
    results = []
    def test_handler(*args, **kwargs):
        results.append((args, kwargs))
    
    engine.register_handler(topic, test_handler)
    print("✓ Registered handler")
    
    # Start engine
    engine.start()
    print("✓ Started engine")
    
    # Publish a message
    engine.put(topic, "test_arg", key="test_value")
    print("✓ Published message")
    
    # Wait for processing
    import time
    time.sleep(0.3)
    
    # Stop engine
    engine.stop()
    print("✓ Stopped engine")
    
    # Verify results: handlers accepting **kwargs also receive the topic
    assert len(results) == 1
    args, kwargs = results[0]
    assert args == ("test_arg",)
    assert kwargs["key"] == "test_value"
    assert kwargs["topic"].value == "test.fallback.check"
    print(f"✓ Message processed correctly: {results}")
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    
except Exception as e:
    print(f"\n❌ Test failed with error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Display implementation info
print("\n" + "=" * 60)
print("Implementation Information:")
print("=" * 60)
print(f"Using fallback: {USING_FALLBACK}")
print(f"EventEngine: {EventEngine}")
print(f"EventEngineEx: {EventEngineEx}")
print(f"Full: {Full}")
print(f"Empty: {Empty}")
print("=" * 60)

