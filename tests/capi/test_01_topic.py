"""Contract tests for the Cython topic implementation (event_engine.capi.c_topic).

The topic parser/matcher contract is verified against an independent oracle
(``tests._common.oracle_parse`` / ``oracle_match``) derived from the C
implementation in ``event_engine/capi/c_topic.h``.

Internal C-level state (part chain, key, internal map) is additionally
verified through the ``TopicTestToolkit`` test toolkit in ``c_topic.pyx``.
"""

import unittest

from tests._common import MATCH_CASES, PARSE_ERROR_CASES, TOPIC_PARSE_CASES, oracle_match, oracle_parse

from event_engine.capi import (
    Topic,
    TopicMatchResult,
    TopicPartAny,
    TopicPartExact,
    TopicPartPattern,
    TopicPartRange,
    TopicType,
    get_internal_map,
    get_internal_topic,
)
from event_engine.capi.c_topic import TopicTestToolkit


def _part_spec(part) -> tuple:
    """Map a parsed TopicPart instance back to an oracle part spec."""
    if isinstance(part, TopicPartExact):
        return ("exact", part.part)
    if isinstance(part, TopicPartAny):
        return ("any", part.name)
    if isinstance(part, TopicPartRange):
        return ("range", list(part.options()))
    if isinstance(part, TopicPartPattern):
        return ("pattern", part.pattern)
    raise AssertionError(f"unknown part type {type(part)}")


class TestTopicParsingContract(unittest.TestCase):
    """Contract: parsing follows c_topic_parse; verified against the oracle."""

    def test_00_parse_corpus_matches_oracle(self) -> None:
        """Every corpus topic parses to exactly the oracle's part specs."""
        for topic_str, expected in TOPIC_PARSE_CASES:
            with self.subTest(topic=topic_str):
                self.assertEqual(oracle_parse(topic_str), expected)
                topic = Topic(topic_str)
                actual = [_part_spec(p) for p in topic]
                self.assertEqual(actual, expected)
                self.assertEqual(len(topic), len(expected))
                self.assertEqual(len(list(topic)), len(expected))

    def test_01_parse_error_corpus_raises(self) -> None:
        """Unclosed patterns raise during construction."""
        for topic_str in PARSE_ERROR_CASES:
            with self.subTest(topic=topic_str):
                with self.assertRaises(Exception):  # MemoryError/RuntimeError
                    Topic(topic_str)

    def test_02_part_chain_linked(self) -> None:
        """Parts yielded by iteration form a linked chain via next()."""
        topic = Topic("a.+b.(x|y)")
        parts = list(topic)
        self.assertEqual(len(parts), 3)
        # next() follows the C linked list — parts[1] is TopicPartAny
        n2 = parts[0].next()
        self.assertIsInstance(n2, TopicPartAny)
        self.assertEqual(n2.name, "b")
        n3 = parts[1].next()
        self.assertIsInstance(n3, TopicPartRange)
        self.assertEqual(list(n3.options()), ["x", "y"])
        with self.assertRaises(StopIteration):
            parts[2].next()

    def test_03_part_ttype_enum(self) -> None:
        """Each part reports the correct TopicType."""
        topic = Topic("a.+b.(x|y)./z/")
        expected_types = [
            TopicType.TOPIC_PART_EXACT,
            TopicType.TOPIC_PART_ANY,
            TopicType.TOPIC_PART_RANGE,
            TopicType.TOPIC_PART_PATTERN,
        ]
        for part, expected in zip(topic, expected_types):
            with self.subTest(part=repr(part)):
                self.assertEqual(part.ttype, expected)

    def test_04_indexing(self) -> None:
        """__getitem__ supports positive, negative and out-of-range indices."""
        topic = Topic("a.b.c")
        self.assertEqual(topic[0].part, "a")
        self.assertEqual(topic[1].part, "b")
        self.assertEqual(topic[-1].part, "c")
        self.assertEqual(topic[-3].part, "a")
        with self.assertRaises(IndexError):
            topic[3]
        with self.assertRaises(IndexError):
            topic[-4]

    def test_05_constructed_parts(self) -> None:
        """Parts can be constructed directly with alloc=True."""
        exact = TopicPartExact("x", alloc=True)
        any_part = TopicPartAny("name", alloc=True)
        range_part = TopicPartRange(["a", "b", "c"], alloc=True)
        pattern = TopicPartPattern("[0-9]+", alloc=True)

        self.assertEqual(exact.part, "x")
        self.assertEqual(any_part.name, "name")
        self.assertEqual(list(range_part.options()), ["a", "b", "c"])
        self.assertEqual(len(range_part), 3)
        self.assertEqual(pattern.pattern, "[0-9]+")
        self.assertTrue(pattern.regex.match("123"))

        for part in (exact, any_part, range_part, pattern):
            self.assertTrue(part.owner)
            self.assertGreater(part.addr, 0)

    def test_06_repr(self) -> None:
        """repr of topics and parts carries the value."""
        self.assertIn("a.b.c", repr(Topic("a.b.c")))
        self.assertIn("x", repr(TopicPartExact("x", alloc=True)))
        self.assertIn("name", repr(TopicPartAny("name", alloc=True)))
        r = repr(TopicPartRange(["a", "b"], alloc=True))
        self.assertIn("a", r)
        self.assertIn("b", r)
        self.assertIn("z", repr(TopicPartPattern("z", alloc=True)))


