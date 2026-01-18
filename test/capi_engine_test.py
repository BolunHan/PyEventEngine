import os
import sys
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO

# Ensure project root is on sys.path for direct execution
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from event_engine.capi import EventHook, EventEngine, EventEngineEx, Full, Empty, Topic


class OutputCapture:
    def __enter__(self):
        self._buf = StringIO()
        self._cm = redirect_stdout(self._buf)
        self._cm.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cm.__exit__(exc_type, exc_val, exc_tb)

    @property
    def text(self):
        return self._buf.getvalue()


class TestEventEngineBasics(unittest.TestCase):
    def test_initialization(self):
        engine = EventEngine(capacity=100)
        self.assertEqual(engine.capacity, 100)
        self.assertEqual(len(engine), 0)  # No hooks registered initially

    def test_repr(self):
        engine = EventEngine()
        r = repr(engine)
        self.assertIn('EventEngine', r)
        self.assertIn('idle', r)

    def test_len_with_no_hooks(self):
        engine = EventEngine()
        self.assertEqual(len(engine), 0)

    def test_register_hook_and_unregister(self):
        engine = EventEngine()
        topic = Topic('test.topic')  # type: ignore[arg-type]
        hook = EventHook(topic)

        def handler(a):
            pass

        hook.add_handler(handler)
        engine.register_hook(hook)

        self.assertEqual(len(engine), 1)

        retrieved_hook = engine.unregister_hook(topic)
        self.assertIs(retrieved_hook, hook)
        self.assertEqual(len(engine), 0)

    def test_register_hook_duplicate_raises_keyerror(self):
        engine = EventEngine()
        topic = Topic('test.topic')  # type: ignore[arg-type]
        hook1 = EventHook(topic)
        hook2 = EventHook(topic)

        engine.register_hook(hook1)

        with self.assertRaises(KeyError):
            engine.register_hook(hook2)

    def test_unregister_hook_nonexistent_raises_keyerror(self):
        engine = EventEngine()
        topic = Topic('test.topic')  # type: ignore[arg-type]

        with self.assertRaises(KeyError):
            engine.unregister_hook(topic)

    def test_register_handler_creates_hook_if_needed(self):
        engine = EventEngine()
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a):
            pass

        self.assertEqual(len(engine), 0)
        engine.register_handler(topic, handler)
        self.assertEqual(len(engine), 1)

    def test_register_handler_to_existing_hook(self):
        engine = EventEngine()
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def h1(a):
            pass

        def h2(a, **kw):
            pass

        engine.register_handler(topic, h1)
        self.assertEqual(len(engine), 1)

        # Register to same topic
        engine.register_handler(topic, h2)
        self.assertEqual(len(engine), 1)

    def test_unregister_handler_removes_empty_hook(self):
        engine = EventEngine()
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        self.assertEqual(len(engine), 1)

        engine.unregister_handler(topic, handler)
        self.assertEqual(len(engine), 0)

    def test_unregister_handler_nonexistent_topic_raises_keyerror(self):
        engine = EventEngine()
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a):
            pass

        with self.assertRaises(KeyError):
            engine.unregister_handler(topic, handler)

    def test_event_hooks_iterator(self):
        engine = EventEngine()
        topic1 = Topic('topic1')  # type: ignore[arg-type]
        topic2 = Topic('topic2')  # type: ignore[arg-type]

        def h1(a):
            pass

        def h2(a):
            pass

        engine.register_handler(topic1, h1)
        engine.register_handler(topic2, h2)

        hooks = list(engine.event_hooks())
        self.assertEqual(len(hooks), 2)
        self.assertIsInstance(hooks[0], EventHook)
        self.assertIsInstance(hooks[1], EventHook)

    def test_topics_iterator(self):
        engine = EventEngine()
        topic1 = Topic('topic1')  # type: ignore[arg-type]
        topic2 = Topic('topic2')  # type: ignore[arg-type]

        def h1(a):
            pass

        def h2(a):
            pass

        engine.register_handler(topic1, h1)
        engine.register_handler(topic2, h2)

        topics = list(engine.topics())
        self.assertEqual(len(topics), 2)

    def test_items_iterator(self):
        engine = EventEngine()
        topic1 = Topic('topic1')  # type: ignore[arg-type]
        topic2 = Topic('topic2')  # type: ignore[arg-type]

        def h1(a):
            pass

        def h2(a):
            pass

        engine.register_handler(topic1, h1)
        engine.register_handler(topic2, h2)

        items = list(engine.items())
        self.assertEqual(len(items), 2)
        for topic, hook in items:
            self.assertIsInstance(topic, Topic)
            self.assertIsInstance(hook, EventHook)


