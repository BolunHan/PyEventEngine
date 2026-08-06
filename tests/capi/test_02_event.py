"""Contract tests for the Cython event layer (event_engine.capi.c_event).

Covers MessagePayload, EventHook and EventHookEx. Internal C state
(callback / watcher arrays, callable list) is verified through the
``EventTestToolkit`` test toolkit in ``c_event.pyx``.
"""

import logging
import time
import unittest

from event_engine.capi import MessagePayload, Topic
from event_engine.capi.c_event import EventHook, EventHookEx, EventTestToolkit


def make_payload(topic_value="abc.efg", args=(), kwargs=None) -> tuple[MessagePayload, Topic]:
    topic = Topic(topic_value)
    payload = MessagePayload(topic, args, {} if kwargs is None else kwargs)
    return payload, topic


class TestMessagePayload(unittest.TestCase):
    """Contract: payload construction, accessors and ownership."""

    def test_00_basic_accessors(self) -> None:
        """topic/args/kwargs round-trip through the constructor."""
        topic = Topic("unit.test")
        args = (1, "x", {"nested": 2})
        kwargs = {"a": 2}
        payload = MessagePayload(topic, args, kwargs)
        self.assertEqual(payload.topic.value, topic.value)
        self.assertEqual(payload.args, args)
        self.assertEqual(payload.kwargs, kwargs)

    def test_01_owner_flag(self) -> None:
        """Constructed payloads own their memory."""
        payload, _ = make_payload()
        self.assertTrue(payload.owner)

    def test_02_seq_id_default_and_set(self) -> None:
        """seq_id defaults to 0 and is settable."""
        payload, _ = make_payload()
        self.assertEqual(payload.seq_id, 0)
        payload.seq_id = 42
        self.assertEqual(payload.seq_id, 42)

    def test_03_kwargs_with_topic(self) -> None:
        """kwargs_with_topic is a copy of kwargs with the topic injected."""
        payload, topic = make_payload(kwargs={"x": 1})
        aggregated = payload.kwargs_with_topic
        self.assertEqual(aggregated["x"], 1)
        self.assertEqual(aggregated["topic"].value, topic.value)

    def test_04_repr(self) -> None:
        """repr carries class name, topic, seq and args/kwargs."""
        payload, _ = make_payload(args=(1,), kwargs={"k": "v"})
        r = repr(payload)
        self.assertIn("MessagePayload", r)
        self.assertIn("seq_id=0", r)
        self.assertIn("k", r)

    def test_05_kwargs_not_mutated_by_engine(self) -> None:
        """The payload does not mutate the caller's kwargs dict."""
        original = {"x": 1}
        payload, _ = make_payload(kwargs=original)
        _ = payload.kwargs_with_topic
        self.assertEqual(original, {"x": 1})


