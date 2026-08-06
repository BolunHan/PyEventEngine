"""Contract tests for the fallback engine (event_engine.capi.fallback_engine).

The fallback engine is the pure-Python EventEngine used on platforms where
the compiled ``c_engine`` module is unavailable (e.g. Windows source
checkouts). It must satisfy the same engine contract as the Cython engine —
this module guarantees that with the same scenarios used in the capi suite.
"""

import threading
import time
import unittest

from event_engine.capi import EventEngineEx, Topic
from event_engine.capi.fallback_engine import Empty, Full, EventEngine


class TestFallbackEngineRegistry(unittest.TestCase):
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
        finally:
            engine.clear()

    def test_01_register_and_unregister_hook(self) -> None:
        """register_hook stores by topic; unregister_hook returns the same hook."""
        engine = EventEngine()
        from event_engine.capi import EventHook

        topic = Topic("fallback.registry.hook")
        hook = EventHook(topic)
        engine.register_hook(hook)
        try:
            self.assertEqual(len(engine), 1)
            self.assertIs(engine.get_hook(topic), hook)
            retrieved = engine.unregister_hook(topic)
            self.assertIs(retrieved, hook)
            self.assertEqual(len(engine), 0)
        finally:
            engine.clear()

    def test_02_duplicate_hook_raises_keyerror(self) -> None:
        """Registering a second hook for the same topic raises KeyError."""
        engine = EventEngine()
        from event_engine.capi import EventHook

        topic = Topic("fallback.registry.dup")
        engine.register_hook(EventHook(topic))
        try:
            with self.assertRaises(KeyError):
                engine.register_hook(EventHook(topic))
        finally:
            engine.clear()

    def test_03_missing_hook_raises_keyerror(self) -> None:
        """Unregistering an unknown topic raises KeyError."""
        engine = EventEngine()
        try:
            with self.assertRaises(KeyError):
                engine.unregister_hook(Topic("fallback.registry.missing"))
            with self.assertRaises(KeyError):
                engine.get_hook(Topic("fallback.registry.missing"))
        finally:
            engine.clear()

    def test_04_register_handler_and_cleanup(self) -> None:
        """register_handler auto-creates hooks; empty hooks are removed."""
        engine = EventEngine()
        topic = Topic("fallback.registry.auto")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            self.assertEqual(len(engine), 1)
            self.assertEqual(len(engine.get_hook(topic)), 1)
            engine.unregister_handler(topic, handler)
            self.assertEqual(len(engine), 0)
            with self.assertRaises(KeyError):
                engine.get_hook(topic)
        finally:
            engine.clear()

    def test_05_unregister_handler_missing_logs_error(self) -> None:
        """Unregistering a handler from an unknown topic logs, no raise."""
        engine = EventEngine()
        import logging

        with self.assertLogs(logging.getLogger("EventEngine.Event"), level="ERROR") as cm:
            engine.unregister_handler(Topic("fallback.registry.none"), lambda a: None)
        self.assertTrue(any("No EventHook registered" in m for m in cm.output))
        engine.clear()

    def test_06_iterators_and_getitem(self) -> None:
        """event_hooks / topics / items / getitem reflect the registry."""
        engine = EventEngine()
        exact_topic = Topic("fallback.registry.iter.exact")

        def handler(a):
            pass

        engine.register_handler(exact_topic, handler)
        engine.register_handler(Topic("fallback.{name}"), handler)
        try:
            self.assertEqual(len(list(engine.event_hooks())), 2)
            self.assertEqual(len(list(engine.topics())), 2)
            self.assertEqual(len(list(engine.items())), 2)

            matched = engine[exact_topic]
            self.assertEqual(len(matched), 1)
            self.assertIs(matched[0].topic, exact_topic)

            matched = engine[Topic("fallback.generic")]
            self.assertEqual(len(matched), 1)
        finally:
            engine.clear()


