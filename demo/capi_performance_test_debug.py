import os
import sys
import time
import threading
import signal
import faulthandler

# Enable faulthandler to get better stack traces on segfault
faulthandler.enable()

# Ensure project root is on sys.path for direct execution
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from event_engine.capi import EventEngine, PyTopic  # type: ignore


def test_basic_single_message():
    """Test with just one message to isolate the issue"""
    print("=" * 60)
    print("TEST: Single message")
    print("=" * 60)
    
    engine = EventEngine(capacity=16)
    topic = PyTopic("test.topic")
    
    received = []
    done = threading.Event()
    
    def handler(value: int):
        print(f"Handler called with value: {value}")
        received.append(value)
        done.set()
    
    engine.register_handler(topic, handler)
    engine.start()
    print("Engine started")
    
    time.sleep(0.1)  # Let engine initialize
    
    print("Putting message...")
    engine.put(topic, 42, block=True)
    print("Message put, waiting for handler...")
    
    if done.wait(timeout=2):
        print(f"�� Handler executed successfully, received: {received}")
    else:
        print(f"✗ Timeout waiting for handler")
    
    engine.stop()
    print("Engine stopped\n")


def test_producer_thread():
    """Test with producer in separate thread"""
    print("=" * 60)
    print("TEST: Producer in separate thread")
    print("=" * 60)
    
    total_messages = 63
    engine = EventEngine(capacity=64)
    topic = PyTopic("perf.topic")
    
    count = [0]  # Use list to avoid closure issues
    done = threading.Event()
    
    def handler(value: int):
        count[0] += 1
        print(f"Handler: {count[0]}/{total_messages}, value={value}")
        if count[0] >= total_messages:
            done.set()
    
    engine.register_handler(topic, handler)
    
    def producer():
        print(f"Producer thread started (tid={threading.get_ident()})")
        for i in range(total_messages):
            print(f"Producer: putting message {i}")
            try:
                engine.put(topic, i, block=True)
                print(f"Producer: message {i} put successfully")
            except Exception as e:
                print(f"Producer: ERROR putting message {i}: {e}")
                break
        print(f"Producer thread finished")
    
    producer_thread = threading.Thread(target=producer, name="producer", daemon=False)
    
    print("Starting engine...")
    engine.start()
    print(f"Engine started (consumer tid likely different)")
    
    time.sleep(0.1)  # Let engine initialize
    
    print("Starting producer thread...")
    producer_thread.start()
    
    print(f"Waiting for messages (timeout=5s)...")
    if done.wait(timeout=5):
        print(f"✓ All {count[0]} messages processed")
    else:
        print(f"✗ Timeout: only {count[0]}/{total_messages} messages processed")
    
    print("Stopping engine...")
    engine.stop()
    
    print("Joining producer thread...")
    producer_thread.join(timeout=2)
    
    print(f"Test complete\n")


def main():
    print("\n" + "=" * 60)
    print("DIAGNOSTIC TEST SUITE")
    print("=" * 60 + "\n")
    
    try:
        test_basic_single_message()
    except Exception as e:
        print(f"EXCEPTION in test_basic_single_message: {e}")
        import traceback
        traceback.print_exc()
    
    time.sleep(0.5)
    
    try:
        test_producer_thread()
    except Exception as e:
        print(f"EXCEPTION in test_producer_thread: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()

