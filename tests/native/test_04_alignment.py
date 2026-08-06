"""API alignment guarantee: the native layer behaves exactly like capi.

Every scenario in this module executes the same operations against the
Cython (``event_engine.capi``) and pure-Python (``event_engine.native``)
implementations and asserts identical observable outcomes — values,
exception types, container shapes and dispatch behavior.

This is the unittest-level guarantee that the native fallback API is
aligned with the capi API.

Known, documented divergences (asserted as such, not aligned):
    - ``owner`` flags (C memory ownership has no Python equivalent).
    - exception type for unclosed-pattern parse errors (both raise).
    - ``repr`` strings (class names differ: ``Topic`` vs ``PyTopic``).
"""

import inspect
import threading
import unittest

from tests._common import MATCH_CASES, PARSE_ERROR_CASES, TOPIC_PARSE_CASES, oracle_parse

from event_engine import capi as capi_pkg
from event_engine import native as native_pkg

CAPI_EVENT = capi_pkg.c_event
NATIVE_EVENT = native_pkg.event

# --- Scenario helpers ------------------------------------------------------

def _outcome(fn, normalize=None):
    """Run ``fn``; return ('ok', value) or ('raise', exception-type-name)."""
    if normalize is None:
        normalize = lambda v: v
    try:
        return ("ok", normalize(fn()))
    except Exception as exc:  # noqa: BLE001 — outcome capture is the point
        return ("raise", type(exc).__name__)


def _part_specs(topic):
    """Normalized part specs of a topic (same shape for both layers)."""
    out = []
    for part in topic:
        if type(part).__name__.endswith("PartExact"):
            out.append(("exact", part.part))
        elif type(part).__name__.endswith("PartAny"):
            out.append(("any", part.name))
        elif type(part).__name__.endswith("PartRange"):
            out.append(("range", list(part.options())))
        elif type(part).__name__.endswith("PartPattern"):
            out.append(("pattern", part.pattern))
        else:
            out.append((type(part).__name__,))
    return out


def _topic_outcome(fn):
    """Normalize a topic-producing call to (value, is_exact, part_specs)."""
    def normalize(topic):
        return (topic.value, topic.is_exact, _part_specs(topic))
    return _outcome(fn, normalize)


def _match_outcome(fn):
    """Normalize a match-producing call to (matched, len, nodes)."""
    def normalize(result):
        return (
            bool(result),
            len(result),
            [(n["matched"], n["literal"]) for n in result],
        )
    return _outcome(fn, normalize)


