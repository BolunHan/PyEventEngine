"""Contract tests for the Cython engine layer (event_engine.capi.c_engine).

Covers EventEngine (hook registry, message queue, dispatch loop) and
EventEngineEx (timers). Internal C queue / hook-map state is verified
through the ``EngineTestToolkit`` test toolkit in ``c_engine.pyx``.
"""

import threading
import time
import unittest
from datetime import datetime, timedelta

from event_engine.capi import Empty, EventEngine, EventEngineEx, Full, MessagePayload, Topic
from event_engine.capi.c_engine import EngineTestToolkit


class TestEngineRegistry(unittest.TestCase):
    """Contract: hook registration / unregistration and introspection."""

    def test_00_initial_state(self) -> None:
        """A fresh engine has zero hooks, zero occupancy, seq_id 0."""
        engine = EventEngine(capacity=100)
        try:
            self.assertEqual(engine.capacity, 100)
            self.assertEqual(len(engine), 0)
            self.assertEqual(engine.occupied, 0)
            self.assertEqual(engine.seq_id, 0)
            self.assertFalse(engine.active)
            self.assertEqual(EngineTestToolkit.get_mq_capacity(engine), 100)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 0)
            self.assertEqual(EngineTestToolkit.get_exact_hook_map_size(engine), 0)
            self.assertEqual(EngineTestToolkit.get_generic_hook_map_size(engine), 0)
        finally:
            engine.clear()

    def test_01_default_capacity_matches_config(self) -> None:
        """The default capacity agrees with CONFIG_VIEW."""
        from event_engine import CONFIG_VIEW

        engine = EventEngine()
        try:
            self.assertEqual(engine.capacity, CONFIG_VIEW["engine"]["DEFAULT_MQ_CAPACITY"])
        finally:
            engine.clear()

    def test_02_register_and_unregister_hook(self) -> None:
        """register_hook stores by topic; unregister_hook returns the same hook."""
        engine = EventEngine()
        from event_engine.capi import EventHook

        topic = Topic("registry.hook")
        hook = EventHook(topic)
        engine.register_hook(hook)
        try:
            self.assertEqual(len(engine), 1)
            self.assertEqual(EngineTestToolkit.get_exact_hook_map_size(engine), 1)
            self.assertEqual(EngineTestToolkit.get_exact_hook_map_keys(engine), [topic.value])
            self.assertIs(engine.get_hook(topic), hook)

            retrieved = engine.unregister_hook(topic)
            self.assertIs(retrieved, hook)
            self.assertEqual(len(engine), 0)
            self.assertEqual(EngineTestToolkit.get_exact_hook_map_size(engine), 0)
        finally:
            engine.clear()

    def test_03_duplicate_hook_raises_keyerror(self) -> None:
        """Registering a second hook for the same topic raises KeyError."""
        engine = EventEngine()
        from event_engine.capi import EventHook

        topic = Topic("registry.dup")
        engine.register_hook(EventHook(topic))
        try:
            with self.assertRaises(KeyError):
                engine.register_hook(EventHook(topic))
        finally:
            engine.clear()

    def test_04_unregister_missing_hook_raises_keyerror(self) -> None:
        """Unregistering an unknown topic raises KeyError."""
        engine = EventEngine()
        try:
            with self.assertRaises(KeyError):
                engine.unregister_hook(Topic("registry.missing"))
        finally:
            engine.clear()

    def test_05_register_handler_creates_hook(self) -> None:
        """register_handler auto-creates the hook on first use."""
        engine = EventEngine()
        topic = Topic("registry.auto")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            self.assertEqual(len(engine), 1)
            hook = engine.get_hook(topic)
            self.assertIsInstance(hook, object)
            self.assertEqual(len(hook), 1)
        finally:
            engine.clear()

    def test_06_unregister_handler_removes_empty_hook(self) -> None:
        """Removing the last handler removes the hook from the registry."""
        engine = EventEngine()
        topic = Topic("registry.cleanup")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        engine.unregister_handler(topic, handler)
        self.assertEqual(len(engine), 0)
        with self.assertRaises(KeyError):
            engine.get_hook(topic)

    def test_07_unregister_handler_missing_logs_error(self) -> None:
        """Unregistering a handler from an unknown topic logs, no raise."""
        engine = EventEngine()
        from event_engine import base

        with self.assertLogs(base.LOGGER.getChild("Engine"), level="ERROR") as cm:
            engine.unregister_handler(Topic("registry.none"), lambda a: None)
        self.assertTrue(any("No EventHook registered" in m for m in cm.output))
        engine.clear()

    def test_08_generic_hook_registry(self) -> None:
        """Generic (pattern) topics land in the generic hook map."""
        engine = EventEngine()
        topic = Topic("registry.+generic")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            self.assertEqual(len(engine), 1)
            self.assertEqual(EngineTestToolkit.get_exact_hook_map_size(engine), 0)
            self.assertEqual(EngineTestToolkit.get_generic_hook_map_size(engine), 1)
            self.assertEqual(EngineTestToolkit.get_generic_hook_map_keys(engine), [topic.value])
        finally:
            engine.clear()

    def test_09_iterators(self) -> None:
        """event_hooks / topics / items / getitem reflect the registry."""
        engine = EventEngine()
        exact_topic = Topic("registry.iter.exact")

        def handler(a):
            pass

        engine.register_handler(exact_topic, handler)
        engine.register_handler(Topic("registry.{name}"), handler)
        try:
            hooks = list(engine.event_hooks())
            self.assertEqual(len(hooks), 2)
            topics = list(engine.topics())
            self.assertEqual(len(topics), 2)
            items = list(engine.items())
            self.assertEqual(len(items), 2)
            for topic, hook in items:
                self.assertIs(hook.topic, topic)

            # getitem: exact topic returns the exact hook
            matched = engine[exact_topic]
            self.assertEqual(len(matched), 1)
            self.assertIs(matched[0].topic, exact_topic)
            # getitem: published topic matching generic pattern returns the generic hook
            # registry.{name} has 2 parts, so the probe must also have 2 parts
            matched = engine[Topic("registry.generic")]
            self.assertEqual(len(matched), 1)
            self.assertFalse(matched[0].topic.is_exact)
        finally:
            engine.clear()

    def test_10_repr(self) -> None:
        """repr carries class name, state and capacity."""
        engine = EventEngine()
        try:
            self.assertIn("EventEngine", repr(engine))
            self.assertIn("idle", repr(engine))
        finally:
            engine.clear()

    def test_11_activate_deactivate_flags(self) -> None:
        """activate/deactivate toggle the active flag without a thread."""
        engine = EventEngine()
        try:
            engine.activate()
            self.assertTrue(engine.active)
            engine.deactivate()
            self.assertFalse(engine.active)
        finally:
            engine.clear()