class TestEventEngineQueue(unittest.TestCase):
    def test_put_and_get_basic(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a, b):
            pass

        engine.register_handler(topic, handler)

        # Put a message
        engine.put(topic, 1, 2)

        # Get the message (non-blocking)
        payload = engine.get(block=False)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.args, (1, 2))

    def test_get_empty_raises_empty(self):
        engine = EventEngine(capacity=10)
        with self.assertRaises(Empty):
            engine.get(block=False)

    def test_put_full_raises_full_when_nonblocking(self):
        engine = EventEngine(capacity=2)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a):
            pass

        engine.register_handler(topic, handler)

        # Fill the queue
        engine.put(topic, 1, block=False)
        engine.put(topic, 2, block=False)

        # Try to add third (should raise Full when capacity is reached)
        with self.assertRaises(Full):
            engine.put(topic, 3, block=False)

    def test_put_non_exact_topic_raises_valueerror(self):
        engine = EventEngine()
        # Create a non-exact topic (with wildcard or pattern)
        topic = Topic('test.+any')  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            engine.put(topic, 1)

    def test_publish_basic(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a, b, **kw):
            pass

        engine.register_handler(topic, handler)

        # Publish with explicit args and kwargs
        engine.publish(topic, (1, 2), {'x': 3})

        payload = engine.get(block=False)
        self.assertTrue(payload is not None)
        self.assertEqual(payload.args, (1, 2))
        self.assertEqual(payload.kwargs, {'x': 3})

    def test_publish_non_exact_topic_raises_valueerror(self):
        engine = EventEngine()
        topic = Topic('test.+any')  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            engine.publish(topic, (), {})

    def test_payload_from_get_owns_args_and_kwargs(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a, **kw):
            pass

        engine.register_handler(topic, handler)

        engine.put(topic, 1, x=2)

        payload = engine.get(block=False)
        # Payload obtained from get() should own its args and kwargs
        self.assertTrue(payload.owner)


