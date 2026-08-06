"""Shared helpers for the event_engine test suites (capi / native / nt).

Provides:
    - ``oracle_parse`` / ``oracle_match``: an independent, plain-Python
      reimplementation of the topic parsing and matching contract, written
      from the C implementation in ``event_engine/capi/c_topic.h``. Test
      assertions compare implementation results against this oracle rather
      than reusing the implementation under test.
    - ``TOPIC_PARSE_CASES`` / ``MATCH_CASES`` / ``PARSE_ERROR_CASES``:
      the shared topic corpus exercised by both the capi and native suites.
    - ``PerfMetrics`` and ``bench_producer_consumer``: performance harness
      used by the performance test modules.
"""

import os
import re
import sys
import threading
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "artifacts")


# ---------------------------------------------------------------------------
# Oracle: topic parsing (mirrors c_topic_parse in event_engine/capi/c_topic.h)
# ---------------------------------------------------------------------------

def oracle_parse(topic_str: str) -> list:
    """Parse ``topic_str`` into part specs using the documented contract.

    Returns a list of ``('exact', s)``, ``('any', name)``, ``('range', [opts])``
    or ``('pattern', re)`` tuples.

    Contract (from the C parser):
        - ``.`` separates tokens; empty tokens are dropped.
        - ``./re/`` (or ``/re/`` at the start) is a pattern part; it must be
          closed by ``/`` at the end of the string or by ``/.``.
        - ``+name`` (non-empty name) is an any part; a lone ``+`` is exact.
        - ``{name}`` (non-empty) is an any part; an unclosed ``{`` is exact.
        - ``(a|b)`` is a range part (empty options dropped); an unclosed or
          empty ``()`` is exact.

    Raises:
        ValueError: on an unclosed pattern (the implementation raises too).
    """
    parts = []
    n = len(topic_str)
    i = 0

    while i < n:
        # Pattern: "./" at the start, or '.' directly followed by '/'
        if (i == 0 and topic_str[0] == "/") or (
                i + 1 < n and topic_str[i] == "." and topic_str[i + 1] == "/"):
            content_start = i + 2 if topic_str[i] == "." else 1
            j = content_start
            found_close = False
            while j < n:
                if (j == n - 1 and topic_str[j] == "/") or (
                        j + 1 < n and topic_str[j] == "/" and topic_str[j + 1] == "."):
                    parts.append(("pattern", topic_str[content_start:j]))
                    i = j + 2
                    found_close = True
                    break
                j += 1
            if not found_close:
                raise ValueError(f"unclosed pattern in {topic_str!r}")
            continue

        # Normal token: run up to the next '.' (unless it starts "./")
        token_start = i
        while i < n:
            if topic_str[i] == ".":
                if i + 1 < n and topic_str[i + 1] == "/":
                    break
                break
            i += 1
        token = topic_str[token_start:i]

        if token:
            if len(token) >= 2 and token[0] == "+":
                parts.append(("any", token[1:]))
            elif len(token) >= 3 and token[0] == "{" and token[-1] == "}":
                parts.append(("any", token[1:-1]))
            elif len(token) >= 3 and token[0] == "(" and token[-1] == ")":
                opts = [o for o in token[1:-1].split("|") if o]
                parts.append(("range", opts))
            else:
                parts.append(("exact", token))

        # Consume the terminating '.' unless it starts "./"
        if i < n and topic_str[i] == ".":
            if i + 1 >= n or topic_str[i + 1] != "/":
                i += 1

    return parts


