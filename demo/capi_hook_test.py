"""Smoke tests for the Cython event-hook layer (event_engine.capi).

Demonstrates the CAPI surface: ``MessagePayload(topic, args, kwargs)``,
``EventHook(topic)`` and ``EventHookEx(topic)``. Unlike the native package,
the CAPI payload is immutable after construction and ``EventHookEx`` reports
aggregate hook stats rather than per-handler stats.
"""

import os
import sys
import time
import unittest

# Ensure project root is on sys.path for direct execution
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from event_engine.capi import EventHook, EventHookEx, MessagePayload, Topic


def make_payload(topic_value: str = 'abc.efg', args=(), kwargs=None) -> tuple[MessagePayload, Topic]:
    """Build a CAPI payload and its topic."""
    topic = Topic(topic_value)
    payload = MessagePayload(topic, tuple(args), {} if kwargs is None else dict(kwargs))
    return payload, topic


class TestMessagePayload(unittest.TestCase):
    """Contract: payload construction and accessors."""

    def test_00_initialization(self):
        """A constructed payload owns its C memory and starts at seq_id 0."""
        payload, topic = make_payload()
        self.assertTrue(payload.owner)
        self.assertEqual(payload.seq_id, 0)
        self.assertEqual(payload.args, ())
        self.assertEqual(payload.kwargs, {})
        self.assertEqual(payload.topic.value, topic.value)

    def test_01_args_and_kwargs_roundtrip(self):
        """args/kwargs survive construction unchanged."""
        payload, _ = make_payload(args=(1, 'x'), kwargs={'a': 2})
        self.assertEqual(payload.args, (1, 'x'))
        self.assertEqual(payload.kwargs, {'a': 2})

    def test_02_kwargs_with_topic(self):
        """kwargs_with_topic injects the payload topic without mutating kwargs."""
        payload, topic = make_payload(kwargs={'x': 1})
        aggregated = payload.kwargs_with_topic
        self.assertEqual(aggregated['x'], 1)
        self.assertEqual(aggregated['topic'].value, topic.value)
        self.assertEqual(payload.kwargs, {'x': 1})

    def test_03_repr(self):
        """repr carries the CAPI class name and payload details."""
        payload, _ = make_payload(args=(1,), kwargs={'k': 'v'})
        self.assertIn('MessagePayload', repr(payload))
        self.assertIn('seq_id=0', repr(payload))


class TestEventHookBasics(unittest.TestCase):
    """Contract: handler registration, containment and introspection."""

    def test_00_add_handler_and_contains(self):
        """Handlers accumulate and are discoverable."""
        _, topic = make_payload()
        hook = EventHook(topic)

        def h1(a):
            pass

        def h2(a, **kwargs):
            pass

        self.assertEqual(len(hook), 0)
        hook.add_handler(h1)
        hook.add_handler(h2)
        self.assertEqual(len(hook), 2)
        self.assertIn(h1, hook)
        self.assertIn(h2, hook)

    def test_01_handlers_property_and_iter(self):
        """handlers and __iter__ expose the same registrations."""
        _, topic = make_payload()
        hook = EventHook(topic)

        def h1(a):
            pass

        def h2(a, **kwargs):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)
        hs = list(iter(hook))
        self.assertEqual(hs, hook.handlers)
        self.assertEqual([entry['fn'] for entry in hs], [h1, h2])

    def test_02_remove_handler(self):
        """Removing one handler leaves the others in place."""
        _, topic = make_payload()
        hook = EventHook(topic)

        def h1(a):
            pass

        def h2(a, **kwargs):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)
        hook.remove_handler(h1)
        self.assertNotIn(h1, hook)
        self.assertIn(h2, hook)
        self.assertEqual(len(hook), 1)

    def test_03_clear(self):
        """clear removes every handler."""
        _, topic = make_payload()
        hook = EventHook(topic)
        hook.add_handler(lambda a: None)
        hook.clear()
        self.assertEqual(len(hook), 0)


