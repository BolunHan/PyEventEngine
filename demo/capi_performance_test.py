import os
import sys
import time
import threading
import unittest
from typing import List, Optional

# Ensure project root is on sys.path for direct execution
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from event_engine.capi import EventEngine, PyTopic  # type: ignore


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


class TestEventEnginePerformance(unittest.TestCase):
    def test_producer_consumer_throughput_and_latency(self):
        """
        Performance sanity test:
        - Launch EventEngine consumer loop.
        - Producer thread publishes N messages carrying the send timestamp (ns).
        - Consumer handler computes per-message latency and records stats.
        - Assert all produced messages are consumed and report metrics.

        Note: This is a bounded, quick performance sanity check intended to
        be stable in CI. It prints throughput/latency without strict thresholds.
        """
        total_messages = int(os.environ.get("PEE_PERF_MSGS", "100_000"))
        capacity = int(os.environ.get("PEE_PERF_CAP", "8192"))

        engine = EventEngine(capacity=capacity)
        topic = PyTopic("perf.topic")  # type: ignore[arg-type]

        metrics = PerfMetrics()
        processed_all = threading.Event()

        # Consumer handler executed on engine's internal thread
        def handler(sent_ts_ns: int):
            now = time.perf_counter_ns()
            metrics.record(now - sent_ts_ns)
            # Fast path check to avoid taking a lock per access other than record()
            if metrics.count >= total_messages:
                processed_all.set()

        engine.register_handler(topic, handler)

        # Producer that runs in a separate thread
        def producer():
            for _ in range(total_messages):
                ts = time.perf_counter_ns()
                # Block on full to ensure every message is enqueued
                engine.put(topic, ts, block=True)

        t = threading.Thread(target=producer, name="perf-producer", daemon=True)

        # Start engine and measure wall time around active period
        engine.start()
        metrics.start()
        t.start()

        # Wait for all messages processed or timeout
        timeout_s = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))
        finished = processed_all.wait(timeout=timeout_s)
        metrics.stop()

        # Clean up engine and join producer
        engine.stop()
        t.join(timeout=5)

        # Assertions: we must have processed all messages within the timeout
        self.assertTrue(finished, msg=f"Timeout waiting for {total_messages} messages; processed {metrics.count}")
        self.assertEqual(metrics.count, total_messages)

        # Report metrics for human inspection (does not affect pass/fail)
        lat = metrics.latency_stats_ms()
        print(
            f"\n[Perf] messages={metrics.count} wall={metrics.wall_time_s():.3f}s "
            f"throughput={metrics.throughput_mps():.0f} msg/s "
            f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} p95={lat['p95']:.3f} max={lat['max']:.3f}"
        )


def suite():
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestEventEnginePerformance))
    return test_suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())
    sys.exit(0 if result.wasSuccessful() else 1)