class TestTopicAlignment(unittest.TestCase):
    """Contract: capi Topic and native PyTopic parse/match/format identically."""

    def test_00_parse_corpus_alignment(self) -> None:
        """Both layers parse every corpus topic to identical part specs."""
        for topic_str, expected in TOPIC_PARSE_CASES:
            with self.subTest(topic=topic_str):
                self.assertEqual(oracle_parse(topic_str), expected)
                capi_out = _topic_outcome(lambda: capi_pkg.Topic(topic_str))
                native_out = _topic_outcome(lambda: native_pkg.PyTopic(topic_str))
                self.assertEqual(capi_out, native_out)

    def test_01_parse_error_corpus_alignment(self) -> None:
        """Both layers raise on unclosed patterns (type-agnostic)."""
        for topic_str in PARSE_ERROR_CASES:
            with self.subTest(topic=topic_str):
                capi_out = _topic_outcome(lambda: capi_pkg.Topic(topic_str))
                native_out = _topic_outcome(lambda: native_pkg.PyTopic(topic_str))
                self.assertEqual(capi_out[0], "raise")
                self.assertEqual(native_out[0], "raise")

    def test_02_match_corpus_alignment(self) -> None:
        """Both layers match the entire corpus identically (bool/len/nodes)."""
        for a_str, b_str, expected in MATCH_CASES:
            with self.subTest(a=a_str, b=b_str, expected=expected):
                capi_out = _match_outcome(lambda: capi_pkg.Topic(a_str).match(capi_pkg.Topic(b_str)))
                native_out = _match_outcome(lambda: native_pkg.PyTopic(a_str).match(native_pkg.PyTopic(b_str)))
                self.assertEqual(capi_out, native_out)
                self.assertEqual(capi_out[0], "ok")

    def test_03_identical_topic_short_circuit(self) -> None:
        """Both layers short-circuit identical topics to one node."""
        capi_out = _match_outcome(lambda: capi_pkg.Topic("a.b.c").match(capi_pkg.Topic("a.b.c")))
        native_out = _match_outcome(lambda: native_pkg.PyTopic("a.b.c").match(native_pkg.PyTopic("a.b.c")))
        self.assertEqual(capi_out, native_out)
        self.assertEqual(capi_out[1][0], True)
        self.assertEqual(capi_out[1][1], 1)
        self.assertEqual(capi_out[1][2][0][1], "a.b.c")

    def test_04_format_map_alignment(self) -> None:
        """format_map behaves identically across strict/lenient/internalized."""
        template = "realtime.{ticker}.{dtype}"
        scenarios = [
            ({"ticker": "600010.SH", "dtype": "TickData"}, True),
            ({"ticker": "600010.SH", "dtype": "TickData"}, False),
            ({"ticker": "600010.SH"}, False),
            ({}, False),
        ]
        for mapping, strict in scenarios:
            with self.subTest(mapping=mapping, strict=strict):
                capi_out = _topic_outcome(lambda: capi_pkg.Topic(template).format_map(dict(mapping), strict=strict))
                native_out = _topic_outcome(lambda: native_pkg.PyTopic(template).format_map(dict(mapping), strict=strict))
                self.assertEqual(capi_out, native_out)

        # strict=True with missing key raises KeyError on both
        capi_out = _topic_outcome(lambda: capi_pkg.Topic(template).format_map({"ticker": "600010.SH"}, strict=True))
        native_out = _topic_outcome(lambda: native_pkg.PyTopic(template).format_map({"ticker": "600010.SH"}, strict=True))
        self.assertEqual(capi_out, native_out)
        self.assertEqual(capi_out[0], "raise")
        self.assertEqual(capi_out[1], "KeyError")

    def test_05_value_setter_alignment(self) -> None:
        """value assignment behaves identically (valid and invalid)."""
        for new_value in ["x.+y", "a.(p|q)./re/", "plain"]:
            with self.subTest(value=new_value):
                capi_topic = capi_pkg.Topic("a.b")
                native_topic = native_pkg.PyTopic("a.b")
                capi_out = _topic_outcome(lambda: setattr(capi_topic, "value", new_value) or capi_topic)
                native_out = _topic_outcome(lambda: setattr(native_topic, "value", new_value) or native_topic)
                self.assertEqual(capi_out, native_out)

        # invalid assignment raises on both
        capi_topic = capi_pkg.Topic("a.b")
        native_topic = native_pkg.PyTopic("a.b")
        capi_out = _topic_outcome(lambda: setattr(capi_topic, "value", "./unclosed") or capi_topic)
        native_out = _topic_outcome(lambda: setattr(native_topic, "value", "./unclosed") or native_topic)
        self.assertEqual(capi_out[0], "raise")
        self.assertEqual(native_out[0], "raise")

    def test_06_builders_alignment(self) -> None:
        """join / from_parts / append / __add__ produce identical topics."""
        capi_out = _topic_outcome(lambda: capi_pkg.Topic.join(["a", "b", "c"]))
        native_out = _topic_outcome(lambda: native_pkg.PyTopic.join(["a", "b", "c"]))
        self.assertEqual(capi_out, native_out)

        capi_parts = [capi_pkg.TopicPartExact("a", alloc=True),
                      capi_pkg.TopicPartAny("b", alloc=True),
                      capi_pkg.TopicPartRange(["x", "y"], alloc=True)]
        native_parts = [native_pkg.PyTopicPartExact("a", alloc=True),
                        native_pkg.PyTopicPartAny("b", alloc=True),
                        native_pkg.PyTopicPartRange(["x", "y"], alloc=True)]
        capi_out = _topic_outcome(lambda: capi_pkg.Topic.from_parts(capi_parts))
        native_out = _topic_outcome(lambda: native_pkg.PyTopic.from_parts(native_parts))
        self.assertEqual(capi_out, native_out)

        capi_out = _topic_outcome(lambda: capi_pkg.Topic("a") + capi_pkg.Topic("b"))
        native_out = _topic_outcome(lambda: native_pkg.PyTopic("a") + native_pkg.PyTopic("b"))
        self.assertEqual(capi_out, native_out)

        capi_out = _topic_outcome(lambda: capi_pkg.Topic("a").append(capi_pkg.TopicPartAny("n", alloc=True)))
        native_out = _topic_outcome(lambda: native_pkg.PyTopic("a").append(native_pkg.PyTopicPartAny("n", alloc=True)))
        self.assertEqual(capi_out, native_out)


