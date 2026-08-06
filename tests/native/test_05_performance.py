"""Performance tests for the pure-Python native layer.

Benchmarks the native EventEngine under producer/consumer load, multi-topic
routing, handler overhead, multi-producer contention and timer interference.
Thresholds are environmental and modest (correctness of consumption is the
hard assertion; numbers are reported for inspection).

Environment variables:
    PEE_PERF_MSGS        messages per benchmark (default 10_000 for native)
    PEE_PERF_TIMEOUT     consumer timeout in seconds (default 20)
"""

import os
import threading
import time
import unittest

from tests._common import PerfMetrics, bench_producer_consumer

from event_engine.native import EventEngine, EventEngineEx, PyTopic

_PERF_MSGS = int(os.environ.get("PEE_PERF_MSGS", "10_000"))
_TIMEOUT = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))


def _log_metrics(tag: str, metrics: PerfMetrics) -> None:
    lat = metrics.latency_stats_ms()
    print(
        f"\n[{tag}] messages={metrics.count} wall={metrics.wall_time_s():.3f}s "
        f"throughput={metrics.throughput_mps():.0f} msg/s "
        f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} "
        f"p95={lat['p95']:.3f} max={lat['max']:.3f}"
    )


class TestNativeEnginePerformance(unittest.TestCase):
    """Contract: the native engine processes all messages within the budget."""

    def test_00_producer_consumer_throughput(self) -> None:
        """All produced messages are consumed; metrics are reported."""
        engine = EventEngine(capacity=8192)
        topic = PyTopic("perf.native.basic")
        try:
            finished, metrics = bench_producer_consumer(engine, topic, _PERF_MSGS, _TIMEOUT)
            self.assertTrue(finished, msg=f"timeout: consumed {metrics.count}/{_PERF_MSGS}")
            self.assertEqual(metrics.count, _PERF_MSGS)
            _log_metrics("Perf-Native-Engine", metrics)
        finally:
            engine.clear()

    def test_01_multi_topic_routing(self) -> None:
        """Routing across exact and generic topics does not drop messages."""
        n = min(_PERF_MSGS, 5_000)
        engine = EventEngine(capacity=8192)
        exact_topics = [PyTopic(f"perf.native.exact.topic{i}") for i in range(10)]
        generic_topic = PyTopic("perf.native.generic.{wildcard}")
        metrics = PerfMetrics()
        processed_all = threading.Event()

        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            if metrics.count >= n:
                processed_all.set()

        for topic in exact_topics:
            engine.register_handler(topic, handler)
        engine.register_handler(generic_topic, handler)

        def producer():
            for i in range(n):
                ts = time.perf_counter_ns()
                engine.put(exact_topics[i % len(exact_topics)], ts, block=True)

        producer_thread = threading.Thread(target=producer, daemon=True)
        try:
            engine.start()
            metrics.start()
            producer_thread.start()
            finished = processed_all.wait(timeout=_TIMEOUT)
            metrics.stop()
            engine.stop()
            producer_thread.join(timeout=5)

            self.assertTrue(finished, msg=f"timeout: consumed {metrics.count}/{n}")
            self.assertEqual(metrics.count, n)
            _log_metrics("Perf-Native-MultiTopic", metrics)
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_02_handler_overhead(self) -> None:
        """Handler-side work is included in the measured throughput."""
        n = min(_PERF_MSGS, 5_000)
        engine = EventEngine(capacity=8192)
        topic = PyTopic("perf.native.handler")
        metrics = PerfMetrics()
        processed_all = threading.Event()

        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            _ = sum(range(100))
            metrics.record(now - sent_ts_ns)
            if metrics.count >= n:
                processed_all.set()

        engine.register_handler(topic, handler)

        def producer():
            for _ in range(n):
                ts = time.perf_counter_ns()
                engine.put(topic, ts, block=True)

        producer_thread = threading.Thread(target=producer, daemon=True)
        try:
            engine.start()
            metrics.start()
            producer_thread.start()
            finished = processed_all.wait(timeout=_TIMEOUT)
            metrics.stop()
            engine.stop()
            producer_thread.join(timeout=5)

            self.assertTrue(finished, msg=f"timeout: consumed {metrics.count}/{n}")
            self.assertEqual(metrics.count, n)
            _log_metrics("Perf-Native-Handler", metrics)
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_03_queue_contention(self) -> None:
        """Multiple producers all deliver their messages."""
        n = min(_PERF_MSGS, 5_000)
        num_producers = 4
        engine = EventEngine(capacity=8192)
        topic = PyTopic("perf.native.contention")
        metrics = PerfMetrics()
        processed_all = threading.Event()
        messages_per_producer = n // num_producers

        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            if metrics.count >= messages_per_producer * num_producers:
                processed_all.set()

        engine.register_handler(topic, handler)

        def producer():
            for _ in range(messages_per_producer):
                ts = time.perf_counter_ns()
                engine.put(topic, ts, block=True)

        producers = [threading.Thread(target=producer, daemon=True) for _ in range(num_producers)]
        try:
            engine.start()
            metrics.start()
            for p in producers:
                p.start()

            finished = processed_all.wait(timeout=_TIMEOUT)
            metrics.stop()
            engine.stop()
            for p in producers:
                p.join(timeout=5)

            self.assertTrue(finished, msg=f"timeout: consumed {metrics.count}/{n}")
            self.assertGreaterEqual(metrics.count, n - num_producers)
            _log_metrics("Perf-Native-Contention", metrics)
        finally:
            if engine.active:
                engine.stop()
            engine.clear()

    def test_04_timer_interference(self) -> None:
        """An active timer does not prevent message delivery."""
        n = min(_PERF_MSGS, 5_000)
        engine = EventEngineEx(capacity=8192)
        topic = PyTopic("perf.native.timer")
        metrics = PerfMetrics()
        processed_all = threading.Event()
        timer_count = [0]

        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            if metrics.count >= n:
                processed_all.set()

        def timer_handler(**kw):
            timer_count[0] += 1

        engine.register_handler(topic, handler)

        def producer():
            for _ in range(n):
                ts = time.perf_counter_ns()
                engine.put(topic, ts, block=True)

        producer_thread = threading.Thread(target=producer, daemon=True)
        try:
            engine.start()
            timer_topic = engine.get_timer(0.1)
            engine.register_handler(timer_topic, timer_handler)

            metrics.start()
            producer_thread.start()
            finished = processed_all.wait(timeout=_TIMEOUT)
            metrics.stop()
            engine.stop()
            producer_thread.join(timeout=5)

            self.assertTrue(finished, msg=f"timeout: consumed {metrics.count}/{n}")
            self.assertEqual(metrics.count, n)
            self.assertGreater(timer_count[0], 0, "timer should have fired")
            _log_metrics("Perf-Native-Timer", metrics)
        finally:
            if engine.active:
                engine.stop()
            engine.clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