class TestTopicPropertiesContract(unittest.TestCase):
    """Contract: value / is_exact / hash / eq / bool / str."""

    def test_00_value_roundtrip(self) -> None:
        """value returns the original literal."""
        for topic_str, _ in TOPIC_PARSE_CASES:
            with self.subTest(topic=topic_str):
                self.assertEqual(Topic(topic_str).value, topic_str)

    def test_01_is_exact_flag(self) -> None:
        """is_exact is True only for topics of pure exact parts."""
        self.assertTrue(Topic("a.b.c").is_exact)
        self.assertTrue(Topic("").is_exact)
        self.assertFalse(Topic("a.+b").is_exact)
        self.assertFalse(Topic("a.(x|y)").is_exact)
        self.assertFalse(Topic("a./re/").is_exact)
        self.assertFalse(Topic("{name}").is_exact)

    def test_02_hash_and_eq(self) -> None:
        """Equal literals hash equal; different literals differ."""
        self.assertEqual(hash(Topic("a.b")), hash(Topic("a.b")))
        self.assertEqual(Topic("a.b"), Topic("a.b"))
        self.assertNotEqual(Topic("a.b"), Topic("a.c"))
        self.assertEqual(str(Topic("a.b")), "a.b")

    def test_03_bool(self) -> None:
        """bool reflects part count."""
        self.assertTrue(Topic("a"))
        self.assertFalse(Topic(""))

    def test_04_empty_topic(self) -> None:
        """The empty topic has zero parts."""
        topic = Topic("")
        self.assertEqual(len(topic), 0)
        self.assertEqual(list(topic), [])
        self.assertTrue(topic.is_exact)

    def test_05_value_setter_valid(self) -> None:
        """Assigning a valid value re-parses the topic."""
        topic = Topic("a.b")
        topic.value = "x.+y"
        self.assertEqual(topic.value, "x.+y")
        self.assertFalse(topic.is_exact)
        self.assertEqual(len(topic), 2)
        self.assertIsInstance(topic[1], TopicPartAny)

    def test_06_value_setter_invalid(self) -> None:
        """Assigning an unclosed pattern raises ValueError."""
        topic = Topic("a.b")
        with self.assertRaises(ValueError):
            topic.value = "./unclosed"