class TestEngineQueue(unittest.TestCase):
    """Contract: put/get semantics, Full/Empty, queue bookkeeping."""

    def test_00_put_get_roundtrip(self) -> None:
        """put enqueues; get returns an owning payload with args/kwargs."""
        engine = EventEngine(capacity=8)
        topic = Topic("queue.roundtrip")

        def handler(a, b):
            pass

        engine.register_handler(topic, handler)
        try:
            engine.put(topic, 1, 2, block=False)
            self.assertEqual(engine.occupied, 1)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 1)

            payload = engine.get(block=False)
            self.assertIsInstance(payload, MessagePayload)
            self.assertTrue(payload.owner)
            self.assertEqual(payload.args, (1, 2))
            self.assertEqual(payload.topic.value, topic.value)
            self.assertEqual(engine.occupied, 0)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 0)
        finally:
            engine.clear()

    def test_01_get_empty_raises_empty(self) -> None:
        """Non-blocking get on an empty queue raises Empty."""
        engine = EventEngine(capacity=8)
        try:
            with self.assertRaises(Empty):
                engine.get(block=False)
        finally:
            engine.clear()

    def test_02_get_blocking_timeout_raises_empty(self) -> None:
        """Blocking get with a timeout raises Empty when nothing arrives."""
        engine = EventEngine(capacity=8)
        try:
            t0 = time.perf_counter()
            with self.assertRaises(Empty):
                engine.get(block=True, timeout=0.15)
            self.assertGreaterEqual(time.perf_counter() - t0, 0.1)
        finally:
            engine.clear()

    def test_03_put_full_raises_full(self) -> None:
        """Non-blocking put on a full queue raises Full."""
        engine = EventEngine(capacity=2)
        topic = Topic("queue.full")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            engine.put(topic, 1, block=False)
            engine.put(topic, 2, block=False)
            with self.assertRaises(Full):
                engine.put(topic, 3, block=False)
        finally:
            engine.clear()

    def test_04_put_nonexact_topic_raises_valueerror(self) -> None:
        """Publishing on a non-exact topic raises ValueError."""
        engine = EventEngine()
        try:
            with self.assertRaises(ValueError):
                engine.put(Topic("queue.+any"), 1)
            with self.assertRaises(ValueError):
                engine.publish(Topic("queue.+any"), (1,), {})
        finally:
            engine.clear()

    def test_05_publish_signature(self) -> None:
        """publish(topic, args, kwargs) mirrors put."""
        engine = EventEngine(capacity=8)
        topic = Topic("queue.publish")

        def handler(a, **kw):
            pass

        engine.register_handler(topic, handler)
        try:
            engine.publish(topic, (1, 2), {"x": 3}, block=False)
            payload = engine.get(block=False)
            self.assertEqual(payload.args, (1, 2))
            self.assertEqual(payload.kwargs, {"x": 3})
        finally:
            engine.clear()

    def test_06_payload_kwargs_with_topic_via_engine(self) -> None:
        """A payload retrieved via get carries topic in kwargs_with_topic."""
        engine = EventEngine(capacity=8)
        topic = Topic("queue.topic.kw")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            engine.put(topic, 1, x=2, block=False)
            payload = engine.get(block=False)
            aggregated = payload.kwargs_with_topic
            self.assertEqual(aggregated["x"], 2)
            self.assertEqual(aggregated["topic"].value, topic.value)
        finally:
            engine.clear()

    def test_07_seq_id_monotonic(self) -> None:
        """seq_id increments per put; payloads carry the value at put time."""
        engine = EventEngine(capacity=8)
        topic = Topic("queue.seqid")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            seqs = []
            for i in range(3):
                engine.put(topic, i, block=False)
                seqs.append(engine.get(block=False).seq_id)
            self.assertEqual(seqs, [0, 1, 2])
            self.assertEqual(engine.seq_id, 3)
        finally:
            engine.clear()

    def test_08_queue_state_transitions(self) -> None:
        """Toolkit head/tail/count stay consistent across put/get cycles."""
        engine = EventEngine(capacity=4)
        topic = Topic("queue.state")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            for i in range(3):
                engine.put(topic, i, block=False)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 3)
            self.assertEqual(engine.occupied, 3)

            engine.get(block=False)
            engine.get(block=False)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 1)

            head = EngineTestToolkit.get_mq_head(engine)
            tail = EngineTestToolkit.get_mq_tail(engine)
            self.assertLess(head, 4)
            self.assertLess(tail, 4)

            engine.get(block=False)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 0)
            self.assertEqual(EngineTestToolkit.get_mq_head(engine), EngineTestToolkit.get_mq_tail(engine))
        finally:
            engine.clear()