class TestEventHookAlignment(unittest.TestCase):
    """Contract: capi EventHook and native EventHook behave identically."""

    def _build_hook_pair(self, topic_value="align.hook", ex=False):
        capi_topic = capi_pkg.Topic(topic_value)
        native_topic = native_pkg.PyTopic(topic_value)
        if ex:
            return CAPI_EVENT.EventHookEx(capi_topic), NATIVE_EVENT.EventHookEx(native_topic)
        return CAPI_EVENT.EventHook(capi_topic), NATIVE_EVENT.EventHook(native_topic)

    def _payload_pair(self, topic_value="align.hook", args=(), kwargs=None):
        kwargs = {} if kwargs is None else kwargs
        capi_payload = CAPI_EVENT.MessagePayload(capi_pkg.Topic(topic_value), args, dict(kwargs))
        native_payload = NATIVE_EVENT.PyMessagePayload(native_pkg.PyTopic(topic_value), args, dict(kwargs))
        return capi_payload, native_payload

    def test_00_registration_semantics_alignment(self) -> None:
        """add/remove/len/contains/deduplicate behave identically."""
        capi_hook, native_hook = self._build_hook_pair()

        def h1(a):
            pass

        def h2(a, topic=None):
            pass

        for hook in (capi_hook, native_hook):
            hook.add_handler(h1)
            hook.add_handler(h2)

        def norm(hook):
            return (
                len(hook),
                h1 in hook,
                h2 in hook,
                [(h["fn"], h["idx"], h["with_topic"]) for h in hook.handlers],
            )

        self.assertEqual(norm(capi_hook), norm(native_hook))

        # += deduplicates identically
        capi_hook += h1
        native_hook += h1
        self.assertEqual(len(capi_hook), len(native_hook))
        self.assertEqual(len(capi_hook), 2)

        # -= removes identically
        capi_hook -= h2
        native_hook -= h2
        self.assertEqual(len(capi_hook), len(native_hook))

        # deduplicate flag
        capi_hook.add_handler(h1, deduplicate=True)
        native_hook.add_handler(h1, deduplicate=True)
        self.assertEqual(len(capi_hook), len(native_hook))

        # clear
        capi_hook.clear()
        native_hook.clear()
        self.assertEqual(len(capi_hook), 0)
        self.assertEqual(len(native_hook), 0)

    def test_01_trigger_conventions_alignment(self) -> None:
        """Both layers dispatch no-topic and with-topic handlers identically."""
        capi_payload, native_payload = self._payload_pair(args=(1, "x"), kwargs={"d": 432})
        capi_hook, native_hook = self._build_hook_pair()
        capi_log, native_log = [], []
        native_log2 = []

        def capi_handler(a, b, d, topic=None, **kw):
            capi_log.append((a, b, d, topic.value))

        def native_handler(a, b, d, topic=None, **kw):
            native_log.append((a, b, d, topic.value))

        capi_hook.add_handler(capi_handler)
        native_hook.add_handler(native_handler)
        capi_hook.trigger(capi_payload)
        native_hook.trigger(native_payload)
        self.assertEqual(capi_log, native_log)

        # no-topic handlers receive args/kwargs only, on both layers
        def capi_bare(a, b, d):
            native_log2.append(("capi", a, b, d))

        def native_bare(a, b, d):
            native_log2.append(("native", a, b, d))

        capi_hook.clear()
        native_hook.clear()
        capi_hook.add_handler(capi_bare)
        native_hook.add_handler(native_bare)
        capi_hook.trigger(capi_payload)
        native_hook.trigger(native_payload)
        self.assertEqual(native_log2, [("capi", 1, "x", 432), ("native", 1, "x", 432)])

    def test_02_exception_isolation_alignment(self) -> None:
        """Both layers swallow handler exceptions and run remaining handlers."""
        capi_payload, native_payload = self._payload_pair(args=(1,), kwargs={})
        capi_hook, native_hook = self._build_hook_pair()
        capi_ran, native_ran = [], []

        def failing(a):
            raise ValueError("boom")

        def ok_capi(a):
            capi_ran.append(a)

        def ok_native(a):
            native_ran.append(a)

        for hook, ok in ((capi_hook, ok_capi), (native_hook, ok_native)):
            hook.add_handler(failing)
            hook.add_handler(ok)

        capi_hook.trigger(capi_payload)  # must not raise
        native_hook.trigger(native_payload)  # must not raise
        self.assertEqual(capi_ran, [1])
        self.assertEqual(native_ran, [1])

    def test_03_ex_hook_stats_alignment(self) -> None:
        """EventHookEx stats dict shape and accumulation are identical."""
        capi_hook, native_hook = self._build_hook_pair(ex=True)
        capi_payload, native_payload = self._payload_pair()

        def capi_slow(a):
            pass

        def native_slow(a):
            pass

        capi_hook.add_handler(capi_slow)
        native_hook.add_handler(native_slow)
        capi_hook.trigger(capi_payload)
        capi_hook.trigger(capi_payload)
        native_hook.trigger(native_payload)
        native_hook.trigger(native_payload)

        self.assertEqual(set(capi_hook.stats.keys()), set(native_hook.stats.keys()))
        self.assertEqual(capi_hook.stats["n_calls"], native_hook.stats["n_calls"])
        self.assertEqual(capi_hook.stats["n_calls"], 2)

    def test_04_payload_alignment(self) -> None:
        """Payload construction and accessors are identical."""
        capi_payload, native_payload = self._payload_pair(args=(1, 2), kwargs={"k": "v"})
        self.assertEqual(capi_payload.args, native_payload.args)
        self.assertEqual(capi_payload.kwargs, native_payload.kwargs)
        self.assertEqual(capi_payload.seq_id, native_payload.seq_id)
        self.assertEqual(capi_payload.topic.value, native_payload.topic.value)
        self.assertEqual(capi_payload.kwargs_with_topic["k"], native_payload.kwargs_with_topic["k"])
        self.assertEqual(
            capi_payload.kwargs_with_topic["topic"].value,
            native_payload.kwargs_with_topic["topic"].value,
        )


