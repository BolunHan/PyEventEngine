"""Contract tests for the C-engine-backed Cython engine (event_engine.capi.c_engine_ex).

EventEngineEx is the standalone engine class here: it combines the full engine
core (hook registry, message queue, C-side trigger dispatch loop) with timers
backed by the C ``evt_engine_timer_ctx``. Internal C queue / hook-map / timer
state is verified through the ``EngineTestToolkit`` toolkit.
"""

import threading
import time
import unittest
from datetime import datetime, timedelta

from event_engine.capi import EventHook, MessagePayload, Topic
from event_engine.capi.c_engine_ex import Empty, EventEngineEx, EventHookMap, Full, EngineTestToolkit


class TestEngineRegistry(unittest.TestCase):
    """Contract: hook registration / unregistration and introspection."""

    def test_00_initial_state(self) -> None:
        """A fresh engine has zero hooks, zero occupancy, seq_id 0, no timer."""
        engine = EventEngineEx(capacity=100)
        try:
            self.assertEqual(engine.capacity, 100)
            self.assertEqual(len(engine), 0)
            self.assertEqual(engine.occupied, 0)
            self.assertEqual(engine.seq_id, 0)
            self.assertFalse(engine.active)
            self.assertEqual(engine.timer, {})
            self.assertEqual(EngineTestToolkit.get_mq_capacity(engine), 100)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 0)
            self.assertEqual(EngineTestToolkit.get_exact_hook_map_size(engine), 0)
            self.assertEqual(EngineTestToolkit.get_generic_hook_map_size(engine), 0)
            self.assertEqual(EngineTestToolkit.get_timer_interval(engine), 0)
            self.assertIsNone(EngineTestToolkit.get_timer_payload_topic(engine))
        finally:
            engine.clear()

    def test_01_default_capacity_matches_config(self) -> None:
        """The default capacity agrees with CONFIG_VIEW."""
        from event_engine import CONFIG_VIEW

        engine = EventEngineEx()
        try:
            self.assertEqual(engine.capacity, CONFIG_VIEW["engine"]["DEFAULT_MQ_CAPACITY"])
        finally:
            engine.clear()

    def test_02_register_and_unregister_hook(self) -> None:
        """register_hook stores by topic; unregister_hook returns the same hook."""
        engine = EventEngineEx()
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
        engine = EventEngineEx()
        topic = Topic("registry.dup")
        engine.register_hook(EventHook(topic))
        try:
            with self.assertRaises(KeyError):
                engine.register_hook(EventHook(topic))
        finally:
            engine.clear()

    def test_04_unregister_missing_hook_raises_keyerror(self) -> None:
        """Unregistering an unknown topic raises KeyError."""
        engine = EventEngineEx()
        try:
            with self.assertRaises(KeyError):
                engine.unregister_hook(Topic("registry.missing"))
        finally:
            engine.clear()

    def test_05_register_handler_creates_hook(self) -> None:
        """register_handler auto-creates the hook on first use."""
        engine = EventEngineEx()
        topic = Topic("registry.auto")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            self.assertEqual(len(engine), 1)
            hook = engine.get_hook(topic)
            self.assertIsInstance(hook, EventHook)
            self.assertEqual(len(hook), 1)
        finally:
            engine.clear()

    def test_06_unregister_handler_removes_empty_hook(self) -> None:
        """Removing the last handler removes the hook from the registry."""
        engine = EventEngineEx()
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
        engine = EventEngineEx()
        from event_engine import base

        with self.assertLogs(base.LOGGER.getChild("Engine"), level="ERROR") as cm:
            engine.unregister_handler(Topic("registry.none"), lambda a: None)
        self.assertTrue(any("No EventHook registered" in m for m in cm.output))
        engine.clear()

    def test_08_generic_hook_registry(self) -> None:
        """Generic (pattern) topics land in the generic hook map."""
        engine = EventEngineEx()
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
        engine = EventEngineEx()
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

            matched = engine[exact_topic]
            self.assertEqual(len(matched), 1)
            self.assertIs(matched[0].topic, exact_topic)
            matched = engine[Topic("registry.generic")]
            self.assertEqual(len(matched), 1)
            self.assertFalse(matched[0].topic.is_exact)
        finally:
            engine.clear()

    def test_10_repr(self) -> None:
        """repr carries class name, state and capacity."""
        engine = EventEngineEx()
        try:
            self.assertIn("EventEngineEx", repr(engine))
            self.assertIn("idle", repr(engine))
        finally:
            engine.clear()

    def test_11_activate_deactivate_flags(self) -> None:
        """activate/deactivate toggle the active flag without a thread."""
        engine = EventEngineEx()
        try:
            engine.activate()
            self.assertTrue(engine.active)
            engine.deactivate()
            self.assertFalse(engine.active)
        finally:
            engine.clear()

    def test_12_hook_maps_are_bound_bytemaps(self) -> None:
        """Hook registries are EventHookMap (BoundByteMap) instances backed by the C maps."""
        engine = EventEngineEx()
        try:
            self.assertIsInstance(engine.exact_topic_hooks, EventHookMap)
            self.assertIsInstance(engine.generic_topic_hooks, EventHookMap)
            self.assertIsInstance(engine.exact_topic_hooks, dict)

            hook = EventHook(Topic("registry.bound"))
            engine.register_hook(hook)
            self.assertIs(engine.exact_topic_hooks[hook.topic.value], hook)
            self.assertEqual(list(engine.exact_topic_hooks.keys()), [hook.topic.value])
            self.assertEqual(EngineTestToolkit.get_exact_hook_map_size(engine), len(engine.exact_topic_hooks))
        finally:
            engine.clear()