def oracle_match(a_str: str, b_str: str) -> list:
    """Match two topic strings independently; returns per-node result dicts.

    Each node dict has ``'matched'`` and ``'literal'`` keys. The oracle
    mirrors the C match semantics:
        - identical non-empty literals short-circuit to a single matched node
          whose literal is the full topic literal;
        - per-part matching requires exactly one exact side;
        - matching stops at the first failing part;
        - a length mismatch appends one trailing failed node.
    """
    if a_str and b_str and a_str == b_str:
        return [{"matched": True, "literal": a_str}]

    parts_a = oracle_parse(a_str)
    parts_b = oracle_parse(b_str)
    nodes = []
    n = min(len(parts_a), len(parts_b))
    i = 0

    while i < n:
        pa, pb = parts_a[i], parts_b[i]
        if pa[0] == "exact":
            exact, other = pa, pb
        elif pb[0] == "exact":
            exact, other = pb, pa
        else:
            # Neither side is exact → fail-fast
            nodes.append({"matched": False, "literal": None})
            return nodes

        literal = exact[1]
        if other[0] == "exact":
            matched = exact[1] == other[1]
        elif other[0] == "any":
            matched = True
        elif other[0] == "range":
            matched = exact[1] in other[1]
        elif other[0] == "pattern":
            # POSIX ERE regexec is unanchored → re.search
            # Note: the C match code does NOT populate the literal field
            # for pattern matches (only EXACT/ANY/RANGE set it).
            matched = re.search(other[1], exact[1]) is not None
            literal = None if matched else literal
        else:
            matched = False

        if not matched:
            nodes.append({"matched": False, "literal": None})
            return nodes
        nodes.append({"matched": True, "literal": literal})
        i += 1

    if i < len(parts_a) or i < len(parts_b):
        nodes.append({"matched": False, "literal": None})
    return nodes


# ---------------------------------------------------------------------------
# Shared topic corpus
# ---------------------------------------------------------------------------

TOPIC_PARSE_CASES = [
    ("a.b.c", [("exact", "a"), ("exact", "b"), ("exact", "c")]),
    ("a.+b.c", [("exact", "a"), ("any", "b"), ("exact", "c")]),
    ("+x", [("any", "x")]),
    ("+x.y", [("any", "x"), ("exact", "y")]),
    ("pre.+suffix", [("exact", "pre"), ("any", "suffix")]),
    ("a.{b}.{c}.{d}.{e}", [("exact", "a"), ("any", "b"), ("any", "c"), ("any", "d"), ("any", "e")]),
    ("realtime.{ticker}.{dtype}", [("exact", "realtime"), ("any", "ticker"), ("any", "dtype")]),
    ("(a|b).c", [("range", ["a", "b"]), ("exact", "c")]),
    ("(x)", [("range", ["x"])]),
    ("(a|)", [("range", ["a"])]),
    ("./[0-9]{6}/.x", [("pattern", "[0-9]{6}"), ("exact", "x")]),
    ("log./[0-9]{6}/.+suffix", [("exact", "log"), ("pattern", "[0-9]{6}"), ("any", "suffix")]),
    ("./a\\.b\\.[0-9]/.(x|y|z).+end",
     [("pattern", r"a\.b\.[0-9]"), ("range", ["x", "y", "z"]), ("any", "end")]),
    ("用户.+操作", [("exact", "用户"), ("any", "操作")]),
    ("pre.+", [("exact", "pre"), ("exact", "+")]),
    ("+", [("exact", "+")]),
    ("pre.().post", [("exact", "pre"), ("exact", "()"), ("exact", "post")]),
    ("pre.{}.post", [("exact", "pre"), ("exact", "{}"), ("exact", "post")]),
    ("(unclosed", [("exact", "(unclosed")]),
    ("a.{unclosed.b", [("exact", "a"), ("exact", "{unclosed"), ("exact", "b")]),
    ("a.", [("exact", "a")]),
    ("a..b", [("exact", "a"), ("exact", "b")]),
    ("file.v1", [("exact", "file"), ("exact", "v1")]),
    ("/^[0-9]{6}\\.(SZ|SH)$/.abc.(user|guest|admin)",
     [("pattern", "^[0-9]{6}\\.(SZ|SH)$"), ("exact", "abc"), ("range", ["user", "guest", "admin"])]),
    ("", []),
]

PARSE_ERROR_CASES = [
    "abc./unclosed",
    "./no_close",
    "./pat/x",
]