class TestEngineAlignment(unittest.TestCase):
    """Contract: capi EventEngine and native EventEngine behave identically."""

    def _engine_pair(self, capacity=16):
        return capi_pkg.EventEngine(capacity=capacity), native_pkg.EventEngine(capacity=capacity)

    def test_00_registry_alignment(self) -> None:
        """Hook registry semantics are identical (incl. exceptions)."""
        capi_engine, native_engine = self._engine_pair()
        try:
            for engine, topic_cls in ((capi_engine, capi_pkg.Topic), (native_engine, native_pkg.PyTopic)):
                topic = topic_cls("align.registry")

                def handler(a):
                    pass

                engine.register_handler(topic, handler)
                self.assertEqual(len(engine), 1)
                self.assertIsNotNone(engine.get_hook(topic))
                engine.unregister_handler(topic, handler)
                self.assertEqual(len(engine), 0)

            # duplicate hook raises KeyError on both
            def dup(engine, topic_cls, hook_cls):
                topic = topic_cls("align.dup")
                engine.register_hook(hook_cls(topic))
                engine.register_hook(hook_cls(topic))

            capi_out = _outcome(lambda: dup(capi_engine, capi_pkg.Topic, CAPI_EVENT.EventHook))
            native_out = _outcome(lambda: dup(native_engine, native_pkg.PyTopic, NATIVE_EVENT.EventHook))
            self.assertEqual(capi_out, native_out)
            self.assertEqual(capi_out[1], "KeyError")

            # missing hook raises KeyError on both
            capi_out = _outcome(lambda: capi_engine.get_hook(capi_pkg.Topic("align.missing")))
            native_out = _outcome(lambda: native_engine.get_hook(native_pkg.PyTopic("align.missing")))
            self.assertEqual(capi_out, native_out)
            self.assertEqual(capi_out[1], "KeyError")
        finally:
            capi_engine.clear()
            native_engine.clear()

    def test_01_queue_alignment(self) -> None:
        """put/get/Full/Empty/seq_id/occupied behave identically."""
        capi_engine, native_engine = self._engine_pair(capacity=2)
        try:
            for engine, topic_cls in ((capi_engine, capi_pkg.Topic), (native_engine, native_pkg.PyTopic)):
                topic = topic_cls("align.queue")

                def handler(a):
                    pass

                engine.register_handler(topic, handler)
                engine.put(topic, 1, block=False)
                engine.put(topic, 2, block=False)
                payload = engine.get(block=False)
                self.assertEqual(payload.args, (1,))
                self.assertEqual(engine.seq_id, 2)
                self.assertEqual(engine.occupied, 1)

            # Full on both
            def fill_and_overflow(engine, topic_cls):
                topic = topic_cls("align.queue")
                engine.put(topic, 1, block=False)
                engine.put(topic, 2, block=False)
                engine.put(topic, 3, block=False)

            capi_out = _outcome(lambda: fill_and_overflow(capi_engine, capi_pkg.Topic))
            native_out = _outcome(lambda: fill_and_overflow(native_engine, native_pkg.PyTopic))
            self.assertEqual(capi_out, native_out)
            self.assertEqual(capi_out[1], "Full")

            # Empty on both
            def drain(engine, topic_cls):
                while True:
                    engine.get(block=False)

            capi_out = _outcome(lambda: drain(capi_engine, capi_pkg.Topic))
            native_out = _outcome(lambda: drain(native_engine, native_pkg.PyTopic))
            self.assertEqual(capi_out, native_out)
            self.assertEqual(capi_out[1], "Empty")

            # non-exact topic raises ValueError on both
            capi_out = _outcome(lambda: capi_engine.put(capi_pkg.Topic("align.+any"), 1))
            native_out = _outcome(lambda: native_engine.put(native_pkg.PyTopic("align.+any"), 1))
            self.assertEqual(capi_out, native_out)
            self.assertEqual(capi_out[1], "ValueError")
        finally:
            capi_engine.clear()
            native_engine.clear()

    def test_02_dispatch_alignment(self) -> None:
        """start/put/stop deliver identical events to identical handlers."""
        capi_engine, native_engine = self._engine_pair(capacity=16)
        capi_received, native_received = [], []

        def capi_handler(a, topic=None, **kw):
            capi_received.append((a, topic.value))

        def native_handler(a, topic=None, **kw):
            native_received.append((a, topic.value))

        capi_engine.register_handler(capi_pkg.Topic("align.dispatch"), capi_handler)
        native_engine.register_handler(native_pkg.PyTopic("align.dispatch"), native_handler)
        try:
            capi_engine.start()
            native_engine.start()
            capi_engine.put(capi_pkg.Topic("align.dispatch"), 42)
            native_engine.put(native_pkg.PyTopic("align.dispatch"), 42)

            deadline = threading.Event()
            while (not capi_received or not native_received) and not deadline.wait(3.0):
                pass

            capi_engine.stop()
            native_engine.stop()
            self.assertEqual(capi_received, native_received)
            self.assertEqual(capi_received, [(42, "align.dispatch")])
        finally:
            if capi_engine.active:
                capi_engine.stop()
            if native_engine.active:
                native_engine.stop()
            capi_engine.clear()
            native_engine.clear()

    def test_03_generic_routing_alignment(self) -> None:
        """Generic topic hooks match identically during dispatch."""
        capi_engine, native_engine = self._engine_pair(capacity=16)
        capi_received, native_received = [], []

        def capi_handler(a, topic=None, **kw):
            capi_received.append(topic.value)

        def native_handler(a, topic=None, **kw):
            native_received.append(topic.value)

        capi_engine.register_handler(capi_pkg.Topic("align.any.+generic"), capi_handler)
        native_engine.register_handler(native_pkg.PyTopic("align.any.+generic"), native_handler)
        try:
            capi_engine.start()
            native_engine.start()
            capi_engine.put(capi_pkg.Topic("align.any.generic"), 1)
            native_engine.put(native_pkg.PyTopic("align.any.generic"), 1)

            deadline = threading.Event()
            while (not capi_received or not native_received) and not deadline.wait(3.0):
                pass

            capi_engine.stop()
            native_engine.stop()
            self.assertEqual(capi_received, native_received)
            self.assertEqual(capi_received, ["align.any.generic"])
        finally:
            if capi_engine.active:
                capi_engine.stop()
            if native_engine.active:
                native_engine.stop()
            capi_engine.clear()
            native_engine.clear()

    def test_04_timer_alignment(self) -> None:
        """EventEngineEx timers produce identical topics and payload shapes."""
        capi_engine = capi_pkg.EventEngineEx(capacity=16)
        native_engine = native_pkg.EventEngineEx(capacity=16)
        capi_ticks, native_ticks = [], []

        def capi_handler(**kw):
            capi_ticks.append(kw)

        def native_handler(**kw):
            native_ticks.append(kw)

        try:
            capi_engine.start()
            native_engine.start()
            capi_topic = capi_engine.get_timer(interval=0.05)
            native_topic = native_engine.get_timer(interval=0.05)
            self.assertEqual(capi_topic.value, native_topic.value)

            capi_engine.register_handler(capi_topic, capi_handler)
            native_engine.register_handler(native_topic, native_handler)

            deadline = threading.Event()
            while (len(capi_ticks) < 2 or len(native_ticks) < 2) and not deadline.wait(5.0):
                pass

            capi_engine.stop()
            native_engine.stop()
            self.assertGreaterEqual(len(capi_ticks), 2)
            self.assertGreaterEqual(len(native_ticks), 2)
            self.assertEqual(capi_ticks[0]["interval"], native_ticks[0]["interval"])
            self.assertEqual(capi_ticks[0]["interval"], 0.05)
            self.assertEqual(set(capi_ticks[0].keys()), set(native_ticks[0].keys()))
        finally:
            if capi_engine.active:
                capi_engine.stop()
            if native_engine.active:
                native_engine.stop()
            capi_engine.clear()
            native_engine.clear()