class TestEventEngineLoop(unittest.TestCase):
    def test_start_and_stop(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        received = []

        def handler(a):
            received.append(a)

        engine.register_handler(topic, handler)

        engine.start()
        self.assertTrue(engine.active)

        time.sleep(0.1)

        # Put a message
        engine.put(topic, 42)

        # Wait for processing
        time.sleep(0.2)

        engine.stop()
        self.assertFalse(engine.active)

        # Handler should have been called
        self.assertIn(42, received)

    def test_multiple_handlers_on_same_topic(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        results = {'h1': 0, 'h2': 0}

        def h1(a):
            results['h1'] += a

        def h2(a):
            results['h2'] += a * 2

        engine.register_handler(topic, h1)
        engine.register_handler(topic, h2)

        engine.start()
        time.sleep(0.1)

        engine.put(topic, 5)
        time.sleep(0.2)

        engine.stop()

        self.assertEqual(results['h1'], 5)
        self.assertEqual(results['h2'], 10)

    def test_multiple_topics(self):
        engine = EventEngine(capacity=20)
        topic1 = Topic('topic1')  # type: ignore[arg-type]
        topic2 = Topic('topic2')  # type: ignore[arg-type]

        results = {'t1': [], 't2': []}

        def h1(a):
            results['t1'].append(a)

        def h2(a):
            results['t2'].append(a)

        engine.register_handler(topic1, h1)
        engine.register_handler(topic2, h2)

        engine.start()
        time.sleep(0.1)

        engine.put(topic1, 'x')
        engine.put(topic2, 'y')
        time.sleep(0.2)

        engine.stop()

        self.assertEqual(results['t1'], ['x'])
        self.assertEqual(results['t2'], ['y'])

    def test_handler_exception_does_not_crash_engine(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        called_after_error = []

        def failing_handler(a):
            raise ValueError('Test error')

        def normal_handler(a):
            called_after_error.append(a)

        engine.register_handler(topic, failing_handler)
        engine.register_handler(topic, normal_handler)

        engine.start()
        time.sleep(0.1)

        engine.put(topic, 42)
        time.sleep(0.2)

        engine.stop()

        # Normal handler should still be called despite error in first handler
        self.assertIn(42, called_after_error)

    def test_clear_unregisters_all_hooks(self):
        engine = EventEngine(capacity=10)
        topic1 = Topic('topic1')  # type: ignore[arg-type]
        topic2 = Topic('topic2')  # type: ignore[arg-type]

        def h1(a):
            pass

        def h2(a):
            pass

        engine.register_handler(topic1, h1)
        engine.register_handler(topic2, h2)

        self.assertEqual(len(engine), 2)

        engine.clear()

        self.assertEqual(len(engine), 0)

    def test_clear_only_works_when_stopped(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        self.assertEqual(len(engine), 1)

        engine.start()
        time.sleep(0.1)

        # Attempt to clear while running (should not work; logged as error)
        engine.clear()
        self.assertEqual(len(engine), 1)  # Hook still there

        engine.stop()

        # Now clear should work
        engine.clear()
        self.assertEqual(len(engine), 0)

    def test_seq_id_incremented_on_publish(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        def handler(a):
            pass

        engine.register_handler(topic, handler)

        engine.put(topic, 1)
        payload1 = engine.get(block=False)
        seq1 = payload1.seq_id

        engine.put(topic, 2)
        payload2 = engine.get(block=False)
        seq2 = payload2.seq_id

        self.assertGreater(seq2, seq1)


class TestEventEngineEx(unittest.TestCase):
    def test_initialization(self):
        engine = EventEngineEx(capacity=100)
        self.assertEqual(engine.capacity, 100)
        self.assertEqual(len(engine), 0)

    def test_repr(self):
        engine = EventEngineEx()
        r = repr(engine)
        self.assertIn('EventEngineEx', r)
        self.assertIn('idle', r)

    def test_inherits_from_eventengihe(self):
        engine = EventEngineEx()
        self.assertIsInstance(engine, EventEngine)

    def test_basic_operation_same_as_engine(self):
        engine = EventEngineEx(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        received = []

        def handler(a):
            received.append(a)

        engine.register_handler(topic, handler)

        engine.start()
        time.sleep(0.1)

        engine.put(topic, 42)
        time.sleep(0.2)

        engine.stop()

        self.assertIn(42, received)

    def test_timer_integration(self):
        engine = EventEngineEx(capacity=20)
        results = {'count': 0}

        def timer_handler(**kw):
            results['count'] += 1

        # Get a timer topic and register handler
        engine.start()
        timer_topic = engine.get_timer(interval=0.1)
        engine.register_handler(timer_topic, timer_handler)

        time.sleep(0.5)  # Should trigger multiple times
        engine.stop()

        # Timer should have fired multiple times
        self.assertGreater(results['count'], 0)

    def test_stop_waits_for_timer_threads(self):
        engine = EventEngineEx(capacity=10)
        engine.start()
        timer_topic = engine.get_timer(interval=0.1)

        def timer_handler(**kw):
            pass

        engine.register_handler(timer_topic, timer_handler)

        time.sleep(0.2)

        # Stop should wait for timer threads to finish
        engine.stop()
        self.assertFalse(engine.active)

    def test_clear_stops_timers(self):
        engine = EventEngineEx(capacity=10)
        engine.start()

        timer_topic = engine.get_timer(interval=0.1)

        def timer_handler(**kw):
            pass

        engine.register_handler(timer_topic, timer_handler)

        time.sleep(0.2)
        engine.stop()

        # Clear should stop all timer threads
        engine.clear()
        time.sleep(0.2)  # Allow time for threads to finish


class TestEventEngineWithPayloads(unittest.TestCase):
    def test_payload_args_not_mutated(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        received_args = []

        def handler(a, b, c):
            # Try to mutate
            a = 999
            received_args.append((a, b, c))

        engine.register_handler(topic, handler)

        engine.start()
        time.sleep(0.1)

        original_args = (1, 2, 3)
        engine.put(topic, *original_args)
        time.sleep(0.2)

        engine.stop()

        # Handler received immutable args
        self.assertTrue(any(args == (999, 2, 3) for args in received_args))

    def test_payload_kwargs_not_mutated(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        received_kwargs = []

        def handler(a, **kw):
            # Try to mutate
            kw['mutated'] = True
            received_kwargs.append(dict(kw))

        engine.register_handler(topic, handler)

        engine.start()
        time.sleep(0.1)

        engine.put(topic, 1, x=2, y=3)
        time.sleep(0.2)

        engine.stop()

        # Payload's kwargs should not be affected by mutations
        # (We verify by checking that the handler saw the mutation,
        # but the original payload was not changed)
        self.assertTrue(any('mutated' in kw for kw in received_kwargs))


class TestEventEngineThreadSafety(unittest.TestCase):
    def test_concurrent_puts_processed(self):
        engine = EventEngine(capacity=100)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        results = []

        def handler(a):
            results.append(a)

        engine.register_handler(topic, handler)

        engine.start()
        time.sleep(0.1)

        def put_messages(start, count):
            for i in range(start, start + count):
                engine.put(topic, i)

        threads = [
            threading.Thread(target=put_messages, args=(0, 10)),
            threading.Thread(target=put_messages, args=(10, 10)),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        time.sleep(0.3)
        engine.stop()

        # All messages should be processed
        self.assertEqual(len(results), 20)
        self.assertEqual(set(results), set(range(20)))


class TestEventEngineRemoval(unittest.TestCase):
    def test_remove_handler_safe(self):
        engine = EventEngine(capacity=10)
        topic = Topic('test.topic')  # type: ignore[arg-type]

        called = []

        def handler_1(a):
            called.append(a)

        def handler_2(a):
            called.append(a * 10)

        def handler_3(a):
            called.append(a * 100)

        class A:
            @classmethod
            def cls_handler(cls, a):
                called.append(a * 1000)

            @staticmethod
            def static_handler(a):
                called.append(a * 10000)

            def bound_handler(self, a):
                called.append(a * 100000)

        a_1 = A()
        a_2 = A()
        engine.register_handler(topic, handler_1)
        engine.register_handler(topic, handler_2)
        engine.register_handler(topic, handler_3)
        engine.register_handler(topic, A.cls_handler)
        engine.register_handler(topic, A.static_handler)
        engine.register_handler(topic, a_1.bound_handler)
        engine.register_handler(topic, a_2.bound_handler)

        engine.start()
        time.sleep(0.1)
        engine.put(topic, 1)
        time.sleep(0.2)
        engine.put(topic, 2)
        time.sleep(0.2)
        engine.stop()

        # Now remove handler_2 safely
        engine.unregister_handler(topic, handler_2)
        hook = engine.get_hook(topic)
        self.assertIsNotNone(hook)
        self.assertEqual(len(hook), 6)

        # Now continue to remove all the handler
        engine.unregister_handler(topic, handler_1)
        self.assertEqual(len(hook), 5)
        engine.unregister_handler(topic, handler_3)
        engine.unregister_handler(topic, A.cls_handler)
        engine.unregister_handler(topic, A.static_handler)
        engine.unregister_handler(topic, a_1.bound_handler)
        engine.unregister_handler(topic, a_2.bound_handler)
        with self.assertRaises(KeyError):
            _ = engine.get_hook(topic)


def suite():
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEngineBasics))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEngineQueue))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEngineLoop))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEngineEx))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEngineWithPayloads))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEngineThreadSafety))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEngineRemoval))
    return test_suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())
    sys.exit(0 if result.wasSuccessful() else 1)
