"""
Performance test for the native Python fallback implementation of EventEngine.

This test measures throughput and latency for message publishing and processing,
comparing results with environment-configurable thresholds.
"""

import os
import sys
import time
import threading
import unittest
from typing import List, Optional

# Ensure project root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from event_engine.native.engine import EventEngine, EventEngineEx
from event_engine.native.topic import PyTopic


class PerfMetrics:
    """
    Tracks consumer-side metrics:
    - count: number of processed messages
    - latencies_ns: list of per-message latencies in nanoseconds
    - started_at_ns / finished_at_ns: wall-clock timing for the test window
    Thread-safe updates from the consumer handler.
    """

    __slots__ = (
        "count",
        "latencies_ns",
        "started_at_ns",
        "finished_at_ns",
        "_lock",
    )

    def __init__(self) -> None:
        self.count: int = 0
        self.latencies_ns: List[int] = []
        self.started_at_ns: Optional[int] = None
        self.finished_at_ns: Optional[int] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self.started_at_ns = time.perf_counter_ns()

    def stop(self) -> None:
        with self._lock:
            self.finished_at_ns = time.perf_counter_ns()

    def record(self, latency_ns: int) -> None:
        with self._lock:
            self.count += 1
            self.latencies_ns.append(latency_ns)

    # Derived metrics helpers
    def wall_time_s(self) -> float:
        if self.started_at_ns is None or self.finished_at_ns is None:
            return 0.0
        return (self.finished_at_ns - self.started_at_ns) / 1e9

    def throughput_mps(self) -> float:
        wt = self.wall_time_s()
        if wt <= 0:
            return 0.0
        return self.count / wt

    def latency_stats_ms(self) -> dict:
        if not self.latencies_ns:
            return {"min": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        xs = sorted(self.latencies_ns)
        n = len(xs)
        min_ms = xs[0] / 1e6
        max_ms = xs[-1] / 1e6
        avg_ms = (sum(xs) / n) / 1e6
        p50_ms = xs[int(0.5 * (n - 1))] / 1e6
        p95_ms = xs[int(0.95 * (n - 1))] / 1e6
        return {"min": min_ms, "avg": avg_ms, "p50": p50_ms, "p95": p95_ms, "max": max_ms}


class TestNativeEventEnginePerformance(unittest.TestCase):
    """Performance tests for native Python EventEngine implementation."""

    def test_producer_consumer_throughput_and_latency(self):
        """
        Performance test for native EventEngine:
        - Launch EventEngine consumer loop
        - Producer thread publishes N messages with send timestamp
        - Consumer handler computes per-message latency and records stats
        - Assert all messages are consumed and report metrics

        Environment variables:
        - PEE_PERF_MSGS: Number of messages to send (default: 100,000)
        - PEE_PERF_CAP: Queue capacity (default: 8192)
        - PEE_PERF_TIMEOUT: Timeout in seconds (default: 20)
        """
        total_messages = int(os.environ.get("PEE_PERF_MSGS", "100_000"))
        capacity = int(os.environ.get("PEE_PERF_CAP", "8192"))

        engine = EventEngine(capacity=capacity)
        topic = PyTopic("perf.native.topic")

        metrics = PerfMetrics()
        processed_all = threading.Event()

        # Consumer handler executed on engine's internal thread
        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            # Fast path check
            if metrics.count >= total_messages:
                processed_all.set()

        engine.register_handler(topic, handler)

        # Producer runs in separate thread
        def producer():
            for _ in range(total_messages):
                ts = time.perf_counter_ns()
                # Block on full to ensure every message is enqueued
                engine.put(topic, ts, block=True)

        t = threading.Thread(target=producer, name="perf-producer-native", daemon=True)

        # Start engine and measure wall time
        engine.start()
        metrics.start()
        t.start()

        # Wait for all messages processed or timeout
        timeout_s = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))
        finished = processed_all.wait(timeout=timeout_s)
        metrics.stop()

        # Clean up
        engine.stop()
        t.join(timeout=5)

        # Assertions
        self.assertTrue(finished, msg=f"Timeout waiting for {total_messages} messages; processed {metrics.count}")
        self.assertEqual(metrics.count, total_messages)

        # Report metrics
        lat = metrics.latency_stats_ms()
        print(
            f"\n[Perf-Native] messages={metrics.count} wall={metrics.wall_time_s():.3f}s "
            f"throughput={metrics.throughput_mps():.0f} msg/s "
            f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} "
            f"p95={lat['p95']:.3f} max={lat['max']:.3f}"
        )

    def test_multi_topic_routing_performance(self):
        """
        Test performance with multiple topics (exact and generic matching).
        
        This tests the routing overhead when multiple topics are registered.
        """
        total_messages = int(os.environ.get("PEE_PERF_MSGS", "50_000"))
        capacity = int(os.environ.get("PEE_PERF_CAP", "8192"))
        num_topics = 10

        engine = EventEngine(capacity=capacity)

        # Create multiple exact topics
        exact_topics = [PyTopic(f"perf.exact.topic{i}") for i in range(num_topics)]

        # Create a generic topic
        generic_topic = PyTopic("perf.generic.{wildcard}")

        metrics = PerfMetrics()
        processed_all = threading.Event()

        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            if metrics.count >= total_messages:
                processed_all.set()

        # Register handlers for all topics
        for topic in exact_topics:
            engine.register_handler(topic, handler)

        engine.register_handler(generic_topic, handler)

        # Producer publishes to different topics
        def producer():
            for i in range(total_messages):
                ts = time.perf_counter_ns()
                # Alternate between topics
                topic = exact_topics[i % num_topics]
                engine.put(topic, ts, block=True)

        t = threading.Thread(target=producer, name="perf-producer-multi", daemon=True)

        engine.start()
        metrics.start()
        t.start()

        timeout_s = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))
        finished = processed_all.wait(timeout=timeout_s)
        metrics.stop()

        engine.stop()
        t.join(timeout=5)

        self.assertTrue(finished)
        self.assertEqual(metrics.count, total_messages)

        lat = metrics.latency_stats_ms()
        print(
            f"\n[Perf-Multi-Topic] topics={num_topics + 1} messages={metrics.count} "
            f"wall={metrics.wall_time_s():.3f}s throughput={metrics.throughput_mps():.0f} msg/s "
            f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} "
            f"p95={lat['p95']:.3f} max={lat['max']:.3f}"
        )

    def test_handler_execution_overhead(self):
        """
        Test overhead of handler execution with varying handler complexities.
        
        Measures the impact of handler execution time on overall throughput.
        """
        total_messages = int(os.environ.get("PEE_PERF_MSGS", "10_000"))
        capacity = int(os.environ.get("PEE_PERF_CAP", "4096"))

        engine = EventEngine(capacity=capacity)
        topic = PyTopic("perf.handler.overhead")

        metrics = PerfMetrics()
        processed_all = threading.Event()

        # Handler with some work (simulating real processing)
        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            # Simulate some processing (compute something)
            _ = sum(range(100))
            metrics.record(now - sent_ts_ns)
            if metrics.count >= total_messages:
                processed_all.set()

        engine.register_handler(topic, handler)

        def producer():
            for _ in range(total_messages):
                ts = time.perf_counter_ns()
                engine.put(topic, ts, block=True)

        t = threading.Thread(target=producer, name="perf-producer-overhead", daemon=True)

        engine.start()
        metrics.start()
        t.start()

        timeout_s = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))
        finished = processed_all.wait(timeout=timeout_s)
        metrics.stop()

        engine.stop()
        t.join(timeout=5)

        self.assertTrue(finished)
        self.assertEqual(metrics.count, total_messages)

        lat = metrics.latency_stats_ms()
        print(
            f"\n[Perf-Handler-Overhead] messages={metrics.count} wall={metrics.wall_time_s():.3f}s "
            f"throughput={metrics.throughput_mps():.0f} msg/s "
            f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} "
            f"p95={lat['p95']:.3f} max={lat['max']:.3f}"
        )

    def test_queue_contention_performance(self):
        """
        Test queue performance under contention (multiple producers).
        
        Measures throughput when multiple threads are competing to publish.
        """
        total_messages = int(os.environ.get("PEE_PERF_MSGS", "50_000"))
        capacity = int(os.environ.get("PEE_PERF_CAP", "4096"))
        num_producers = 4

        engine = EventEngine(capacity=capacity)
        topic = PyTopic("perf.contention.topic")

        metrics = PerfMetrics()
        processed_all = threading.Event()

        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            if metrics.count >= total_messages:
                processed_all.set()

        engine.register_handler(topic, handler)

        messages_per_producer = total_messages // num_producers

        def producer():
            for _ in range(messages_per_producer):
                ts = time.perf_counter_ns()
                engine.put(topic, ts, block=True)

        producers = [
            threading.Thread(target=producer, name=f"perf-producer-{i}", daemon=True)
            for i in range(num_producers)
        ]

        engine.start()
        metrics.start()

        for p in producers:
            p.start()

        timeout_s = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))
        finished = processed_all.wait(timeout=timeout_s)
        metrics.stop()

        engine.stop()
        for p in producers:
            p.join(timeout=5)

        self.assertTrue(finished)
        # Allow some tolerance for rounding
        self.assertGreaterEqual(metrics.count, total_messages - num_producers)

        lat = metrics.latency_stats_ms()
        print(
            f"\n[Perf-Contention] producers={num_producers} messages={metrics.count} "
            f"wall={metrics.wall_time_s():.3f}s throughput={metrics.throughput_mps():.0f} msg/s "
            f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} "
            f"p95={lat['p95']:.3f} max={lat['max']:.3f}"
        )

    def test_eventengine_ex_timer_overhead(self):
        """
        Test EventEngineEx timer overhead.
        
        Measures the impact of active timers on event processing.
        """
        total_messages = int(os.environ.get("PEE_PERF_MSGS", "10_000"))
        capacity = int(os.environ.get("PEE_PERF_CAP", "4096"))

        engine = EventEngineEx(capacity=capacity)
        topic = PyTopic("perf.timer.test")

        metrics = PerfMetrics()
        processed_all = threading.Event()

        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            if metrics.count >= total_messages:
                processed_all.set()

        engine.register_handler(topic, handler)

        # Start engine with a timer running
        engine.start()

        # Get a timer (this will run in background)
        timer_topic = engine.get_timer(0.5)  # 500ms timer
        timer_count = [0]

        def timer_handler(**kwargs):
            timer_count[0] += 1

        engine.register_handler(timer_topic, timer_handler)

        metrics.start()

        def producer():
            for _ in range(total_messages):
                ts = time.perf_counter_ns()
                engine.put(topic, ts, block=True)

        t = threading.Thread(target=producer, name="perf-producer-timer", daemon=True)
        t.start()

        timeout_s = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))
        finished = processed_all.wait(timeout=timeout_s)
        metrics.stop()

        engine.stop()
        t.join(timeout=5)

        self.assertTrue(finished)
        self.assertEqual(metrics.count, total_messages)
        self.assertGreater(timer_count[0], 0, "Timer should have fired at least once")

        lat = metrics.latency_stats_ms()
        print(
            f"\n[Perf-Timer-Overhead] messages={metrics.count} timer_events={timer_count[0]} "
            f"wall={metrics.wall_time_s():.3f}s throughput={metrics.throughput_mps():.0f} msg/s "
            f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} "
            f"p95={lat['p95']:.3f} max={lat['max']:.3f}"
        )


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)