MATCH_CASES = [
    ("a.b.c", "a.b.c", True),
    ("a.b", "a.b", True),
    ("a.+x", "a.test", True),
    ("base.+value", "base.test", True),
    ("cmd.+", "cmd.+", True),
    ("cmd.+", "cmd.x", False),
    ("event.(user|admin).action", "event.admin.action", True),
    ("event.(user|admin).action", "event.guest.action", False),
    ("log./[0-9]{6}/.+suffix", "log.123456.extra.suffix", False),
    ("log./[0-9]{6}/.+suffix", "log.123.extra.suffix", False),
    ("a.b", "a.b.c", False),
    ("a.b.c", "a.b", False),
    ("x.b", "a.b", False),
    ("a.x", "a.y", False),
    ("a.+x", "a.+y", False),
    ("a.+b", "a.+b", True),
    ("a.{b}.{c}.{d}.{e}", "a.2.3.4.5", True),
    ("realtime.{ticker}.{dtype}", "realtime.600010.TransactionData", True),
    ("realtime.{ticker}.{dtype}", "realtime.600010.SH.TransactionData", False),
    ("abc.(user|guest|admin)./^[0-9]{6}\\.(SZ|SH)$/.+suffix", "abc.user.600000.SZ.extra.suffix", False),
    ("abc.(user|guest|admin)./^[0-9]{6}\\.(SZ|SH)$/.+suffix", "abc.hacker.600000.SZ.extra.suffix", False),
    ("abc.(user|guest|admin)./^[0-9]{6}\\.(SZ|SH)$/.+suffix", "abc.user.123.SZ.extra.suffix", False),
    ("a./[0-9]{6}/.b", "a.pre600010.b", True),
    ("a./^x$/.b", "a.x.b", True),
    ("a./^x$/.b", "a.xy.b", False),
    ("a", "b", False),
]


# ---------------------------------------------------------------------------
# Performance harness
# ---------------------------------------------------------------------------

class PerfMetrics:
    """Consumer-side metrics: count, per-message latencies, wall clock.

    Thread-safe updates from a handler running on the engine thread.
    """

    __slots__ = ("count", "latencies_ns", "started_at_ns", "finished_at_ns", "_lock")

    def __init__(self) -> None:
        self.count = 0
        self.latencies_ns = []
        self.started_at_ns = None
        self.finished_at_ns = None
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

    def wall_time_s(self) -> float:
        if self.started_at_ns is None or self.finished_at_ns is None:
            return 0.0
        return (self.finished_at_ns - self.started_at_ns) / 1e9

    def throughput_mps(self) -> float:
        wt = self.wall_time_s()
        return self.count / wt if wt > 0 else 0.0

    def latency_stats_ms(self) -> dict:
        if not self.latencies_ns:
            return {"min": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        xs = sorted(self.latencies_ns)
        n = len(xs)
        return {
            "min": xs[0] / 1e6,
            "avg": (sum(xs) / n) / 1e6,
            "p50": xs[int(0.5 * (n - 1))] / 1e6,
            "p95": xs[int(0.95 * (n - 1))] / 1e6,
            "max": xs[-1] / 1e6,
        }


def bench_producer_consumer(engine, topic, total_messages, timeout_s=20.0):
    """Run a producer/consumer throughput benchmark against ``engine``.

    Args:
        engine: A started-capable engine instance.
        topic: The topic to publish on.
        total_messages: Number of messages to produce.
        timeout_s: Max wall-clock seconds to wait for consumption.

    Returns:
        ``(finished, metrics)`` where ``finished`` is whether all messages
        were consumed within the timeout, and ``metrics`` is a PerfMetrics.
    """
    metrics = PerfMetrics()
    processed_all = threading.Event()

    def handler(sent_ts_ns: int):
        now = time.perf_counter_ns()
        metrics.record(now - sent_ts_ns)
        if metrics.count >= total_messages:
            processed_all.set()

    engine.register_handler(topic, handler)

    def producer():
        for _ in range(total_messages):
            ts = time.perf_counter_ns()
            engine.put(topic, ts, block=True)

    producer_thread = threading.Thread(target=producer, name="perf-producer", daemon=True)

    engine.start()
    metrics.start()
    producer_thread.start()

    finished = processed_all.wait(timeout=timeout_s)
    metrics.stop()

    engine.stop()
    producer_thread.join(timeout=5)
    return finished, metrics
