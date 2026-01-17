import sys
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO

from event_engine.capi.c_event import MessagePayload, EventHook, EventHookEx
from event_engine.capi.c_topic import Topic


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


def make_payload(topic_value: str = 'abc.efg', args=(), kwargs=None) -> tuple[MessagePayload, Topic]:
    if kwargs is None:
        kwargs = {}
    topic = Topic(topic_value)
    payload = MessagePayload(topic, args, kwargs)
    return payload, topic


class TestMessagePayload(unittest.TestCase):
    def test_payload_topic_property(self):
        t = Topic('unit.test')
        p = MessagePayload(t, tuple(), dict())
        self.assertEqual(p.topic.value, t.value)

    def test_payload_args_and_kwargs(self):
        p = MessagePayload(Topic('a.b.c'), (1, 'x'), {'a': 2})
        self.assertEqual(p.args, (1, 'x'))
        self.assertEqual(p.kwargs, {'a': 2})

    def test_payload_repr(self):
        p = make_payload()
        r = repr(p)
        self.assertIn('MessagePayload', r)


class TestEventHookBasics(unittest.TestCase):
    def test_add_handler_and_contains(self):
        payload, topic = make_payload(args=(1,), kwargs={'k': 'v'})
        hook = EventHook(topic)

        def h1(a):
            pass

        def h2(a, **kwargs):
            pass

        self.assertEqual(len(hook), 0)
        hook.add_handler(h1)
        self.assertEqual(len(hook), 1)
        hook.add_handler(h2)
        self.assertEqual(len(hook), 2)
        self.assertIn(h1, hook)
        self.assertIn(h2, hook)

    def test_handlers_property_and_iter(self):
        payload, topic = make_payload()
        hook = EventHook(topic)

        def h1(a):
            pass

        def h2(a, **kwargs):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)

        hs = list(iter(hook))
        self.assertEqual(hs, hook.handlers)
        self.assertEqual(set([_['fn'] for _ in hs]), {h1, h2})

    def test_iadd_operator(self):
        payload, topic = make_payload()
        hook = EventHook(topic)

        def h(a, **kw):
            pass

        hook += h
        self.assertEqual(len(hook), 1)
        self.assertIn(h, hook)

    def test_isub_operator(self):
        payload, topic = make_payload()
        hook = EventHook(topic)

        def h(a, **kw):
            pass

        hook += h
        self.assertEqual(len(hook), 1)
        hook -= h
        self.assertEqual(len(hook), 0)
        self.assertNotIn(h, hook)

    def test_remove_handler(self):
        payload, topic = make_payload()
        hook = EventHook(topic)

        def h1(a):
            pass

        def h2(a, **kw):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)
        self.assertEqual(len(hook), 2)

        hook.remove_handler(h1)
        self.assertEqual(len(hook), 1)
        self.assertNotIn(h1, hook)
        self.assertIn(h2, hook)

    def test_clear(self):
        payload, topic = make_payload()
        hook = EventHook(topic)

        def h1(a):
            pass

        def h2(a, **kw):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)
        self.assertEqual(len(hook), 2)

        hook.clear()
        self.assertEqual(len(hook), 0)