class TestFallbackEngineQueue(unittest.TestCase):
    """Contract: put/get semantics, Full/Empty, queue bookkeeping."""

    def test_00_put_get_roundtrip(self) -> None:
        """put enqueues; get returns a payload with args/kwargs."""
        engine = EventEngine(capacity=8)
        topic = Topic("fallback.queue.roundtrip")

        def handler(a, b):
            pass

        engine.register_handler(topic, handler)
        try:
            engine.put(topic, 1, 2, block=False)
            self.assertEqual(engine.occupied, 1)
            payload = engine.get(block=False)
            self.assertEqual(payload.args, (1, 2))
            self.assertEqual(payload.topic.value, topic.value)
            self.assertEqual(engine.occupied, 0)
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
        engine.activate()  # fallback engine _get_message gates on active
        try:
            t0 = time.perf_counter()
            with self.assertRaises(Empty):
                engine.get(block=True, timeout=0.15)
            self.assertGreaterEqual(time.perf_counter() - t0, 0.1)
        finally:
            engine.deactivate()
            engine.clear()

    def test_03_put_full_raises_full(self) -> None:
        """Non-blocking put on a full queue raises Full."""
        engine = EventEngine(capacity=2)
        topic = Topic("fallback.queue.full")

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
                engine.put(Topic("fallback.+any"), 1)
            with self.assertRaises(ValueError):
                engine.publish(Topic("fallback.+any"), (1,), {})
        finally:
            engine.clear()

    def test_05_seq_id_and_payload_kwargs_with_topic(self) -> None:
        """seq_id increments; payloads carry topic in kwargs_with_topic."""
        engine = EventEngine(capacity=8)
        topic = Topic("fallback.queue.seqid")

        def handler(a):
            pass

        engine.register_handler(topic, handler)
        try:
            engine.put(topic, 1, x=2, block=False)
            payload = engine.get(block=False)
            self.assertEqual(payload.seq_id, 0)
            self.assertEqual(engine.seq_id, 1)
            aggregated = payload.kwargs_with_topic
            self.assertEqual(aggregated["x"], 2)
            self.assertEqual(aggregated["topic"].value, topic.value)
        finally:
            engine.clear()


class TestFallbackEngineLoop(unittest.TestCase):
    """Contract: the dispatch loop delivers messages to matching hooks."""

    def _wait_for(self, event: threading.Event, timeout=3.0) -> None:
        self.assertTrue(event.wait(timeout), "timed out waiting for event")

    def test_00_start_stop_and_dispatch(self) -> None:
        """start/stop toggle active; handlers receive published messages."""
        engine = EventEngine(capacity=16)
        topic = Topic("fallback.loop.basic")
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

    def test_01_generic_topic_routing(self) -> None:
        """Messages published on an exact topic reach generic pattern hooks."""
        engine = EventEngine(capacity=16)
        received = []
        done = threading.Event()

        def handler(a, topic=None, **kw):
            received.append((a, topic.value))
            done.set()

        engine.register_handler(Topic("fallback.{name}.status"), handler)
        try:
            engine.start()
            engine.put(Topic("fallback.new.status"), 7)
            self._wait_for(done)
            engine.stop()
            self.assertEqual(received, [(7, "fallback.new.status")])
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_02_handler_exception_does_not_crash_engine(self) -> None:
        """A raising handler does not stop the loop; later handlers still run."""
        engine = EventEngine(capacity=16)
        topic = Topic("fallback.loop.error")
        ran = []
        done = threading.Event()

        def failing(a):
            raise ValueError("fallback test")

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

    def test_03_clear_only_when_stopped(self) -> None:
        """clear() while running logs an error and keeps hooks."""
        engine = EventEngine(capacity=16)
        topic = Topic("fallback.loop.clear")

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

    def test_04_concurrent_producers(self) -> None:
        """Messages from several producer threads are all delivered."""
        engine = EventEngine(capacity=256)
        topic = Topic("fallback.loop.concurrent")
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


class TestFallbackEngineEx(unittest.TestCase):
    """Contract: fallback EventEngineEx timer support."""

    def test_00_custom_interval_timer(self) -> None:
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
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_01_second_timer_topic(self) -> None:
        """interval=1 uses the second timer topic."""
        engine = EventEngineEx(capacity=64)
        try:
            engine.start()
            timer_topic = engine.get_timer(interval=1)
            self.assertEqual(timer_topic.value, "EventEngine.Internal.Timer.Second")
            engine.stop()
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_02_get_timer_requires_active_engine(self) -> None:
        """get_timer before start raises RuntimeError."""
        engine = EventEngineEx(capacity=64)
        try:
            with self.assertRaises(RuntimeError):
                engine.get_timer(interval=0.1)
        finally:
            engine.clear()

    def test_03_stop_joins_timer_threads(self) -> None:
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