class TestSignatureAlignment(unittest.TestCase):
    """Contract: public method signatures (parameter names) match."""

    SIGNATURE_PAIRS = [
        ("Topic", ["append", "match", "format_map", "format", "update_literal"]),
        ("EventHook", ["add_handler", "remove_handler", "trigger", "clear"]),
        ("EventEngine", [
            "register_hook", "unregister_hook", "register_handler", "unregister_handler",
            "get_hook", "get", "put", "publish", "start", "stop", "clear",
            "activate", "deactivate", "run", "event_hooks", "topics", "items",
        ]),
    ]

    def _param_names(self, obj, method: str) -> list:
        return list(inspect.signature(getattr(obj, method)).parameters.keys())

    def test_00_topic_signatures(self) -> None:
        """Topic methods expose identical parameter names."""
        capi_topic = capi_pkg.Topic("a.b")
        native_topic = native_pkg.PyTopic("a.b")
        for method in self.SIGNATURE_PAIRS[0][1]:
            with self.subTest(method=method):
                self.assertEqual(
                    self._param_names(capi_topic, method),
                    self._param_names(native_topic, method),
                )

    def test_01_hook_signatures(self) -> None:
        """EventHook methods expose identical parameter names."""
        capi_hook = CAPI_EVENT.EventHook(capi_pkg.Topic("a.b"))
        native_hook = NATIVE_EVENT.EventHook(native_pkg.PyTopic("a.b"))
        for method in self.SIGNATURE_PAIRS[1][1]:
            with self.subTest(method=method):
                self.assertEqual(
                    self._param_names(capi_hook, method),
                    self._param_names(native_hook, method),
                )

    def test_02_engine_signatures(self) -> None:
        """EventEngine methods expose identical parameter names."""
        capi_engine = capi_pkg.EventEngine()
        native_engine = native_pkg.EventEngine()
        try:
            for method in self.SIGNATURE_PAIRS[2][1]:
                with self.subTest(method=method):
                    self.assertEqual(
                        self._param_names(capi_engine, method),
                        self._param_names(native_engine, method),
                    )
        finally:
            capi_engine.clear()
            native_engine.clear()

    def test_03_engine_ex_signatures(self) -> None:
        """EventEngineEx timer methods expose identical parameter names."""
        capi_engine = capi_pkg.EventEngineEx()
        native_engine = native_pkg.EventEngineEx()
        try:
            for method in ["get_timer", "run_timer", "minute_timer", "second_timer"]:
                with self.subTest(method=method):
                    self.assertEqual(
                        self._param_names(capi_engine, method),
                        self._param_names(native_engine, method),
                    )
        finally:
            capi_engine.clear()
            native_engine.clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