class TestEventHookBasics(unittest.TestCase):
    """Contract: handler registration, containment, introspection."""

    def setUp(self) -> None:
        self.topic = Topic("hook.basic")

    def _hook(self) -> EventHook:
        return EventHook(self.topic)

    def test_00_add_handler_and_len(self) -> None:
        """Handlers accumulate; len reflects the C callback array."""
        hook = self._hook()

        def h1(a):
            pass

        def h2(a, **kwargs):
            pass

        self.assertEqual(len(hook), 0)
        hook.add_handler(h1)
        self.assertEqual(len(hook), 1)
        hook.add_handler(h2)
        self.assertEqual(len(hook), 2)
        self.assertEqual(EventTestToolkit.get_n_callbacks(hook), 2)
        self.assertEqual(EventTestToolkit.get_callable_count(hook), 2)

    def test_01_contains(self) -> None:
        """__contains__ detects registered handlers (incl. bound methods)."""
        hook = self._hook()

        def h1(a):
            pass

        class A:
            def bound(self, a):
                pass

        a = A()
        hook.add_handler(h1)
        hook.add_handler(a.bound)
        self.assertIn(h1, hook)
        self.assertIn(a.bound, hook)
        self.assertNotIn(lambda x: None, hook)

    def test_02_handlers_property_shape(self) -> None:
        """handlers returns descriptor dicts {fn, logger, idx, with_topic}."""
        hook = self._hook()

        def h1(a):
            pass

        def h2(a, topic=None):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)
        handlers = hook.handlers
        self.assertEqual(len(handlers), 2)
        self.assertEqual(handlers[0]["fn"], h1)
        self.assertEqual(handlers[0]["idx"], 0)
        self.assertFalse(handlers[0]["with_topic"])
        self.assertEqual(handlers[1]["fn"], h2)
        self.assertEqual(handlers[1]["idx"], 1)
        self.assertTrue(handlers[1]["with_topic"])
        self.assertTrue(all("logger" in h for h in handlers))

        # iteration mirrors handlers
        self.assertEqual(list(hook), hook.handlers)

    def test_03_with_topic_detection(self) -> None:
        """Handlers accepting a 'topic' param or **kwargs are with-topic."""
        hook = self._hook()

        def h_topic(a, topic=None):
            pass

        def h_var_kw(a, **kw):
            pass

        def h_bare(a):
            pass

        hook.add_handler(h_topic)
        hook.add_handler(h_var_kw)
        hook.add_handler(h_bare)
        flags = [h["with_topic"] for h in hook.handlers]
        self.assertEqual(flags, [True, True, False])
        # Toolkit agrees
        self.assertTrue(EventTestToolkit.get_callable_with_topic(hook, 0))
        self.assertTrue(EventTestToolkit.get_callable_with_topic(hook, 1))
        self.assertFalse(EventTestToolkit.get_callable_with_topic(hook, 2))

    def test_04_iadd_deduplicates(self) -> None:
        """+= deduplicates (add_handler with deduplicate=True)."""
        hook = self._hook()
        calls = {"n": 0}

        def h(a, **kw):
            calls["n"] += 1

        hook += h
        hook += h
        self.assertEqual(len(hook), 1)
        hook.trigger(make_payload(args=(1,))[0])
        self.assertEqual(calls["n"], 1)

    def test_05_add_handler_deduplicate_flag(self) -> None:
        """add_handler(deduplicate=True) skips existing; False allows duplicates."""
        hook = self._hook()

        def h(a):
            pass

        hook.add_handler(h, deduplicate=True)
        hook.add_handler(h, deduplicate=True)
        self.assertEqual(len(hook), 1)

        hook.add_handler(h, deduplicate=False)
        self.assertEqual(len(hook), 2)
        # remove removes the first occurrence only
        hook.remove_handler(h)
        self.assertEqual(len(hook), 1)

    def test_06_isub(self) -> None:
        """-= removes a handler."""
        hook = self._hook()

        def h(a):
            pass

        hook += h
        hook -= h
        self.assertEqual(len(hook), 0)
        self.assertNotIn(h, hook)

    def test_07_remove_missing_logs_warning(self) -> None:
        """remove_handler on an unknown callable logs a warning, no raise."""
        hook = self._hook()

        def h(a):
            pass

        with self.assertLogs(logging.getLogger("EventEngine.Event"), level="WARNING") as cm:
            hook.remove_handler(h)
        self.assertTrue(any("not exist" in m for m in cm.output))

    def test_08_clear(self) -> None:
        """clear empties the hook, both at Python and C level."""
        hook = self._hook()

        def h1(a):
            pass

        def h2(a, **kw):
            pass

        hook.add_handler(h1)
        hook.add_handler(h2)
        hook.clear()
        self.assertEqual(len(hook), 0)
        self.assertEqual(EventTestToolkit.get_n_callbacks(hook), 0)
        self.assertEqual(EventTestToolkit.get_callable_count(hook), 0)

    def test_09_non_callable_raises(self) -> None:
        """add_handler rejects non-callables (the signature inspect raises TypeError)."""
        hook = self._hook()
        with self.assertRaises((ValueError, TypeError)):
            hook.add_handler("not callable")