class TestEngineLoop(unittest.TestCase):
    """Contract: the dispatch loop delivers messages to matching hooks."""

    def _wait_for(self, event: threading.Event, timeout=3.0) -> None:
        self.assertTrue(event.wait(timeout), "timed out waiting for event")

    def test_00_start_stop_and_dispatch(self) -> None:
        """start/stop toggle active; handlers receive published messages."""
        engine = EventEngine(capacity=16)
        topic = Topic("loop.basic")
        received = []
        done = threading.Event()

        def handler(a):
            received.append(a)
            done.set()

        engine.register_handler(topic, handler)
        try:
            engine.start()
            self.assertTrue(engine.active)
            engine.put(topic, 42)
            self._wait_for(done)
            engine.stop()
            self.assertFalse(engine.active)
            self.assertEqual(received, [42])
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_01_multiple_handlers_same_topic(self) -> None:
        """All handlers on a topic fire, in registration order."""
        engine = EventEngine(capacity=16)
        topic = Topic("loop.multi.handler")
        results = []
        done = threading.Event()

        def h1(a):
            results.append(a)

        def h2(a):
            results.append(a * 2)

        engine.register_handler(topic, h1)
        engine.register_handler(topic, h2)
        try:
            engine.start()
            engine.put(topic, 5)
            time.sleep(0.2)
            engine.stop()
            self.assertEqual(results, [5, 10])
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_02_multiple_topics(self) -> None:
        """Messages route to the correct topic's handlers."""
        engine = EventEngine(capacity=16)
        topic1 = Topic("loop.t1")
        topic2 = Topic("loop.t2")
        results = {"t1": [], "t2": []}
        done = threading.Event()

        def h1(a):
            results["t1"].append(a)
            done.set()

        def h2(a):
            results["t2"].append(a)
            done.set()

        engine.register_handler(topic1, h1)
        engine.register_handler(topic2, h2)
        try:
            engine.start()
            engine.put(topic1, "x")
            engine.put(topic2, "y")
            self._wait_for(done)
            time.sleep(0.1)
            engine.stop()
            self.assertEqual(results, {"t1": ["x"], "t2": ["y"]})
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_03_generic_topic_routing(self) -> None:
        """Messages published on an exact topic reach generic pattern hooks."""
        engine = EventEngine(capacity=16)
        generic = Topic("order.{name}.status")
        published = Topic("order.new.status")
        received = []
        done = threading.Event()

        def handler(a, topic=None, **kw):
            received.append((a, topic.value))
            done.set()

        engine.register_handler(generic, handler)
        try:
            engine.start()
            engine.put(published, 7)
            self._wait_for(done)
            engine.stop()
            self.assertEqual(received, [(7, "order.new.status")])
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_04_exact_and_generic_both_fire(self) -> None:
        """An exact hook and a matching generic hook both receive the message."""
        engine = EventEngine(capacity=16)
        exact = Topic("route.data")
        generic = Topic("route.{name}")
        received = []
        done = threading.Event()

        def handler(tag):
            def impl(a, topic=None, **kw):
                received.append((tag, a))
                done.set()

            return impl

        engine.register_handler(exact, handler("exact"))
        engine.register_handler(generic, handler("generic"))
        try:
            engine.start()
            engine.put(exact, 1)
            self._wait_for(done)
            time.sleep(0.1)
            engine.stop()
            self.assertEqual(sorted(received), [("exact", 1), ("generic", 1)])
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_05_handler_exception_does_not_crash_engine(self) -> None:
        """A raising handler does not stop the loop; later handlers still run."""
        engine = EventEngine(capacity=16)
        topic = Topic("loop.error")
        ran = []
        done = threading.Event()

        def failing(a):
            raise ValueError("engine test")

        def normal(a):
            ran.append(a)
            done.set()

        engine.register_handler(topic, failing)
        engine.register_handler(topic, normal)
        try:
            engine.start()
            engine.put(topic, 42)
            self._wait_for(done)
            engine.stop()
            self.assertEqual(ran, [42])
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_06_clear_only_when_stopped(self) -> None:
        """clear() while running logs an error and keeps hooks."""
        engine = EventEngine(capacity=16)
        topic = Topic("loop.clear")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            engine.start()
            with self.assertLogs(engine.logger, level="ERROR"):
                engine.clear()
            self.assertEqual(len(engine), 1)
            engine.stop()

            engine.clear()
            self.assertEqual(len(engine), 0)
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_07_clear_resets_hook_maps(self) -> None:
        """clear() empties both exact and generic hook maps."""
        engine = EventEngine(capacity=16)

        def handler(a):
            pass

        engine.register_handler(Topic("loop.clear.exact"), handler)
        engine.register_handler(Topic("loop.+generic"), handler)
        engine.clear()
        self.assertEqual(len(engine), 0)
        self.assertEqual(EngineTestToolkit.get_exact_hook_map_size(engine), 0)
        self.assertEqual(EngineTestToolkit.get_generic_hook_map_size(engine), 0)

    def test_08_start_twice_warns(self) -> None:
        """start() on an active engine logs a warning and stays single-threaded."""
        engine = EventEngine(capacity=16)
        try:
            engine.start()
            with self.assertLogs(engine.logger, level="WARNING"):
                engine.start()
            engine.stop()
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_09_stop_when_idle_warns(self) -> None:
        """stop() on an idle engine logs a warning."""
        engine = EventEngine(capacity=16)
        try:
            with self.assertLogs(engine.logger, level="WARNING"):
                engine.stop()
        finally:
            engine.clear()

    def test_10_concurrent_producers(self) -> None:
        """Messages from several producer threads are all delivered."""
        engine = EventEngine(capacity=256)
        topic = Topic("loop.concurrent")
        total = 200
        results = []
        done = threading.Event()

        def handler(a):
            results.append(a)
            if len(results) >= total:
                done.set()

        engine.register_handler(topic, handler)
        try:
            engine.start()

            def produce(start, count):
                for i in range(start, start + count):
                    engine.put(topic, i)

            threads = [threading.Thread(target=produce, args=(0, total // 2)),
                       threading.Thread(target=produce, args=(total // 2, total // 2))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self._wait_for(done, timeout=10.0)
            engine.stop()
            self.assertEqual(len(results), total)
            self.assertEqual(set(results), set(range(total)))
        finally:
            if engine.active:
                engine.stop()
            engine.clear()


class TestEventEngineEx(unittest.TestCase):
    """Contract: EventEngineEx timer support."""

    def _stop_engine(self, engine) -> None:
        if engine.active:
            engine.stop()
        engine.clear()

    def test_00_initialization_and_repr(self) -> None:
        """EventEngineEx initializes like EventEngine with an empty timer dict."""
        engine = EventEngineEx(capacity=64)
        try:
            self.assertEqual(engine.capacity, 64)
            self.assertIsInstance(engine, EventEngine)
            self.assertEqual(engine.timer, {})
            self.assertIn("EventEngineEx", repr(engine))
        finally:
            engine.clear()

    def test_01_get_timer_requires_active_engine(self) -> None:
        """get_timer before start raises RuntimeError."""
        engine = EventEngineEx(capacity=64)
        try:
            with self.assertRaises(RuntimeError):
                engine.get_timer(interval=0.1)
        finally:
            engine.clear()

    def test_02_custom_interval_timer(self) -> None:
        """A custom-interval timer publishes repeatedly with interval kwargs."""
        engine = EventEngineEx(capacity=64)
        ticks = []
        done = threading.Event()

        def timer_handler(**kw):
            ticks.append(kw)
            if len(ticks) >= 3:
                done.set()

        try:
            engine.start()
            timer_topic = engine.get_timer(interval=0.05)
            engine.register_handler(timer_topic, timer_handler)
            self.assertTrue(done.wait(5.0), "timer did not fire 3 times")
            engine.stop()

            self.assertGreaterEqual(len(ticks), 3)
            for tick in ticks:
                self.assertEqual(tick["interval"], 0.05)
                self.assertIn("trigger_time", tick)
                self.assertIsInstance(tick["trigger_time"], datetime)
            # payloads carry no positional args
        finally:
            self._stop_engine(engine)

    def test_03_second_timer(self) -> None:
        """interval=1 uses the second timer topic."""
        engine = EventEngineEx(capacity=64)
        ticks = []
        done = threading.Event()

        def timer_handler(**kw):
            ticks.append(kw)
            done.set()

        try:
            engine.start()
            timer_topic = engine.get_timer(interval=1)
            self.assertEqual(timer_topic.value, "EventEngine.Internal.Timer.Second")
            engine.register_handler(timer_topic, timer_handler)
            self.assertTrue(done.wait(3.0), "second timer did not fire")
            engine.stop()
            self.assertEqual(ticks[0]["interval"], 1)
            self.assertIn("timestamp", ticks[0])
        finally:
            self._stop_engine(engine)

    def test_04_timer_deduplication(self) -> None:
        """get_timer with the same interval returns the same topic and one thread."""
        engine = EventEngineEx(capacity=64)
        try:
            engine.start()
            t1 = engine.get_timer(interval=0.1)
            t2 = engine.get_timer(interval=0.1)
            self.assertEqual(t1.value, t2.value)
            self.assertEqual(len(engine.timer), 1)
            engine.stop()
        finally:
            self._stop_engine(engine)

    def test_05_stop_joins_timer_threads(self) -> None:
        """stop() waits for timer threads to terminate."""
        engine = EventEngineEx(capacity=64)
        try:
            engine.start()
            engine.get_timer(interval=0.1)
            timer_thread = next(iter(engine.timer.values()))
            self.assertTrue(timer_thread.is_alive())
            engine.stop()
            self.assertFalse(timer_thread.is_alive())
        finally:
            engine.clear()

    def test_06_clear_stops_timers(self) -> None:
        """clear() joins and removes timer threads."""
        engine = EventEngineEx(capacity=64)
        try:
            engine.start()
            engine.get_timer(interval=0.1)
            engine.stop()
            engine.clear()
            self.assertEqual(engine.timer, {})
        finally:
            engine.clear()

    def test_07_timer_payload_routed_to_handler(self) -> None:
        """Timer topics are publishable exact topics with no args."""
        engine = EventEngineEx(capacity=64)
        received = []
        done = threading.Event()

        def timer_handler(*args, **kw):
            received.append((args, kw.get("interval")))
            done.set()

        try:
            engine.start()
            timer_topic = engine.get_timer(interval=0.05)
            engine.register_handler(timer_topic, timer_handler)
            self.assertTrue(done.wait(5.0), "timer did not fire")
            engine.stop()
            args, interval = received[0]
            self.assertEqual(args, ())
            self.assertEqual(interval, 0.05)
        finally:
            self._stop_engine(engine)


if __name__ == "__main__":
    unittest.main(verbosity=2)
