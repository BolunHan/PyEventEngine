"""Benchmark the two EventEngineEx implementations against EventEngine.

Engines under test (all Cython in ``event_engine.capi`` unless noted):

- ``c_engine.EventEngine``      — baseline engine; loop/dispatch in Cython.
- ``c_engine.EventEngineEx``    — EventEngine subclass; timers via Python
                                  threads (sleep loops per interval).
- ``c_engine_ex.EventEngineEx`` — standalone engine; loop/dispatch/seq-id and
                                  timers moved into C (``evt_engine`` in
                                  ``c_engine.h`` / ``c_engine_gil.h``).
- ``native.EventEngine``        — pure-Python engine; context baseline only
                                  (dispatch workload).

Methodology
    - every workload runs a warmup pass before measurement;
    - ``--repeats`` (default 5) trials per engine per workload, engines
      interleaved across trials so thermal/clock drift hits all engines
      equally;
    - per-workload per-engine stats: mean / std / CV% / min / max / median of
      per-op (or per-message) samples;
    - producer/consumer latency percentiles pooled across all trials;
    - results dumped as JSON + Markdown into a versioned artifact directory
      named ``<__version__>-<git_head>`` (auto-generated; see
      ``_bench_common.versioned_artifacts_dir``).

Usage
    python tests/benchmarks/run_benchmarks.py [--quick] [--msgs N] [--repeats R]
        [--capacity C] [--hooks K] [--cycles C] [--tag TAG] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.benchmarks._bench_common import (  # noqa: E402
    aggregate,
    collect_env,
    dispose,
    percentiles_us,
    ratio_vs,
    versioned_artifacts_dir,
)

from event_engine.capi import EventEngine, Topic  # noqa: E402
from event_engine.capi.c_engine import EventEngineEx as SubclassEventEngineEx  # noqa: E402
from event_engine.capi.c_engine import EngineTestToolkit as ToolkitEngine  # noqa: E402
from event_engine.capi.c_engine_ex import EngineTestToolkit as ToolkitEngineEx  # noqa: E402
from event_engine.capi.c_engine_ex import EventEngineEx as CEventEngineEx  # noqa: E402
from event_engine.native.engine import EventEngine as NativeEventEngine  # noqa: E402
from event_engine.native.topic import PyTopic  # noqa: E402

GENERIC_HOOKS = 10
GENERIC_TOPIC = "bench.generic.x"


def _noop(*args, **kwargs) -> None:
    pass


# ---------------------------------------------------------------------------
# Engine factories — each returns a fresh (engine, topic) pair per call.
# ---------------------------------------------------------------------------

def _make_capi_factory(cls, capacity: int, topic_str: str):
    def factory():
        return cls(capacity=capacity), Topic(topic_str)

    return factory


def _make_native_factory(capacity: int, topic_str: str):
    def factory():
        return NativeEventEngine(capacity=capacity), PyTopic(topic_str)

    return factory


def build_factories(args) -> dict:
    """Engine label -> factory, in a stable order for interleaved trials."""
    return {
        "c_engine.EventEngine": _make_capi_factory(EventEngine, args.capacity, "bench.dispatch.exact"),
        "c_engine.EventEngineEx": _make_capi_factory(SubclassEventEngineEx, args.capacity, "bench.dispatch.exact"),
        "c_engine_ex.EventEngineEx": _make_capi_factory(CEventEngineEx, args.capacity, "bench.dispatch.exact"),
        "native.EventEngine": _make_native_factory(args.capacity, "bench.dispatch.exact"),
    }


def _capi_factories(factories: dict) -> dict:
    return {k: v for k, v in factories.items() if not k.startswith("native.")}


# ---------------------------------------------------------------------------
# Workload: producer/consumer dispatch
# ---------------------------------------------------------------------------

def run_dispatch_once(engine, topic, total: int, timeout_s: float) -> dict:
    """One producer/consumer trial; returns per-message metrics dict.

    Two latency views per message (the queue is FIFO, so delivery ``i``
    corresponds to producer put ``i``):
        - ``e2e_ns``: stamped before the blocking put — includes producer-side
          backpressure when the queue is full;
        - ``queue_ns``: e2e minus the producer's own put duration — the pure
          enqueue -> handler time (queue + dispatch latency). Computed
          post-hoc in the main thread, after the producer has joined, so the
          handler itself never reads producer-side state.

    Raises RuntimeError when the trial does not deliver every message.
    """
    e2e_latencies = []
    put_durations = []
    done = threading.Event()

    def handler(sent_ns: int) -> None:
        e2e_latencies.append(time.perf_counter_ns() - sent_ns)
        if len(e2e_latencies) >= total:
            done.set()

    engine.register_handler(topic, handler)
    engine.start()

    def producer() -> None:
        for _ in range(total):
            before = time.perf_counter_ns()
            engine.put(topic, before, block=True)
            put_durations.append(time.perf_counter_ns() - before)

    producer_thread = threading.Thread(target=producer, name="bench-producer", daemon=True)
    t0 = time.perf_counter()
    producer_thread.start()
    finished = done.wait(timeout=timeout_s)
    wall = time.perf_counter() - t0
    engine.stop()
    producer_thread.join(timeout=5)

    count = len(e2e_latencies)
    if not finished or count != total:
        raise RuntimeError(f"dispatch trial incomplete: {count}/{total} delivered")

    queue_ns = [e2e_latencies[i] - put_durations[i] for i in range(count)]
    return {"msg_per_s": count / wall if wall > 0 else 0.0, "e2e_ns": e2e_latencies, "queue_ns": queue_ns}


def bench_dispatch(args, factories) -> dict:
    """Interleaved producer/consumer trials; throughput + pooled latency."""
    result = {label: {"msg_per_s": [], "e2e_ns": [], "queue_ns": []} for label in factories}

    for label, factory in factories.items():
        engine, topic = factory()
        try:
            total = args.msgs if not label.startswith("native.") else min(args.msgs, 10_000)
            run_dispatch_once(engine, topic, min(total, args.msgs // 4), timeout_s=60)
        finally:
            dispose(engine)

    for _ in range(args.repeats):
        for label, factory in factories.items():
            total = args.msgs if not label.startswith("native.") else min(args.msgs, 10_000)
            engine, topic = factory()
            try:
                res = run_dispatch_once(engine, topic, total, timeout_s=60)
            finally:
                dispose(engine)
            result[label]["msg_per_s"].append(res["msg_per_s"])
            result[label]["e2e_ns"].extend(res["e2e_ns"])
            result[label]["queue_ns"].extend(res["queue_ns"])

    return {
        label: {
            "msg_per_s": data["msg_per_s"],
            "latency_us": percentiles_us(data["e2e_ns"]),
            "queue_latency_us": percentiles_us(data["queue_ns"]),
        }
        for label, data in result.items()
    }


def bench_dispatch_generic(args) -> dict:
    """Deliveries/s when every message matches GENERIC_HOOKS pattern hooks.

    Each message triggers the exact hook plus every matching generic hook
    (GENERIC_HOOKS + 1 deliveries per message).
    """
    gen_factories = {
        "c_engine.EventEngine": _make_capi_factory(EventEngine, args.capacity, GENERIC_TOPIC),
        "c_engine.EventEngineEx": _make_capi_factory(SubclassEventEngineEx, args.capacity, GENERIC_TOPIC),
        "c_engine_ex.EventEngineEx": _make_capi_factory(CEventEngineEx, args.capacity, GENERIC_TOPIC),
    }
    deliveries_per_msg = GENERIC_HOOKS + 1
    result = {label: {"deliveries_per_s": [], "e2e_ns": [], "queue_ns": []} for label in gen_factories}

    def run_generic_once(engine, topic, total, timeout_s):
        gen_topics = [Topic(f"bench.generic.{{{i}}}") for i in range(GENERIC_HOOKS)]
        e2e_latencies = []
        put_durations = []
        done = threading.Event()

        def handler(sent_ns: int) -> None:
            e2e_latencies.append(time.perf_counter_ns() - sent_ns)
            if len(e2e_latencies) >= total * deliveries_per_msg:
                done.set()

        for gen_topic in gen_topics:
            engine.register_handler(gen_topic, handler)
        engine.register_handler(topic, handler)
        engine.start()

        def producer() -> None:
            for _ in range(total):
                before = time.perf_counter_ns()
                engine.put(topic, before, block=True)
                put_durations.append(time.perf_counter_ns() - before)

        producer_thread = threading.Thread(target=producer, name="bench-producer", daemon=True)
        t0 = time.perf_counter()
        producer_thread.start()
        finished = done.wait(timeout=timeout_s)
        wall = time.perf_counter() - t0
        engine.stop()
        producer_thread.join(timeout=5)

        count = len(e2e_latencies)
        if not finished or count != total * deliveries_per_msg:
            raise RuntimeError(f"generic dispatch trial incomplete: {count}/{total * deliveries_per_msg}")

        # Deliveries arrive grouped per message (dispatch is per-message), so
        # delivery ``i`` pairs with put ``i // deliveries_per_msg``.
        queue_ns = [e2e_latencies[i] - put_durations[i // deliveries_per_msg] for i in range(count)]
        return {"deliveries_per_s": count / wall if wall > 0 else 0.0, "e2e_ns": e2e_latencies, "queue_ns": queue_ns}

    for label, factory in gen_factories.items():
        engine, topic = factory()
        try:
            run_generic_once(engine, topic, min(args.msgs // 2, args.msgs // 8), timeout_s=60)
        finally:
            dispose(engine)

    for _ in range(args.repeats):
        for label, factory in gen_factories.items():
            engine, topic = factory()
            try:
                res = run_generic_once(engine, topic, args.msgs // 2, timeout_s=60)
            finally:
                dispose(engine)
            result[label]["deliveries_per_s"].append(res["deliveries_per_s"])
            result[label]["e2e_ns"].extend(res["e2e_ns"])
            result[label]["queue_ns"].extend(res["queue_ns"])

    return {
        label: {
            "deliveries_per_s": data["deliveries_per_s"],
            "latency_us": percentiles_us(data["e2e_ns"]),
            "queue_latency_us": percentiles_us(data["queue_ns"]),
        }
        for label, data in result.items()
    }


# ---------------------------------------------------------------------------
# Workloads: per-op micro-benchmarks (seconds-per-op trial samples)
# ---------------------------------------------------------------------------

def _per_op_workload(factories: dict, run_once, args, warmup_n: int | None = None, trial_n: int | None = None) -> dict:
    """Interleaved per-op sampling: warmup all, then repeat interleaved trials."""
    warmup_n = args.warmup_ops if warmup_n is None else warmup_n
    trial_n = args.per_op_n if trial_n is None else trial_n
    result = {label: [] for label in factories}

    for label, factory in factories.items():
        engine, topic = factory()
        try:
            run_once(engine, topic, warmup_n)
        finally:
            dispose(engine)

    for _ in range(args.repeats):
        for label, factory in factories.items():
            engine, topic = factory()
            try:
                result[label].append(run_once(engine, topic, trial_n))
            finally:
                dispose(engine)

    return {label: {"per_op_s": samples} for label, samples in result.items()}


def bench_publish_get_roundtrip(args, factories) -> dict:
    """put(block=False) + get(block=False) round trip on a stopped engine."""

    def run_once(engine, topic, n):
        t0 = time.perf_counter()
        for _ in range(n):
            engine.put(topic, 1, block=False)
            engine.get(block=False)
        elapsed = time.perf_counter() - t0
        if engine.occupied != 0:
            raise RuntimeError("roundtrip left messages in the queue")
        return elapsed / n

    return _per_op_workload(_capi_factories(factories), run_once, args)


def bench_register_handler(args, factories) -> dict:
    """Per-registration cost on a fresh engine (distinct exact topics)."""

    def run_once(engine, topic, k):
        t0 = time.perf_counter()
        for i in range(k):
            engine.register_handler(Topic(f"bench.reg.{i}"), _noop)
        elapsed = time.perf_counter() - t0
        if len(engine) != k:
            raise RuntimeError(f"registry size {len(engine)} != {k}")
        return elapsed / k

    return _per_op_workload(_capi_factories(factories), run_once, args)


def bench_unregister_handler(args, factories) -> dict:
    """Per-unregistration cost; each engine starts with K registered hooks."""

    def run_once(engine, topic, k):
        topics = [Topic(f"bench.unreg.{i}") for i in range(k)]
        for t in topics:
            engine.register_handler(t, _noop)
        t0 = time.perf_counter()
        for i in range(k):
            engine.unregister_handler(topics[i], _noop)
        elapsed = time.perf_counter() - t0
        if len(engine) != 0:
            raise RuntimeError(f"unregister left {len(engine)} hooks")
        return elapsed / k

    return _per_op_workload(_capi_factories(factories), run_once, args)


def bench_hook_lookup(args, factories) -> dict:
    """Per get_hook() cost with K pre-registered exact hooks."""

    def run_once(engine, topic, k):
        topics = [Topic(f"bench.lookup.{i}") for i in range(k)]
        for t in topics:
            engine.register_handler(t, _noop)
        n_total = max(args.lookups, k)
        ops = (n_total // k) * k
        t0 = time.perf_counter()
        for _ in range(n_total // k):
            for t in topics:
                engine.get_hook(t)
        return (time.perf_counter() - t0) / ops

    return _per_op_workload(_capi_factories(factories), run_once, args)


def bench_start_stop(args, factories) -> dict:
    """Per start()+stop() cycle cost (thread spawn/join + atomic flag)."""

    def run_once(engine, topic, cycles):
        t0 = time.perf_counter()
        for _ in range(cycles):
            engine.start()
            engine.stop()
        return (time.perf_counter() - t0) / cycles

    # Cycle counts stay tiny: an idle stop() waits out the 1 s MQ wake-up
    # granularity (DEFAULT_MQ_TIMEOUT_SECONDS), so each cycle costs ~1 s.
    return _per_op_workload(_capi_factories(factories), run_once, args, warmup_n=2, trial_n=args.cycles)


# ---------------------------------------------------------------------------
# Workload: timers (EventEngineEx only — base EventEngine has no timers)
# ---------------------------------------------------------------------------

def bench_timer_register(args, factories) -> dict:
    """Per get_timer() cost with distinct custom intervals.

    Measured on a started engine; the subclass spawns one Python thread per
    interval, the C engine registers a timer task (replacing the previous
    interval). Intervals are short (< 0.5 s) so stopping the subclass joins
    its timer threads quickly; ticks are consumed by the running loop.
    """
    intervals = [0.05 + 0.05 * i for i in range(args.timer_intervals)]
    labels = ("c_engine.EventEngineEx", "c_engine_ex.EventEngineEx")
    # The subclass keeps one thread per interval; the C engine replaces the
    # previous interval, so its timer registry holds exactly one entry.
    expected_registry = {labels[0]: len(intervals), labels[1]: 1}
    result = {label: [] for label in labels}

    for label in labels:
        engine, _ = factories[label]()
        engine.start()
        try:
            for iv in intervals:
                engine.get_timer(interval=iv)
        finally:
            dispose(engine)

    for _ in range(args.repeats):
        for label in labels:
            engine, _ = factories[label]()
            engine.start()
            try:
                t0 = time.perf_counter()
                for iv in intervals:
                    engine.get_timer(interval=iv)
                result[label].append((time.perf_counter() - t0) / len(intervals))
                if len(engine.timer) != expected_registry[label]:
                    raise RuntimeError(f"timer registry size {len(engine.timer)} != {expected_registry[label]}")
            finally:
                dispose(engine)

    return {label: {"per_op_s": samples} for label, samples in result.items()}


def bench_raw_mq(args) -> dict:
    """Raw C message-queue put/get via both test toolkits (sanity baseline)."""
    n = min(max(args.msgs, 50_000), 200_000)
    toolkits = {"c_engine": ToolkitEngine, "c_engine_ex": ToolkitEngineEx}
    result = {label: [] for label in toolkits}

    for label, toolkit in toolkits.items():
        toolkit.bench_mq_put_get(min(n, 20_000))

    for _ in range(args.repeats):
        for label, toolkit in toolkits.items():
            result[label].append(toolkit.bench_mq_put_get(n))

    return {label: {"per_op_s": samples} for label, samples in result.items()}


# ---------------------------------------------------------------------------
# Orchestration + reporting
# ---------------------------------------------------------------------------

BASELINES = {
    "dispatch_exact": "c_engine.EventEngine",
    "dispatch_generic": "c_engine.EventEngine",
    "publish_get_roundtrip": "c_engine.EventEngine",
    "register_handler": "c_engine.EventEngine",
    "unregister_handler": "c_engine.EventEngine",
    "hook_lookup": "c_engine.EventEngine",
    "start_stop": "c_engine.EventEngine",
    "timer_register": "c_engine.EventEngineEx",
    "raw_mq": "c_engine",
}


def summarize(workload_result: dict, baseline_label: str) -> dict:
    """Convert raw per-engine samples into stats + ratio vs the baseline."""
    summary = {}
    for label, data in workload_result.items():
        if "msg_per_s" in data:
            stats = aggregate(data["msg_per_s"])
            entry = {"throughput_msg_s": stats}
            entry.update(data["latency_us"])
            entry["queue_latency_us"] = data["queue_latency_us"]
            entry["raw_trials"] = data["msg_per_s"]
        elif "deliveries_per_s" in data:
            stats = aggregate(data["deliveries_per_s"])
            entry = {"throughput_deliveries_s": stats}
            entry.update(data["latency_us"])
            entry["queue_latency_us"] = data["queue_latency_us"]
            entry["raw_trials"] = data["deliveries_per_s"]
        else:
            stats = aggregate(data["per_op_s"])
            entry = {"per_op_s": stats}
            entry["raw_trials"] = data["per_op_s"]
        summary[label] = entry

    base_stats = summary[baseline_label]
    for label, entry in summary.items():
        if label == baseline_label:
            entry["ratio_vs_baseline"] = 1.0
        elif "throughput_msg_s" in entry:
            entry["ratio_vs_baseline"] = ratio_vs(base_stats["throughput_msg_s"]["mean_s"], entry["throughput_msg_s"]["mean_s"])
        elif "throughput_deliveries_s" in entry:
            entry["ratio_vs_baseline"] = ratio_vs(base_stats["throughput_deliveries_s"]["mean_s"], entry["throughput_deliveries_s"]["mean_s"])
        else:
            entry["ratio_vs_baseline"] = ratio_vs(base_stats["per_op_s"]["mean_s"], entry["per_op_s"]["mean_s"])
    return {"baseline": baseline_label, "engines": summary}


def run_all(args) -> dict:
    print("preparing engines ...", flush=True)
    factories = build_factories(args)
    workload_fns = [
        ("dispatch_exact", lambda: bench_dispatch(args, factories)),
        ("dispatch_generic", lambda: bench_dispatch_generic(args)),
        ("publish_get_roundtrip", lambda: bench_publish_get_roundtrip(args, factories)),
        ("register_handler", lambda: bench_register_handler(args, factories)),
        ("unregister_handler", lambda: bench_unregister_handler(args, factories)),
        ("hook_lookup", lambda: bench_hook_lookup(args, factories)),
        ("start_stop", lambda: bench_start_stop(args, factories)),
        ("timer_register", lambda: bench_timer_register(args, factories)),
        ("raw_mq", lambda: bench_raw_mq(args)),
    ]
    results = {}
    for name, fn in workload_fns:
        print(f"  running [{name}] ...", flush=True)
        results[name] = summarize(fn(), BASELINES[name])
        print(f"  done [{name}]", flush=True)
    return results


def render_markdown(meta: dict, results: dict) -> str:
    lines = [
        "# EventEngine Benchmark Report",
        "",
        f"- library version: `{meta['version']}`",
        f"- git head: `{meta['git_head_short']}` (`{meta['git_head']}`)",
        f"- branch: `{meta['git_branch']}`",
        f"- timestamp: `{meta['timestamp']}`",
        f"- host: `{meta['platform']}` (`{meta['processor']}`, {meta['cpu_count']} cpus)",
        f"- python: `{meta['python']}` (`{meta['executable']}`)",
        "",
        "## Methodology",
        "",
        "- engines interleaved across trials; every workload warms up first",
        "- per-op samples: seconds per operation (micro-benchmarks) or messages",
        "  per second (producer/consumer); latency percentiles pooled over trials",
        "- `ratio_vs_baseline` > 1.0 means faster than the baseline",
        "",
    ]

    def engine_table(title: str, entries: dict, value_key: str, unit: str, baseline: str) -> None:
        factor = 1e6 if unit == "us" else 1.0
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| engine | mean | std | CV% | min | max | ratio vs baseline |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for label, entry in entries.items():
            stats = entry[value_key]
            mark = "1.000x" if label == baseline else f"{entry['ratio_vs_baseline']:.3f}x"
            lines.append(
                f"| {label} | {stats['mean_s'] * factor:,.2f} {unit} "
                f"| {stats['std_s'] * factor:,.2f} {unit} "
                f"| {stats['cv_pct']:.1f}% "
                f"| {stats['min_s'] * factor:,.2f} {unit} "
                f"| {stats['max_s'] * factor:,.2f} {unit} "
                f"| {mark} |"
            )
        lines.append("")

    def latency_table(title: str, entries: dict, queue: bool = False) -> None:
        suffix = "" if "latency" in title else " (latency, pooled over trials)"
        lines.append(f"### {title}{suffix}")
        lines.append("")
        lines.append("| engine | p50 | p95 | p99 | avg | max |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for label, entry in entries.items():
            lat = entry["queue_latency_us"] if queue else entry
            lines.append(
                f"| {label} | {lat['p50_us']:.2f} | {lat['p95_us']:.2f} | "
                f"{lat['p99_us']:.2f} | {lat['avg_us']:.2f} | {lat['max_us']:.2f} |"
            )
        lines.append("")

    for name, result in results.items():
        engines = result["engines"]
        baseline = result["baseline"]
        if name == "dispatch_exact":
            engine_table("dispatch_exact — throughput (exact-topic hook)", engines, "throughput_msg_s", "msg/s", baseline)
            latency_table("dispatch_exact — end-to-end latency (incl. producer backpressure)", engines)
            latency_table("dispatch_exact — queue latency (enqueue → handler)", engines, queue=True)
        elif name == "dispatch_generic":
            engine_table(f"dispatch_generic — deliveries/s ({GENERIC_HOOKS} generic hooks)", engines, "throughput_deliveries_s", "del/s", baseline)
            latency_table("dispatch_generic — end-to-end latency (incl. producer backpressure)", engines)
            latency_table("dispatch_generic — queue latency (enqueue → handler)", engines, queue=True)
        else:
            engine_table(f"{name} — per-op cost", engines, "per_op_s", "us", baseline)

    lines.append("## Notes")
    lines.append("")
    lines.append("- `raw_mq` isolates the C queue hot path; both toolkits run the same C code.")
    lines.append("- `dispatch_exact` includes the full path: pypayload allocation, queue, hook")
    lines.append("  dispatch and handler execution.")
    lines.append("- end-to-end latency is stamped before the blocking put, so it includes")
    lines.append("  producer-side backpressure when the queue is full; the queue-latency view")
    lines.append("  subtracts the producer's own put time (FIFO pairing) and measures the pure")
    lines.append("  enqueue -> handler path.")
    lines.append("- `timer_register` compares Python-thread timers (subclass) vs C timer tasks;")
    lines.append("  note the semantic difference: the subclass keeps one thread per interval,")
    lines.append("  the C engine replaces the previous interval.")
    lines.append("- `start_stop` is dominated by the 1 s idle wake-up granularity of the queue")
    lines.append("  wait (`DEFAULT_MQ_TIMEOUT_SECONDS`); it measures idle-engine stop latency.")
    lines.append("")
    lines.append("Results are machine-readable in `benchmark.json` (raw trials included).")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="smaller sizes and fewer repeats")
    parser.add_argument("--msgs", type=int, default=50_000, help="messages per dispatch trial (default 50000)")
    parser.add_argument("--repeats", type=int, default=5, help="trials per engine per workload (default 5)")
    parser.add_argument("--capacity", type=int, default=8192, help="message-queue capacity (default 8192)")
    parser.add_argument("--hooks", type=int, default=2_000, help="topics for register/unregister/lookup workloads (default 2000)")
    parser.add_argument("--cycles", type=int, default=5, help="start/stop cycles per trial (default 5; each idle stop waits out the 1s MQ wake-up)")
    parser.add_argument("--lookups", type=int, default=100_000, help="total lookups per trial (default 100000)")
    parser.add_argument("--timer-intervals", type=int, default=8, help="distinct timer intervals per trial (default 8)")
    parser.add_argument("--tag", default=None, help="extra suffix on the versioned artifact dir name")
    parser.add_argument("--out", default=None, help="override the artifact directory entirely")
    args = parser.parse_args(argv)

    if args.quick:
        args.msgs = min(args.msgs, 10_000)
        args.repeats = min(args.repeats, 3)
        args.hooks = min(args.hooks, 500)
        args.cycles = min(args.cycles, 3)
        args.lookups = min(args.lookups, 30_000)
        args.timer_intervals = min(args.timer_intervals, 4)

    args.warmup_ops = max(args.hooks // 2, 500)
    args.per_op_n = max(args.hooks, 2_000)

    out_dir = versioned_artifacts_dir(args.tag, args.out)
    meta = collect_env()

    t_start = time.perf_counter()
    results = run_all(args)
    wall = time.perf_counter() - t_start

    report = {
        "meta": meta,
        "params": {
            "msgs": args.msgs,
            "repeats": args.repeats,
            "capacity": args.capacity,
            "hooks": args.hooks,
            "cycles": args.cycles,
            "lookups": args.lookups,
            "timer_intervals": args.timer_intervals,
            "wall_time_s": wall,
            "generic_hooks": GENERIC_HOOKS,
        },
        "workloads": results,
    }

    with (out_dir / "benchmark.json").open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with (out_dir / "env.json").open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    with (out_dir / "benchmark.md").open("w", encoding="utf-8") as fh:
        fh.write(render_markdown(meta, results))

    print(f"\nArtifacts written to: {out_dir}")
    print(f"Wall time: {wall:.1f}s")

    for name, result in results.items():
        print(f"\n[{name}] baseline: {result['baseline']}")
        for label, entry in result["engines"].items():
            if "throughput_msg_s" in entry:
                s = entry["throughput_msg_s"]
                q = entry["queue_latency_us"]
                print(
                    f"  {label:<28} {s['mean_s']:>10,.0f} msg/s  "
                    f"(e2e p50={entry['p50_us']:.0f}us queue p50={q['p50_us']:.1f}us p95={q['p95_us']:.1f}us)  "
                    f"ratio={entry['ratio_vs_baseline']:.3f}"
                )
            elif "throughput_deliveries_s" in entry:
                s = entry["throughput_deliveries_s"]
                q = entry["queue_latency_us"]
                print(
                    f"  {label:<28} {s['mean_s']:>10,.0f} del/s  "
                    f"(e2e p50={entry['p50_us']:.0f}us queue p50={q['p50_us']:.1f}us p95={q['p95_us']:.1f}us)  "
                    f"ratio={entry['ratio_vs_baseline']:.3f}"
                )
            else:
                s = entry["per_op_s"]
                print(
                    f"  {label:<28} {s['mean_s'] * 1e6:>9.2f} us/op  "
                    f"(cv={s['cv_pct']:.1f}%)  ratio={entry['ratio_vs_baseline']:.3f}"
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