class TestEventHookTrigger(unittest.TestCase):
    """Contract: dispatch conventions and handler isolation."""

    def test_00_trigger_order_no_topic_before_with_topic(self):
        """No-topic and with-topic handlers both run, in registration order."""
        payload, topic = make_payload(args=('a', 123, {}), kwargs={'d': 432})
        call_order = []

        def no_topic_handler(a, b, c, d):
            call_order.append('no_topic')

        def with_topic_handler(a, b, c, d, topic=None):
            call_order.append('with_topic')

        hook = EventHook(topic)
        hook.add_handler(no_topic_handler)
        hook.add_handler(with_topic_handler)
        hook.trigger(payload)
        self.assertEqual(call_order, ['no_topic', 'with_topic'])

    def test_01_with_topic_handler_receives_topic(self):
        """A handler declaring ``topic`` receives the payload topic."""
        payload, topic = make_payload(args=('a', 123), kwargs={'d': 432})
        received = {}

        def with_topic_handler(a, b, d, topic=None, **kwargs):
            received['topic'] = topic
            received['args'] = (a, b)
            received['d'] = d

        hook = EventHook(topic)
        hook.add_handler(with_topic_handler)
        hook.trigger(payload)
        self.assertEqual(received['topic'].value, topic.value)
        self.assertEqual(received['args'], ('a', 123))
        self.assertEqual(received['d'], 432)

    def test_02_call_operator_is_alias_for_trigger(self):
        """Calling the hook dispatches like trigger()."""
        payload, topic = make_payload(args=(1,))
        called = {}

        def handler(a):
            called['yes'] = True

        hook = EventHook(topic)
        hook.add_handler(handler)
        hook(payload)
        self.assertTrue(called.get('yes'))

    def test_03_handler_exception_does_not_propagate(self):
        """A failing handler is logged; the next handler still runs."""
        payload, topic = make_payload(args=(1,))
        called = []

        def failing_handler(a):
            raise ValueError('Handler error')

        def normal_handler(a):
            called.append(a)

        hook = EventHook(topic)
        hook.add_handler(failing_handler)
        hook.add_handler(normal_handler)
        hook.trigger(payload)
        self.assertEqual(called, [1])

    def test_04_iadd_deduplicates_handlers(self):
        """``+=`` skips a handler already registered."""
        payload, topic = make_payload(args=(1,))
        calls = {'count': 0}

        def h(a, **kwargs):
            calls['count'] += 1

        hook = EventHook(topic)
        hook += h
        hook += h
        self.assertEqual(len(hook), 1)
        hook.trigger(payload)
        self.assertEqual(calls['count'], 1)

    def test_05_remove_handler_only_removes_first_occurrence(self):
        """add_handler(deduplicate=False) allows duplicates; removal drops one."""
        payload, topic = make_payload(args=(1,))
        calls = {'count': 0}

        def h(a, **kwargs):
            calls['count'] += 1

        hook = EventHook(topic)
        hook.add_handler(h, deduplicate=False)
        hook.add_handler(h, deduplicate=False)
        self.assertEqual(len(hook), 2)
        hook.remove_handler(h)
        hook.trigger(payload)
        self.assertEqual(calls['count'], 1)


class TestEventHookEx(unittest.TestCase):
    """Contract: EventHookEx aggregates per-hook call statistics."""

    def test_00_stats_shape(self):
        """stats carries the hook-level counters."""
        hook = EventHookEx(Topic('hookex.stats'))
        self.assertEqual(
            set(hook.stats),
            {'n_calls', 'last_call_start', 'last_call_complete', 'elapsed_seconds'},
        )

    def test_01_stats_accumulate_over_triggers(self):
        """n_calls and elapsed_seconds grow with every dispatch."""
        payload, topic = make_payload(args=(1,))
        hook = EventHookEx(topic)

        def slow_handler(a):
            time.sleep(0.01)

        hook.add_handler(slow_handler)
        hook.trigger(payload)
        hook(payload)

        stats = hook.stats
        self.assertEqual(stats['n_calls'], 2)
        self.assertGreaterEqual(stats['elapsed_seconds'], 0.02)
        self.assertGreater(stats['last_call_complete'], 0)

    def test_02_stats_zero_on_new_hook(self):
        """A fresh EventHookEx reports zeroed stats."""
        hook = EventHookEx(Topic('hookex.fresh'))
        self.assertEqual(hook.stats['n_calls'], 0)
        self.assertEqual(hook.stats['elapsed_seconds'], 0.0)


class TestEventHookHusk(unittest.TestCase):
    """Contract: empty husks are safe to inspect and reject dispatch."""

    def test_00_empty_husk_is_safe(self):
        """len/repr work on a husk; add_handler and trigger raise."""
        hook = EventHook()
        payload, _ = make_payload()
        self.assertEqual(len(hook), 0)
        self.assertIn('NO_TOPIC', repr(hook))
        with self.assertRaises(RuntimeError):
            hook.add_handler(lambda a: None)
        with self.assertRaises(RuntimeError):
            hook.trigger(payload)
        with self.assertRaises(RuntimeError):
            hook(payload)


class TestEventHookRepr(unittest.TestCase):
    """Contract: repr identifies the hook and its topic."""

    def test_00_repr_format(self):
        hook = EventHook(Topic('test.topic'))
        r = repr(hook)
        self.assertIn('EventHook', r)
        self.assertIn('test.topic', r)
        self.assertIn('n=0', r)


def suite():
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMessagePayload))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookBasics))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookTrigger))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookEx))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookHusk))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookRepr))
    return test_suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())
    sys.exit(0 if result.wasSuccessful() else 1)