class TestEngineQueue(unittest.TestCase):
    """Contract: put/get semantics, Full/Empty, queue bookkeeping."""

    def test_00_put_get_roundtrip(self) -> None:
        """put enqueues; get returns an owning payload with args/kwargs."""
        engine = EventEngineEx(capacity=8)
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
        engine = EventEngineEx(capacity=8)
        try:
            with self.assertRaises(Empty):
                engine.get(block=False)
        finally:
            engine.clear()

    def test_02_get_blocking_timeout_raises_empty(self) -> None:
        """Blocking get with a timeout raises Empty when nothing arrives."""
        engine = EventEngineEx(capacity=8)
        try:
            t0 = time.perf_counter()
            with self.assertRaises(Empty):
                engine.get(block=True, timeout=0.15)
            self.assertGreaterEqual(time.perf_counter() - t0, 0.1)
        finally:
            engine.clear()

    def test_03_put_full_raises_full(self) -> None:
        """Non-blocking put on a full queue raises Full."""
        engine = EventEngineEx(capacity=2)
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
        engine = EventEngineEx()
        try:
            with self.assertRaises(ValueError):
                engine.put(Topic("queue.+any"), 1)
            with self.assertRaises(ValueError):
                engine.publish(Topic("queue.+any"), (1,), {})
        finally:
            engine.clear()

    def test_05_publish_signature(self) -> None:
        """publish(topic, args, kwargs) mirrors put."""
        engine = EventEngineEx(capacity=8)
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
        engine = EventEngineEx(capacity=8)
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
        engine = EventEngineEx(capacity=8)
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
        engine = EventEngineEx(capacity=4)
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
    """Contract: the C-side dispatch loop delivers messages to matching hooks."""

    def _wait_for(self, event: threading.Event, timeout=3.0) -> None:
        self.assertTrue(event.wait(timeout), "timed out waiting for event")

    def test_00_start_stop_and_dispatch(self) -> None:
        """start/stop toggle active; handlers receive published messages."""
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)

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
        engine = EventEngineEx(capacity=16)
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
        engine = EventEngineEx(capacity=16)
        try:
            with self.assertLogs(engine.logger, level="WARNING"):
                engine.stop()
        finally:
            engine.clear()

    def test_10_concurrent_producers(self) -> None:
        """Messages from several producer threads are all delivered."""
        engine = EventEngineEx(capacity=256)
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

    def test_11_rapid_start_stop_cycles(self) -> None:
        """Repeated start/stop cycles leave the atomic active flag consistent."""
        engine = EventEngineEx(capacity=16)
        try:
            for _ in range(5):
                engine.start()
                self.assertTrue(engine.active)
                engine.stop()
                self.assertFalse(engine.active)
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_12_atomic_seq_id_unique_under_concurrency(self) -> None:
        """Concurrent publishes get unique, gap-free seq ids (atomic counter)."""
        engine = EventEngineEx(capacity=512)
        topic = Topic("loop.atomic.seq")
        total = 200

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            def produce(start, count):
                for i in range(start, start + count):
                    engine.put(topic, i, block=False)

            threads = [threading.Thread(target=produce, args=(0, total // 2)),
                       threading.Thread(target=produce, args=(total // 2, total // 2))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(engine.seq_id, total)
            seen = set()
            for _ in range(total):
                seen.add(engine.get(block=False).seq_id)
            self.assertEqual(seen, set(range(total)))
        finally:
            if engine.active:
                engine.stop()
            engine.clear()


class TestEngineTimers(unittest.TestCase):
    """Contract: timers backed by the C evt_engine_timer_ctx (sleep loop)."""

    def _stop_engine(self, engine) -> None:
        if engine.active:
            engine.stop()
        engine.clear()

    def _wait_for(self, event: threading.Event, timeout=5.0) -> None:
        self.assertTrue(event.wait(timeout), "timed out waiting for event")

    def test_00_get_timer_requires_active_engine(self) -> None:
        """get_timer before start raises RuntimeError."""
        engine = EventEngineEx(capacity=64)
        try:
            with self.assertRaises(RuntimeError):
                engine.get_timer(interval=0.1)
        finally:
            engine.clear()

    def test_01_custom_interval_timer(self) -> None:
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
            self._wait_for(done)
            engine.stop()

            self.assertGreaterEqual(len(ticks), 3)
            for tick in ticks:
                self.assertEqual(tick["interval"], 0.05)
                self.assertIn("trigger_time", tick)
                self.assertIsInstance(tick["trigger_time"], datetime)
        finally:
            self._stop_engine(engine)

    def test_02_second_timer(self) -> None:
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
            self._wait_for(done, timeout=3.0)
            engine.stop()
            self.assertEqual(ticks[0]["interval"], 1)
            # Static kwargs contract: interval + injected topic (no per-tick fields)
        finally:
            self._stop_engine(engine)

    def test_03_timer_deduplication(self) -> None:
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

    def test_04_stop_halts_tick_delivery(self) -> None:
        """Timers fire through the dispatch loop; stop() halts delivery."""
        engine = EventEngineEx(capacity=64)
        ticks = []

        def timer_handler(**kw):
            ticks.append(kw)

        try:
            engine.start()
            timer_topic = engine.get_timer(interval=0.1)
            engine.register_handler(timer_topic, timer_handler)
            time.sleep(1.2)
            engine.stop()
            n_after_stop = len(ticks)
            self.assertGreater(n_after_stop, 0)
            time.sleep(1.2)
            self.assertEqual(len(ticks), n_after_stop)
        finally:
            engine.clear()

    def test_05_clear_releases_timer_ctx(self) -> None:
        """clear() releases the C timer ctx and removes timer threads."""
        engine = EventEngineEx(capacity=64)
        try:
            engine.start()
            engine.get_timer(interval=0.1)
            engine.stop()
            engine.clear()
            self.assertEqual(engine.timer, {})
            self.assertEqual(EngineTestToolkit.get_timer_interval(engine), 0)
            self.assertIsNone(EngineTestToolkit.get_timer_payload_topic(engine))
        finally:
            engine.clear()

    def test_06_timer_payload_routed_to_handler(self) -> None:
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
            self._wait_for(done)
            engine.stop()
            args, interval = received[0]
            self.assertEqual(args, ())
            self.assertEqual(interval, 0.05)
        finally:
            self._stop_engine(engine)

    def test_07_timer_ctx_registered_in_c_engine(self) -> None:
        """get_timer populates the C timer ctx (interval + payload topic)."""
        engine = EventEngineEx(capacity=64)
        try:
            engine.start()
            timer_topic = engine.get_timer(interval=0.07)
            self.assertEqual(EngineTestToolkit.get_timer_interval(engine), 0.07)
            self.assertEqual(EngineTestToolkit.get_timer_task_count(engine), 1)
            self.assertEqual(EngineTestToolkit.get_timer_payload_topic(engine).value, timer_topic.value)
            engine.stop()
        finally:
            self._stop_engine(engine)

    def test_08_timer_tick_delivery_rate(self) -> None:
        """Hooked timers deliver ticks at roughly the configured rate."""
        engine = EventEngineEx(capacity=256)
        ticks = []

        def timer_handler(**kw):
            ticks.append(kw)

        try:
            engine.start()
            timer_topic = engine.get_timer(interval=0.1)
            engine.register_handler(timer_topic, timer_handler)
            time.sleep(2.2)
            engine.stop()

            # Ticks fire on timer-scheduled wake-ups (the loop caps its wait
            # at the next tick), so the rate tracks the configured interval.
            n_ticks = len(ticks)
            self.assertGreater(n_ticks, 0)
            rate = n_ticks / 2.2
            self.assertGreater(rate, 2.0)    # at least ~20% of the 10 Hz target
            self.assertLess(rate, 20.0)      # and at most 2x over
            for tick in ticks:
                self.assertEqual(tick["interval"], 0.1)
        finally:
            self._stop_engine(engine)

    def test_09_timer_ticks_advance_seq_id(self) -> None:
        """Each timer tick consumes a monotonic seq id from the C engine."""
        engine = EventEngineEx(capacity=64)
        ticks = []
        done = threading.Event()
        n_ticks = 10

        def timer_handler(**kw):
            ticks.append(kw)
            if len(ticks) >= n_ticks:
                done.set()

        try:
            engine.start()
            timer_topic = engine.get_timer(interval=0.05)
            engine.register_handler(timer_topic, timer_handler)
            self._wait_for(done)
            engine.stop()

            # Ticks dispatch directly (never queued); one extra may land
            # between the done signal and the stop.
            self.assertGreaterEqual(len(ticks), n_ticks)
            self.assertGreaterEqual(engine.seq_id, n_ticks)
            self.assertEqual(EngineTestToolkit.get_mq_count(engine), 0)
        finally:
            self._stop_engine(engine)

    def test_10_timer_sleep_loop_cpu_overhead_is_low(self) -> None:
        """An idle running timer burns negligible CPU (sleep loop)."""
        engine = EventEngineEx(capacity=256)

        def timer_handler(**kw):
            pass

        try:
            engine.start()
            timer_topic = engine.get_timer(interval=0.05)
            engine.register_handler(timer_topic, timer_handler)

            cpu0 = time.process_time()
            time.sleep(2.0)
            cpu_delta = time.process_time() - cpu0
            engine.stop()

            # The sleep loop should consume well under half a second of CPU
            # over 2 wall-clock seconds of 20 Hz ticking.
            self.assertLess(cpu_delta, 0.5, f"timer burned {cpu_delta:.3f}s CPU over 2s")
        finally:
            self._stop_engine(engine)

    def test_11_timer_replacement_takes_over(self) -> None:
        """Registering a different interval replaces the previous timer ctx."""
        engine = EventEngineEx(capacity=256)
        done = threading.Event()

        def timer_handler(**kw):
            if kw.get("interval") == 0.05:
                done.set()

        try:
            engine.start()
            old_topic = engine.get_timer(interval=0.1)
            engine.register_handler(old_topic, timer_handler)

            new_topic = engine.get_timer(interval=0.05)
            engine.register_handler(new_topic, timer_handler)

            self.assertNotEqual(old_topic.value, new_topic.value)
            self.assertEqual(EngineTestToolkit.get_timer_interval(engine), 0.05)
            self.assertEqual(EngineTestToolkit.get_timer_task_count(engine), 1)
            self.assertEqual(EngineTestToolkit.get_timer_payload_topic(engine).value, new_topic.value)
            self._wait_for(done, timeout=5.0)
            engine.stop()
        finally:
            self._stop_engine(engine)

    def test_12_multiple_timers_fire_independently(self) -> None:
        """Timers with different intervals tick at their own cadence.

        Registered through the raw C interface (get_timer replaces, so it
        cannot build multi-timer scenarios). A shared-schedule implementation
        collapses all cadences to the last-registered interval, so the ratio
        checks fail loudly on misfire.
        """
        engine = EventEngineEx(capacity=256)
        intervals = (0.05, 0.2, 1.0)
        ticks = {interval: [] for interval in intervals}
        payloads = []
        first_tick = threading.Event()

        def make_handler(interval):
            def handler(**kw):
                ticks[interval].append(kw)
                first_tick.set()
            return handler

        try:
            engine.start()
            for interval in intervals:
                topic = Topic.join(['EventEngine', 'Internal', 'Timer', str(interval)])
                engine.register_handler(topic, make_handler(interval))
                # Keep the payload wrappers alive for the whole test — the
                # C task only borrows the pypayload args pointer.
                payload = EngineTestToolkit.register_raw_timer(engine, topic, interval)
                self.assertIsNotNone(payload)
                payloads.append(payload)

            self.assertEqual(EngineTestToolkit.get_timer_task_count(engine), len(intervals))
            # One ctx per interval, ordered by next_due (aligned boundaries)
            self.assertEqual(EngineTestToolkit.get_timer_intervals(engine), list(intervals))

            # The first tick may wait out the loop's initial queue-timeout
            # sleep (registrations happen after start); measure steady state.
            self._wait_for(first_tick, timeout=3.0)
            time.sleep(2.0)
            engine.stop()

            n_fast, n_mid, n_slow = (len(ticks[interval]) for interval in intervals)
            # 0.05s ≈ 4x the 0.2s cadence ≈ 20x the 1.0s cadence
            self.assertGreaterEqual(n_fast, 15, f'fast timer delivered {n_fast} ticks')
            self.assertGreaterEqual(n_slow, 1, f'slow timer delivered {n_slow} ticks')
            self.assertGreater(n_fast, 3 * n_mid, f'tick ratio collapsed: {n_fast} vs {n_mid}')
            self.assertGreater(n_mid, 3 * n_slow, f'tick ratio collapsed: {n_mid} vs {n_slow}')
        finally:
            self._stop_engine(engine)

    def test_13_timer_topic_duplicate_filtered(self) -> None:
        """Re-registering a timer topic is rejected — no override, no double fire."""
        engine = EventEngineEx(capacity=64)
        try:
            engine.start()
            topic = Topic('test.dup.timer')
            engine.register_handler(topic, lambda **kw: None)

            payload = EngineTestToolkit.register_raw_timer(engine, topic, 0.1)
            self.assertIsNotNone(payload)

            duplicate = EngineTestToolkit.register_raw_timer(engine, topic, 0.1)
            self.assertIsNone(duplicate)
            self.assertEqual(EngineTestToolkit.get_timer_task_count(engine), 1)
            self.assertEqual(EngineTestToolkit.get_timer_payload_topic(engine).value, topic.value)
            engine.stop()
        finally:
            self._stop_engine(engine)

    def test_14_same_interval_tasks_share_ctx(self) -> None:
        """Tasks with the same interval share one ctx and fire together."""
        engine = EventEngineEx(capacity=256)
        ticks_a = []
        ticks_b = []
        first_tick = threading.Event()

        def handler_a(**kw):
            ticks_a.append(kw)
            first_tick.set()

        def handler_b(**kw):
            ticks_b.append(kw)

        try:
            engine.start()
            topic_a = Topic.join(['EventEngine', 'Timer', 'A'])
            topic_b = Topic.join(['EventEngine', 'Timer', 'B'])
            engine.register_handler(topic_a, handler_a)
            engine.register_handler(topic_b, handler_b)
            payloads = [
                EngineTestToolkit.register_raw_timer(engine, topic_a, 0.1),
                EngineTestToolkit.register_raw_timer(engine, topic_b, 0.1),
            ]
            self.assertTrue(all(payloads))

            self.assertEqual(EngineTestToolkit.get_timer_task_count(engine), 2)
            self.assertEqual(EngineTestToolkit.get_timer_intervals(engine), [0.1])  # ONE ctx

            self._wait_for(first_tick, timeout=3.0)
            time.sleep(1.0)
            engine.stop()

            # One ctx fires both topics together on every tick — counts are
            # always identical (both handlers run inside the same fire call).
            self.assertGreater(len(ticks_a), 3)
            self.assertEqual(len(ticks_a), len(ticks_b))
        finally:
            self._stop_engine(engine)


if __name__ == "__main__":
    unittest.main(verbosity=2)
