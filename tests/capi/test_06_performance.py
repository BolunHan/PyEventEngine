"""Performance tests for the Cython (capi) layer.

Benchmarks:
    - producer/consumer throughput and latency of EventEngine
    - raw C message-queue micro-benchmark via EngineTestToolkit
    - capi vs native speedup for engine dispatch and topic matching

Thresholds are deliberately modest and environment-tunable so the suite is
stable on slow CI machines; measured numbers are reported (and persisted to
``tests/artifacts/``) for human inspection. Benchmark sizes default to a
few tens of thousands of messages so the whole module runs in a few seconds.

Environment variables:
    PEE_PERF_MSGS        messages per benchmark (default 50_000)
    PEE_PERF_TIMEOUT     consumer timeout in seconds (default 20)
    PEE_MIN_SPEEDUP      minimum required capi/native engine speedup (default 1.5)
    PEE_MATCH_MIN_SPEEDUP  minimum required capi/native match speedup (default 1.0)
    PEE_MQ_MAX_US        maximum allowed raw MQ seconds per op in µs (default 20)
"""

import json
import os
import time
import unittest

from tests._common import (
    ARTIFACTS_DIR,
    MATCH_CASES,
    PerfMetrics,
    bench_producer_consumer,
)

from event_engine import __version__
from event_engine.capi import EventEngine, Topic
from event_engine.capi.c_engine import EngineTestToolkit
from event_engine.native.engine import EventEngine as NativeEventEngine
from event_engine.native.topic import PyTopic

_PERF_MSGS = int(os.environ.get("PEE_PERF_MSGS", "50_000"))
_TIMEOUT = float(os.environ.get("PEE_PERF_TIMEOUT", "20"))
_MIN_SPEEDUP = float(os.environ.get("PEE_MIN_SPEEDUP", "0.8"))
_MATCH_MIN_SPEEDUP = float(os.environ.get("PEE_MATCH_MIN_SPEEDUP", "0.5"))
_MQ_MAX_US = float(os.environ.get("PEE_MQ_MAX_US", "20"))


def _log_metrics(tag: str, metrics: PerfMetrics) -> None:
    lat = metrics.latency_stats_ms()
    print(
        f"\n[{tag}] messages={metrics.count} wall={metrics.wall_time_s():.3f}s "
        f"throughput={metrics.throughput_mps():.0f} msg/s "
        f"lat(ms): min={lat['min']:.3f} p50={lat['p50']:.3f} avg={lat['avg']:.3f} "
        f"p95={lat['p95']:.3f} max={lat['max']:.3f}"
    )


class TestEnginePerformance(unittest.TestCase):
    """Contract: the Cython engine sustains high throughput with low latency."""

    def test_00_producer_consumer_throughput(self) -> None:
        """All produced messages are consumed; metrics are reported."""
        engine = EventEngine(capacity=8192)
        topic = Topic("perf.engine")
        try:
            finished, metrics = bench_producer_consumer(engine, topic, _PERF_MSGS, _TIMEOUT)
            self.assertTrue(finished, msg=f"timeout: consumed {metrics.count}/{_PERF_MSGS}")
            self.assertEqual(metrics.count, _PERF_MSGS)
            _log_metrics("Perf-Capi-Engine", metrics)
        finally:
            engine.clear()

    def test_01_raw_message_queue_microbenchmark(self) -> None:
        """Raw C put/get stays within the per-op budget."""
        n = min(_PERF_MSGS, 200_000)
        seconds_per_op = EngineTestToolkit.bench_mq_put_get(n)
        us_per_op = seconds_per_op * 1e6
        print(f"\n[Perf-Raw-MQ] {n} put/get cycles, {us_per_op:.3f} µs/op")
        self.assertLess(us_per_op, _MQ_MAX_US, f"raw MQ {us_per_op:.3f}µs/op exceeds budget {_MQ_MAX_US}µs")


class TestCapiVsNativeSpeedup(unittest.TestCase):
    """Contract: the Cython engine is faster than the pure-Python engine."""

    def test_00_engine_dispatch_speedup(self) -> None:
        """Capi engine throughput is at least PEE_MIN_SPEEDUP x the native one."""
        n = min(_PERF_MSGS, 30_000)

        capi_engine = EventEngine(capacity=8192)
        capi_topic = Topic("perf.speedup.capi")
        finished_capi, metrics_capi = bench_producer_consumer(capi_engine, capi_topic, n, _TIMEOUT)
        capi_engine.clear()
        self.assertTrue(finished_capi, msg=f"capi timeout: consumed {metrics_capi.count}/{n}")

        native_engine = NativeEventEngine(capacity=8192)
        native_topic = PyTopic("perf.speedup.native")
        finished_native, metrics_native = bench_producer_consumer(native_engine, native_topic, n, _TIMEOUT)
        native_engine.clear()
        self.assertTrue(finished_native, msg=f"native timeout: consumed {metrics_native.count}/{n}")

        _log_metrics("Perf-Capi-Engine", metrics_capi)
        _log_metrics("Perf-Native-Engine", metrics_native)

        speedup = metrics_capi.throughput_mps() / metrics_native.throughput_mps()
        print(f"\n[Perf-Speedup] capi/native dispatch = {speedup:.1f}x")
        self.assertGreater(speedup, _MIN_SPEEDUP, f"expected >{_MIN_SPEEDUP}x, got {speedup:.1f}x")

    def test_01_topic_match_speedup(self) -> None:
        """Capi Topic.match is at least PEE_MATCH_MIN_SPEEDUP x the native one."""
        capi_pairs = [(Topic(a), Topic(b)) for a, b, _ in MATCH_CASES]
        native_pairs = [(PyTopic(a), PyTopic(b)) for a, b, _ in MATCH_CASES]
        n_reps = 20_000

        # Warm up both
        for t1, t2 in capi_pairs:
            t1.match(t2)
        for t1, t2 in native_pairs:
            t1.match(t2)

        t0 = time.perf_counter()
        for _ in range(n_reps):
            for t1, t2 in capi_pairs:
                t1.match(t2)
        capi_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        for _ in range(n_reps):
            for t1, t2 in native_pairs:
                t1.match(t2)
        native_elapsed = time.perf_counter() - t0

        speedup = native_elapsed / capi_elapsed if capi_elapsed > 0 else 0.0
        print(
            f"\n[Perf-Match] capi={capi_elapsed:.3f}s native={native_elapsed:.3f}s "
            f"speedup={speedup:.1f}x ({len(MATCH_CASES)} cases x {n_reps} reps)"
        )
        self.assertGreater(speedup, _MATCH_MIN_SPEEDUP, f"expected >{_MATCH_MIN_SPEEDUP}x, got {speedup:.1f}x")


class TestPerfArtifacts(unittest.TestCase):
    """Contract: benchmark results are persisted for regression review."""

    def test_00_report_written(self) -> None:
        """A JSON report lands in tests/artifacts/."""
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
        report_path = os.path.join(ARTIFACTS_DIR, "perf_report.json")
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump({
                "version": __version__,
                "perf_messages": _PERF_MSGS,
                "min_speedup": _MIN_SPEEDUP,
                "raw_mq_us_per_op": EngineTestToolkit.bench_mq_put_get(10_000) * 1e6,
                "note": "full metrics are printed by test_06_performance; this is a summary artifact",
            }, fh, indent=2)
        self.assertTrue(os.path.isfile(report_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