class TestTopicBuildersContract(unittest.TestCase):
    """Contract: join / from_parts / append / __add__ / __iadd__."""

    def test_00_join(self) -> None:
        """join builds an exact topic from literal strings."""
        topic = Topic.join(["a", "b", "c"])
        self.assertEqual(topic.value, "a.b.c")
        self.assertTrue(topic.is_exact)
        self.assertEqual(len(topic), 3)
        self.assertEqual([p.part for p in topic], ["a", "b", "c"])

    def test_01_from_parts(self) -> None:
        """from_parts rebuilds a topic from parts, keeping wildcards."""
        parts = [
            TopicPartExact("a", alloc=True),
            TopicPartAny("b", alloc=True),
            TopicPartRange(["x", "y"], alloc=True),
        ]
        topic = Topic.from_parts(parts)
        self.assertEqual(topic.value, "a.{b}.(x|y)")
        self.assertFalse(topic.is_exact)
        self.assertEqual(len(topic), 3)

    def test_02_append_exact_keeps_exact(self) -> None:
        """Appending an exact part keeps is_exact True."""
        topic = Topic("a.b")
        topic.append(TopicPartExact("c", alloc=True))
        self.assertEqual(topic.value, "a.b.c")
        self.assertTrue(topic.is_exact)
        self.assertEqual(len(topic), 3)

    def test_03_append_any_breaks_exact(self) -> None:
        """Appending a non-exact part flips is_exact and re-renders the value."""
        topic = Topic("a.b")
        result = topic.append(TopicPartAny("name", alloc=True))
        self.assertIs(result, topic)
        self.assertEqual(topic.value, "a.b.{name}")
        self.assertFalse(topic.is_exact)

    def test_04_add_returns_new_topic(self) -> None:
        """__add__ returns a new aggregated topic, leaving operands intact."""
        t1 = Topic("a.b")
        t2 = Topic("c.d")
        t3 = t1 + t2
        self.assertEqual(t3.value, "a.b.c.d")
        self.assertEqual(t1.value, "a.b")
        self.assertEqual(t2.value, "c.d")

        t4 = t1 + TopicPartExact("z", alloc=True)
        self.assertEqual(t4.value, "a.b.z")

    def test_05_iadd_in_place(self) -> None:
        """__iadd__ appends in place."""
        t1 = Topic("a")
        t2 = Topic("b")
        t1 += t2
        self.assertEqual(t1.value, "a.b")
        self.assertEqual(t2.value, "b")

    def test_06_add_type_error(self) -> None:
        """Adding unsupported types raises TypeError."""
        with self.assertRaises(TypeError):
            Topic("a") + "b"

    def test_07_append_owned_part_succeeds(self) -> None:
        """Appending an owner part transfers ownership and succeeds."""
        # A fully allocated empty exact part — the fast path takes it
        topic = Topic("a")
        part = TopicPartExact(alloc=True, part="z")
        result = topic.append(part)
        self.assertIs(result, topic)
        self.assertEqual(topic.value, "a.z")

    def test_08_update_literal(self) -> None:
        """update_literal regenerates the internal literal from parts."""
        topic = Topic("a.b")
        part = TopicPartExact("c", alloc=True)
        topic.append(part)
        topic.update_literal()
        self.assertEqual(topic.value, "a.b.c")


class TestTopicMatchContract(unittest.TestCase):
    """Contract: match follows c_topic_match; verified against the oracle."""

    def test_00_match_corpus_matches_oracle(self) -> None:
        """Every corpus match agrees with the oracle."""
        for a_str, b_str, expected in MATCH_CASES:
            with self.subTest(a=a_str, b=b_str):
                oracle_nodes = oracle_match(a_str, b_str)
                oracle_matched = all(n["matched"] for n in oracle_nodes)
                self.assertEqual(oracle_matched, expected)

                result = Topic(a_str).match(Topic(b_str))
                self.assertEqual(bool(result), expected)
                self.assertEqual(result.matched, expected)

                # Node count must match the oracle (fail-fast semantics)
                self.assertEqual(len(result), len(oracle_nodes))

                # Per-node matched flags and literals must match the oracle
                actual = [(n["matched"], n["literal"]) for n in result]
                oracle = [(n["matched"], n["literal"]) for n in oracle_nodes]
                self.assertEqual(actual, oracle)

    def test_01_short_circuit_identical(self) -> None:
        """Identical topics yield a single node whose literal is the full topic."""
        topic = Topic("a.b.c")
        result = topic.match(Topic("a.b.c"))
        self.assertTrue(result.matched)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["literal"], "a.b.c")

        # Same object also short-circuits
        self.assertEqual(len(topic.match(topic)), 1)

    def test_02_wildcard_captures_literal(self) -> None:
        """An any part captures the exact literal it matched."""
        result = Topic("base.+value").match(Topic("base.test"))
        nodes = list(result)
        self.assertEqual(nodes[1]["literal"], "test")

    def test_03_any_vs_any_fails(self) -> None:
        """Two wildcard parts never match (neither side is exact)."""
        result = Topic("a.+x").match(Topic("a.+y"))
        self.assertFalse(result)
        self.assertEqual(len(result), 2)
        self.assertFalse(result[1]["matched"])
        self.assertIsNone(result[1]["literal"])

    def test_04_length_mismatch_residual_node(self) -> None:
        """A length mismatch appends a trailing failed node with the residual part."""
        result = Topic("a.b").match(Topic("a.b.c"))
        self.assertFalse(result)
        self.assertEqual(len(result), 3)
        self.assertTrue(result[0]["matched"])
        self.assertTrue(result[1]["matched"])
        self.assertFalse(result[2]["matched"])
        self.assertIsNone(result[2]["part_a"])
        self.assertIsInstance(result[2]["part_b"], TopicPartExact)
        self.assertEqual(result[2]["part_b"].part, "c")

    def test_05_fail_fast_node_count(self) -> None:
        """Matching stops at the first failing part (node count == failure position)."""
        result = Topic("x.b").match(Topic("a.b"))
        self.assertFalse(result)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["matched"])

        result = Topic("a.x").match(Topic("a.y"))
        self.assertFalse(result)
        self.assertEqual(len(result), 2)

    def test_06_pattern_unanchored(self) -> None:
        """Pattern parts use unanchored (POSIX regexec) semantics."""
        self.assertTrue(Topic("a./[0-9]{6}/.b").match(Topic.join(["a", "pre600010", "b"])))
        self.assertFalse(Topic("a./^x$/.b").match(Topic.join(["a", "xy", "b"])))

    def test_07_result_container(self) -> None:
        """MatchResult supports bool/len/getitem/iter/length/matched/to_dict."""
        result = Topic("a.+x").match(Topic("a.test"))
        self.assertEqual(result.length, 2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result.matched, True)
        self.assertEqual(result[0]["literal"], "a")
        self.assertEqual(result[-1]["literal"], "test")

        d = result.to_dict()
        self.assertEqual(list(d.keys()), ["a", "test"])
        self.assertIsInstance(d["a"], TopicPartExact)
        self.assertEqual(d["a"].part, "a")
        self.assertEqual(d["test"].part, "test")

        with self.assertRaises(IndexError):
            result[2]

    def test_08_to_dict_short_circuit(self) -> None:
        """to_dict on a short-circuited match maps the full literal to the first part."""
        result = Topic("a.b").match(Topic("a.b"))
        d = result.to_dict()
        self.assertEqual(list(d.keys()), ["a.b"])
        self.assertIsInstance(d["a.b"], TopicPartExact)