class TestEventHookTrigger(unittest.TestCase):
    def test_trigger_order_no_topic_before_with_topic(self):
        args = ('a', 123, {})
        kwargs = {'d': 432}
        payload, topic = make_payload(args=args, kwargs=kwargs)

        call_order = []

        def no_topic_handler_0(a, b, c, d):
            call_order.append('no_topic_0')

        def no_topic_handler_1(a, b, c, d):
            call_order.append('no_topic_1')

        def with_topic_handler(a, b, c, d, topic=None):
            call_order.append('with_topic')

        hook = EventHook(topic)
        hook.add_handler(no_topic_handler_0)
        hook.add_handler(no_topic_handler_1)
        hook.add_handler(with_topic_handler)

        hook.trigger(payload)

        self.assertEqual(call_order, ['no_topic_0', 'no_topic_1', 'with_topic'])

    def test_no_topic_handler_does_not_receive_topic(self):
        args = ('a', 123)
        kwargs = {'d': 432}
        payload, topic = make_payload(args=args, kwargs=kwargs)

        received_kwargs = {}

        def no_topic_handler(a, b, d):
            received_kwargs.update({'a': a, 'b': b, 'd': d})

        hook = EventHook(topic)
        hook.add_handler(no_topic_handler)
        hook.trigger(payload)

        self.assertEqual(received_kwargs['a'], 'a')
        self.assertEqual(received_kwargs['b'], 123)
        self.assertEqual(received_kwargs['d'], 432)

    def test_with_topic_handler_receives_topic_as_kwarg(self):
        args = ('a', 123)
        kwargs = {'d': 432}
        payload, topic = make_payload(args=args, kwargs=kwargs)

        received = {}

        def with_topic_handler(a, b, d, topic=None, **kw):
            received['topic'] = topic
            received['args'] = (a, b)
            received['d'] = d

        hook = EventHook(topic)
        hook.add_handler(with_topic_handler)
        hook.trigger(payload)

        self.assertIsNotNone(received['topic'])
        self.assertEqual(received['topic'].value, topic.value)
        self.assertEqual(received['args'], ('a', 123))
        self.assertEqual(received['d'], 432)

    def test_handler_exception_does_not_propagate(self):
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)

        def failing_handler(a):
            raise ValueError('Handler error')

        def normal_handler(a):
            pass

        hook.add_handler(failing_handler)
        hook.add_handler(normal_handler)

        # Should not raise; exceptions are logged internally
        try:
            hook.trigger(payload)
        except ValueError:
            self.fail('Handler exception should not propagate')

    def test_multiple_handler_exceptions_do_not_propagate(self):
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)

        def failing_handler_1(a):
            raise ValueError('Error 1')

        def failing_handler_2(a):
            raise RuntimeError('Error 2')

        def normal_handler(a):
            pass

        hook.add_handler(failing_handler_1)
        hook.add_handler(failing_handler_2)
        hook.add_handler(normal_handler)

        # Should not raise despite multiple failures
        try:
            hook.trigger(payload)
        except (ValueError, RuntimeError):
            self.fail('Handler exceptions should not propagate')

    def test_handlers_cannot_mutate_payload_args(self):
        original_args = (1, 2, 3)
        payload, topic = make_payload(args=original_args, kwargs={})

        def mutating_handler(a, b, c):
            # Try to mutate local variables (won't affect payload)
            a = 999
            b = 888

        hook = EventHook(topic)
        hook.add_handler(mutating_handler)
        hook.trigger(payload)

        # Payload args should remain unchanged
        self.assertEqual(payload.args, original_args)

    def test_handlers_cannot_mutate_payload_kwargs(self):
        original_kwargs = {'x': 1, 'y': 2}
        payload, topic = make_payload(args=(), kwargs=original_kwargs)

        def no_topic_handler():
            # No-topic handler receives empty kwargs (no mutation possible)
            pass

        def mutating_handler(**kw):
            # With-topic handler receives a COPY of kwargs, so mutations don't affect original
            kw['x'] = 999
            kw['z'] = 888

        hook = EventHook(topic)
        hook.add_handler(no_topic_handler)
        hook.add_handler(mutating_handler)
        hook.trigger(payload)

        # Payload kwargs should remain unchanged
        self.assertEqual(payload.kwargs, original_kwargs)
        self.assertNotIn('z', payload.kwargs)

        hook_no_topic = EventHook(topic)
        hook_no_topic.add_handler(no_topic_handler)
        hook_no_topic.trigger(payload)
        self.assertEqual(payload.kwargs, original_kwargs)
        self.assertNotIn('z', payload.kwargs)

        hook_with_topic = EventHook(topic)
        hook_with_topic.add_handler(mutating_handler)
        hook_with_topic.trigger(payload)
        self.assertEqual(payload.kwargs, original_kwargs)
        self.assertNotIn('z', payload.kwargs)

    def test_call_operator_alias(self):
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)

        called = {}

        def handler(a):
            called['yes'] = True

        hook.add_handler(handler)
        hook(payload)  # Use call operator instead of trigger

        self.assertTrue(called.get('yes'))

    def test_iadd_deduplicates_handlers(self):
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)

        calls = {'count': 0}

        def h(a, **kw):
            calls['count'] += 1

        hook += h
        hook += h  # Should not add again due to deduplicate in __iadd__

        self.assertEqual(len(hook), 1)
        hook.trigger(payload)
        self.assertEqual(calls['count'], 1)

    def test_add_handler_without_deduplicate_allows_duplicates(self):
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)

        calls = {'count': 0}

        def h(a, **kw):
            calls['count'] += 1

        hook.add_handler(h, deduplicate=False)
        hook.add_handler(h, deduplicate=False)  # Added twice intentionally

        self.assertEqual(len(hook), 2)
        hook.trigger(payload)
        self.assertEqual(calls['count'], 2)

    def test_remove_handler_only_removes_first_occurrence(self):
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)

        calls = {'count': 0}

        def h(a, **kw):
            calls['count'] += 1

        hook.add_handler(h, deduplicate=False)
        hook.add_handler(h, deduplicate=False)
        self.assertEqual(len(hook), 2)

        hook.remove_handler(h)
        self.assertEqual(len(hook), 1)

        hook.trigger(payload)
        self.assertEqual(calls['count'], 1)


class TestEventHookEx(unittest.TestCase):
    def test_stats_tracking(self):
        payload, topic = make_payload(args=(1, 2), kwargs={'x': 3})
        hook = EventHookEx(topic)

        def h1(a, b, **kw):
            time.sleep(0.01)

        def h2(a, b):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)

        hook.trigger(payload)
        hook.trigger(payload)

        stats = hook.stats
        assert stats['n_calls'] == 2
        assert stats['elapsed_seconds'] >= 0.02  # At least time for h1
        print(stats)


def suite():
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMessagePayload))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookBasics))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookTrigger))
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventHookEx))
    return test_suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())
    sys.exit(0 if result.wasSuccessful() else 1)