class TestEventHookTrigger(unittest.TestCase):
    """Contract: dispatch conventions and error isolation."""

    def test_00_no_topic_handlers_receive_args_kwargs(self) -> None:
        """No-topic handlers are called with payload args/kwargs only."""
        payload, _ = make_payload(args=("a", 123), kwargs={"d": 432})
        received = {}

        def handler(a, b, d):
            received.update(a=a, b=b, d=d)

        hook = EventHook(Topic("trigger.basic"))
        hook.add_handler(handler)
        hook.trigger(payload)
        self.assertEqual(received, {"a": "a", "b": 123, "d": 432})

    def test_01_with_topic_handler_receives_topic_kwarg(self) -> None:
        """With-topic handlers receive the topic via kwargs."""
        payload, topic = make_payload(args=(1,), kwargs={})
        received = {}

        def handler(a, topic=None, **kw):
            received["topic"] = topic
            received["a"] = a

        hook = EventHook(Topic("trigger.topic"))
        hook.add_handler(handler)
        hook.trigger(payload)
        self.assertEqual(received["topic"].value, topic.value)
        self.assertEqual(received["a"], 1)

    def test_02_invocation_order(self) -> None:
        """No-topic handlers run first (registration order), then with-topic."""
        payload, topic = make_payload(args=("a", 123, {}), kwargs={"d": 432})
        call_order = []

        def no_topic_0(a, b, c, d):
            call_order.append("no_topic_0")

        def no_topic_1(a, b, c, d):
            call_order.append("no_topic_1")

        def with_topic(a, b, c, d, topic=None):
            call_order.append("with_topic")

        hook = EventHook(topic)
        hook.add_handler(no_topic_0)
        hook.add_handler(no_topic_1)
        hook.add_handler(with_topic)
        hook.trigger(payload)
        self.assertEqual(call_order, ["no_topic_0", "no_topic_1", "with_topic"])

    def test_03_handler_exception_does_not_propagate(self) -> None:
        """Handler exceptions are logged internally, not propagated."""
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)

        def failing(a):
            raise ValueError("boom")

        def normal(a):
            pass

        hook.add_handler(failing)
        hook.add_handler(normal)
        with self.assertLogs(hook.logger, level="ERROR"):
            hook.trigger(payload)  # must not raise

    def test_04_multiple_exceptions_isolated(self) -> None:
        """Later handlers still run after earlier ones raise."""
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)
        ran = []

        def fail_value(a):
            raise ValueError("v")

        def fail_runtime(a):
            raise RuntimeError("r")

        def ok(a):
            ran.append(a)

        hook.add_handler(fail_value)
        hook.add_handler(fail_runtime)
        hook.add_handler(ok)
        with self.assertLogs(hook.logger, level="ERROR"):
            hook.trigger(payload)
        self.assertEqual(ran, [1])

    def test_05_payload_immutability(self) -> None:
        """Handlers cannot mutate the payload's args/kwargs."""
        original_args = (1, 2, 3)
        original_kwargs = {"x": 1}
        payload, topic = make_payload(args=original_args, kwargs=original_kwargs)
        hook = EventHook(topic)

        def mutating(a, b, c, **kw):
            kw["z"] = 999

        hook.add_handler(mutating)
        hook.trigger(payload)
        self.assertEqual(payload.args, original_args)
        self.assertEqual(payload.kwargs, original_kwargs)
        self.assertNotIn("z", payload.kwargs)

    def test_06_call_operator_alias(self) -> None:
        """hook(payload) is an alias for trigger."""
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHook(topic)
        called = []

        def handler(a):
            called.append(a)

        hook.add_handler(handler)
        hook(payload)
        self.assertEqual(called, [1])

    def test_07_repr(self) -> None:
        """repr carries hook class, topic and handler count."""
        hook = EventHook(Topic("trigger.repr"))
        self.assertIn("EventHook", repr(hook))
        self.assertIn("trigger.repr", repr(hook))


class TestEventHookEx(unittest.TestCase):
    """Contract: EventHookEx adds hook-level stats via C watchers."""

    def test_00_stats_dict_shape(self) -> None:
        """stats is a dict with n_calls / timestamps / elapsed_seconds."""
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHookEx(topic)
        stats = hook.stats
        self.assertEqual(stats["n_calls"], 0)
        self.assertIn("last_call_start", stats)
        self.assertIn("last_call_complete", stats)
        self.assertEqual(stats["elapsed_seconds"], 0.0)

    def test_01_stats_accumulate_over_triggers(self) -> None:
        """n_calls and elapsed_seconds accumulate across trigger calls."""
        payload, topic = make_payload(args=(1,), kwargs={})
        hook = EventHookEx(topic)

        def slow(a):
            time.sleep(0.01)

        hook.add_handler(slow)
        hook.trigger(payload)
        hook.trigger(payload)

        stats = hook.stats
        self.assertEqual(stats["n_calls"], 2)
        self.assertGreaterEqual(stats["elapsed_seconds"], 0.02)
        self.assertGreater(stats["last_call_complete"], 0)
        self.assertGreaterEqual(stats["last_call_complete"], stats["last_call_start"])

    def test_02_watchers_registered(self) -> None:
        """EventHookEx registers one pre and one post watcher at C level."""
        hook = EventHookEx(Topic("hookex.watchers"))
        self.assertEqual(EventTestToolkit.get_n_pre_watchers(hook), 1)
        self.assertEqual(EventTestToolkit.get_n_post_watchers(hook), 1)
        # plain hook has none
        plain = EventHook(Topic("hookex.plain"))
        self.assertEqual(EventTestToolkit.get_n_pre_watchers(plain), 0)
        self.assertEqual(EventTestToolkit.get_n_post_watchers(plain), 0)

    def test_03_stats_zero_on_new_hook(self) -> None:
        """A fresh hook has zeroed stats."""
        hook = EventHookEx(Topic("hookex.fresh"))
        stats = hook.stats
        self.assertEqual(stats["n_calls"], 0)
        self.assertEqual(stats["elapsed_seconds"], 0.0)


if __name__ == "__main__":
    logging.disable(logging.NOTSET)
    unittest.main(verbosity=2)