class TestTopicFormatMapContract(unittest.TestCase):
    """Contract: format_map / format / __call__ with strict & internalized."""

    def test_00_strict_all_keys(self) -> None:
        """strict=True with all keys present yields an exact topic."""
        template = Topic("realtime.{ticker}.{dtype}")
        formatted = template.format_map({"ticker": "600010.SH", "dtype": "TickData"}, strict=True)
        self.assertEqual(formatted.value, "realtime.600010.SH.TickData")
        self.assertTrue(formatted.is_exact)
        self.assertTrue(formatted.match(Topic("realtime.600010.SH.TickData")))
        self.assertEqual(len(formatted), 3)

    def test_01_strict_missing_key_raises(self) -> None:
        """strict=True with a missing key raises KeyError with the key name."""
        template = Topic("realtime.{ticker}.{dtype}")
        with self.assertRaises(KeyError) as ctx:
            template.format_map({"ticker": "600010.SH"}, strict=True)
        self.assertEqual(str(ctx.exception), "'dtype'")

    def test_02_lenient_keeps_wildcard(self) -> None:
        """strict=False keeps unfilled wildcards as any parts."""
        template = Topic("realtime.{ticker}.{dtype}")
        formatted = template.format_map({"ticker": "600010.SH"}, strict=False)
        self.assertEqual(formatted.value, "realtime.600010.SH.{dtype}")
        self.assertFalse(formatted.is_exact)
        self.assertIsInstance(formatted[2], TopicPartAny)
        self.assertEqual(formatted[2].name, "dtype")

    def test_03_lenient_no_keys(self) -> None:
        """strict=False with no mapping keys keeps every wildcard."""
        template = Topic("realtime.{ticker}.{dtype}")
        formatted = template.format_map({}, strict=False)
        self.assertEqual(formatted.value, "realtime.{ticker}.{dtype}")
        self.assertFalse(formatted.is_exact)
        self.assertIsInstance(formatted[1], TopicPartAny)

    def test_04_format_and_call_default_lenient(self) -> None:
        """format() and __call__ default to strict=False."""
        template = Topic("realtime.{ticker}.{dtype}")
        self.assertEqual(template.format(ticker="600010.SH").value, "realtime.600010.SH.{dtype}")
        self.assertEqual(template(ticker="600010.SH").value, "realtime.600010.SH.{dtype}")

    def test_05_internalized_owner_flag(self) -> None:
        """internalized=True yields a non-owner topic; internalized=False an owner."""
        template = Topic("realtime.{ticker}")
        self.assertFalse(template.format_map({"ticker": "600010.SH"}, internalized=True).owner)
        self.assertTrue(template.format_map({"ticker": "600010.SH"}, internalized=False).owner)

    def test_06_unsupported_part_raises(self) -> None:
        """format_map on a topic with range/pattern parts raises ValueError."""
        with self.assertRaises(ValueError):
            Topic("(a|b)").format_map({})
        with self.assertRaises(ValueError):
            Topic("./re/").format_map({})

    def test_07_mapped_value_with_separator(self) -> None:
        """A mapped value containing '.' becomes a single exact part."""
        formatted = Topic("{ticker}").format_map({"ticker": "600010.SH"})
        self.assertEqual(len(formatted), 1)
        self.assertEqual(formatted[0].part, "600010.SH")


class TestTopicInternalMapContract(unittest.TestCase):
    """Contract: topics are internalized; the global map can be queried."""

    def test_00_construction_internalizes(self) -> None:
        """Constructing a topic registers its literal in the internal map."""
        key = "internal.map.contract"
        Topic(key)
        topic = get_internal_topic(key)
        self.assertIsNotNone(topic)
        self.assertEqual(topic.value, key)
        self.assertTrue(TopicTestToolkit.get_internal_map_has(key))

    def test_01_get_internal_map_dict(self) -> None:
        """get_internal_map returns a dict keyed by literal."""
        Topic("internal.map.dict")
        mapping = get_internal_map()
        self.assertIn("internal.map.dict", mapping)
        self.assertEqual(mapping["internal.map.dict"].value, "internal.map.dict")

    def test_02_missing_key_returns_none(self) -> None:
        """get_internal_topic returns None for unknown literals."""
        self.assertIsNone(get_internal_topic("no.such.topic.registered"))

    def test_03_map_size_monotonic(self) -> None:
        """The internal map grows as new topics are constructed."""
        before = TopicTestToolkit.get_internal_map_size()
        Topic(f"internal.map.growth.{before}")
        after = TopicTestToolkit.get_internal_map_size()
        self.assertGreaterEqual(after, before + 1)


class TestTopicToolkitState(unittest.TestCase):
    """Contract: C-level state relayed by TopicTestToolkit matches public API."""

    def test_00_topic_state_matches_public_api(self) -> None:
        """Toolkit n_parts/hash/is_exact/key agree with the public properties."""
        for topic_str in ["a.b.c", "a.+b.(x|y)./re/", ""]:
            with self.subTest(topic=topic_str):
                topic = Topic(topic_str)
                self.assertEqual(TopicTestToolkit.get_n_parts(topic), len(topic))
                # C hash is uint64_t; Python hash() casts unsigned→signed
                raw_hash = TopicTestToolkit.get_hash(topic)
                self.assertEqual(raw_hash & 0xFFFFFFFFFFFFFFFF, hash(topic) & 0xFFFFFFFFFFFFFFFF)
                self.assertEqual(TopicTestToolkit.get_is_exact(topic), topic.is_exact)
                self.assertEqual(TopicTestToolkit.get_key(topic), topic.value)

    def test_01_part_chain_len_matches_iteration(self) -> None:
        """Toolkit part-chain length agrees with list(topic)."""
        topic = Topic("a.b.c.d")
        parts = list(topic)
        self.assertEqual(TopicTestToolkit.get_part_chain_len(parts[0]), 4)
        self.assertEqual(TopicTestToolkit.get_part_chain_len(parts[2]), 2)

    def test_02_part_ttype_array_matches_iteration(self) -> None:
        """Toolkit per-index ttype agrees with iteration order."""
        topic = Topic("a.+b.(x|y)./re/")
        for i, part in enumerate(topic):
            self.assertEqual(TopicTestToolkit.get_part_ttype(topic, i), part.ttype)
        with self.assertRaises(IndexError):
            TopicTestToolkit.get_part_ttype(topic, 99)

    def test_03_range_internals(self) -> None:
        """Toolkit range options/count agree with options()."""
        topic = Topic("(alpha|beta|gamma)")
        part = topic[0]
        self.assertEqual(TopicTestToolkit.get_range_num_options(part), 3)
        self.assertEqual(TopicTestToolkit.get_range_options(part), ["alpha", "beta", "gamma"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
