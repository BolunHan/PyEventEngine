"""Contract tests for the pure-Python topic implementation (event_engine.native.topic).

The same oracle contract as the capi suite (``tests._common``) is applied to
``PyTopic`` and friends. This suite is what guarantees the native layer
parses, matches and formats topics identically to the Cython layer.
"""

import unittest

from tests._common import MATCH_CASES, PARSE_ERROR_CASES, TOPIC_PARSE_CASES, oracle_match, oracle_parse

from event_engine.native import (
    PyTopic,
    PyTopicMatchResult,
    PyTopicPartAny,
    PyTopicPartExact,
    PyTopicPartPattern,
    PyTopicPartRange,
    PyTopicType,
    clear_internal_map,
    get_internal_map,
    get_internal_topic,
)


def _part_spec(part) -> tuple:
    """Map a parsed part instance back to an oracle part spec."""
    if isinstance(part, PyTopicPartExact):
        return ("exact", part.part)
    if isinstance(part, PyTopicPartAny):
        return ("any", part.name)
    if isinstance(part, PyTopicPartRange):
        return ("range", list(part.options()))
    if isinstance(part, PyTopicPartPattern):
        return ("pattern", part.pattern)
    raise AssertionError(f"unknown part type {type(part)}")


class TestPyTopicParsingContract(unittest.TestCase):
    """Contract: parsing follows c_topic_parse; verified against the oracle."""

    def test_00_parse_corpus_matches_oracle(self) -> None:
        """Every corpus topic parses to exactly the oracle's part specs."""
        for topic_str, expected in TOPIC_PARSE_CASES:
            with self.subTest(topic=topic_str):
                self.assertEqual(oracle_parse(topic_str), expected)
                topic = PyTopic(topic_str)
                actual = [_part_spec(p) for p in topic]
                self.assertEqual(actual, expected)
                self.assertEqual(len(topic), len(expected))
                self.assertEqual(len(list(topic)), len(expected))

    def test_01_parse_error_corpus_raises(self) -> None:
        """Unclosed patterns raise during construction."""
        for topic_str in PARSE_ERROR_CASES:
            with self.subTest(topic=topic_str):
                with self.assertRaises(Exception):
                    PyTopic(topic_str)

    def test_02_part_chain_linked(self) -> None:
        """Parts yielded by iteration form a linked chain via next()."""
        topic = PyTopic("a.+b.(x|y)")
        parts = list(topic)
        self.assertEqual(len(parts), 3)
        n2 = parts[0].next()
        self.assertIsInstance(n2, PyTopicPartAny)
        self.assertEqual(n2.name, "b")
        n3 = parts[1].next()
        self.assertIsInstance(n3, PyTopicPartRange)
        self.assertEqual(list(n3.options()), ["x", "y"])
        with self.assertRaises(StopIteration):
            parts[2].next()

    def test_03_part_ttype_enum(self) -> None:
        """Each part reports the correct PyTopicType."""
        topic = PyTopic("a.+b.(x|y)./z/")
        expected_types = [
            PyTopicType.TOPIC_PART_EXACT,
            PyTopicType.TOPIC_PART_ANY,
            PyTopicType.TOPIC_PART_RANGE,
            PyTopicType.TOPIC_PART_PATTERN,
        ]
        for part, expected in zip(topic, expected_types):
            with self.subTest(part=repr(part)):
                self.assertEqual(part.ttype, expected)

    def test_04_indexing(self) -> None:
        """__getitem__ supports positive, negative and out-of-range indices."""
        topic = PyTopic("a.b.c")
        self.assertEqual(topic[0].part, "a")
        self.assertEqual(topic[1].part, "b")
        self.assertEqual(topic[-1].part, "c")
        with self.assertRaises(IndexError):
            topic[3]

    def test_05_constructed_parts(self) -> None:
        """Parts can be constructed directly with alloc=True."""
        exact = PyTopicPartExact("x", alloc=True)
        any_part = PyTopicPartAny("name", alloc=True)
        range_part = PyTopicPartRange(["a", "b", "c"], alloc=True)
        pattern = PyTopicPartPattern("[0-9]+", alloc=True)

        self.assertEqual(exact.part, "x")
        self.assertEqual(any_part.name, "name")
        self.assertEqual(list(range_part.options()), ["a", "b", "c"])
        self.assertEqual(len(range_part), 3)
        self.assertEqual(pattern.pattern, "[0-9]+")
        self.assertTrue(pattern.regex.match("123"))

    def test_06_repr(self) -> None:
        """repr of topics and parts carries the value."""
        self.assertIn("a.b.c", repr(PyTopic("a.b.c")))
        self.assertIn("x", repr(PyTopicPartExact("x", alloc=True)))
        self.assertIn("name", repr(PyTopicPartAny("name", alloc=True)))
        r = repr(PyTopicPartRange(["a", "b"], alloc=True))
        self.assertIn("a", r)
        self.assertIn("b", r)
        self.assertIn("z", repr(PyTopicPartPattern("z", alloc=True)))


class TestPyTopicPropertiesContract(unittest.TestCase):
    """Contract: value / is_exact / hash / eq / bool / str."""

    def test_00_value_roundtrip(self) -> None:
        """value returns the original literal."""
        for topic_str, _ in TOPIC_PARSE_CASES:
            with self.subTest(topic=topic_str):
                self.assertEqual(PyTopic(topic_str).value, topic_str)

    def test_01_is_exact_flag(self) -> None:
        """is_exact is True only for topics of pure exact parts."""
        self.assertTrue(PyTopic("a.b.c").is_exact)
        self.assertTrue(PyTopic("").is_exact)
        self.assertFalse(PyTopic("a.+b").is_exact)
        self.assertFalse(PyTopic("a.(x|y)").is_exact)
        self.assertFalse(PyTopic("a./re/").is_exact)
        self.assertFalse(PyTopic("{name}").is_exact)

    def test_02_hash_and_eq(self) -> None:
        """Equal literals hash equal; different literals differ."""
        self.assertEqual(hash(PyTopic("a.b")), hash(PyTopic("a.b")))
        self.assertEqual(PyTopic("a.b"), PyTopic("a.b"))
        self.assertNotEqual(PyTopic("a.b"), PyTopic("a.c"))
        self.assertEqual(str(PyTopic("a.b")), "a.b")

    def test_03_bool(self) -> None:
        """bool reflects part count."""
        self.assertTrue(PyTopic("a"))
        self.assertFalse(PyTopic(""))

    def test_04_empty_topic(self) -> None:
        """The empty topic has zero parts."""
        topic = PyTopic("")
        self.assertEqual(len(topic), 0)
        self.assertEqual(list(topic), [])
        self.assertTrue(topic.is_exact)

    def test_05_value_setter_valid(self) -> None:
        """Assigning a valid value re-parses the topic."""
        topic = PyTopic("a.b")
        topic.value = "x.+y"
        self.assertEqual(topic.value, "x.+y")
        self.assertFalse(topic.is_exact)
        self.assertEqual(len(topic), 2)
        self.assertIsInstance(topic[1], PyTopicPartAny)

    def test_06_value_setter_invalid(self) -> None:
        """Assigning an unclosed pattern raises ValueError."""
        topic = PyTopic("a.b")
        with self.assertRaises(ValueError):
            topic.value = "./unclosed"


class TestPyTopicBuildersContract(unittest.TestCase):
    """Contract: join / from_parts / append / __add__ / __iadd__."""

    def test_00_join(self) -> None:
        """join builds an exact topic from literal strings."""
        topic = PyTopic.join(["a", "b", "c"])
        self.assertEqual(topic.value, "a.b.c")
        self.assertTrue(topic.is_exact)
        self.assertEqual(len(topic), 3)

    def test_01_from_parts(self) -> None:
        """from_parts rebuilds a topic from parts, keeping wildcards."""
        parts = [
            PyTopicPartExact("a", alloc=True),
            PyTopicPartAny("b", alloc=True),
            PyTopicPartRange(["x", "y"], alloc=True),
        ]
        topic = PyTopic.from_parts(parts)
        self.assertEqual(topic.value, "a.{b}.(x|y)")
        self.assertFalse(topic.is_exact)
        self.assertEqual(len(topic), 3)

    def test_02_append_exact_keeps_exact(self) -> None:
        """Appending an exact part keeps is_exact True."""
        topic = PyTopic("a.b")
        topic.append(PyTopicPartExact("c", alloc=True))
        self.assertEqual(topic.value, "a.b.c")
        self.assertTrue(topic.is_exact)

    def test_03_append_any_breaks_exact(self) -> None:
        """Appending a non-exact part flips is_exact and re-renders the value."""
        topic = PyTopic("a.b")
        result = topic.append(PyTopicPartAny("name", alloc=True))
        self.assertIs(result, topic)
        self.assertEqual(topic.value, "a.b.{name}")
        self.assertFalse(topic.is_exact)

    def test_04_add_returns_new_topic(self) -> None:
        """__add__ returns a new aggregated topic, leaving operands intact."""
        t1 = PyTopic("a.b")
        t2 = PyTopic("c.d")
        t3 = t1 + t2
        self.assertEqual(t3.value, "a.b.c.d")
        self.assertEqual(t1.value, "a.b")
        self.assertEqual(t2.value, "c.d")

        t4 = t1 + PyTopicPartExact("z", alloc=True)
        self.assertEqual(t4.value, "a.b.z")

    def test_05_iadd_in_place(self) -> None:
        """__iadd__ appends in place."""
        t1 = PyTopic("a")
        t2 = PyTopic("b")
        t1 += t2
        self.assertEqual(t1.value, "a.b")
        self.assertEqual(t2.value, "b")

    def test_06_add_type_error(self) -> None:
        """Adding unsupported types raises TypeError."""
        with self.assertRaises(TypeError):
            PyTopic("a") + "b"

    def test_07_update_literal(self) -> None:
        """update_literal regenerates the internal literal from parts."""
        topic = PyTopic("a.b")
        topic.append(PyTopicPartExact("c", alloc=True))
        topic.update_literal()
        self.assertEqual(topic.value, "a.b.c")


class TestPyTopicMatchContract(unittest.TestCase):
    """Contract: match follows c_topic_match; verified against the oracle."""

    def test_00_match_corpus_matches_oracle(self) -> None:
        """Every corpus match agrees with the oracle."""
        for a_str, b_str, expected in MATCH_CASES:
            with self.subTest(a=a_str, b=b_str):
                oracle_nodes = oracle_match(a_str, b_str)
                oracle_matched = all(n["matched"] for n in oracle_nodes)
                self.assertEqual(oracle_matched, expected)

                result = PyTopic(a_str).match(PyTopic(b_str))
                self.assertEqual(bool(result), expected)
                self.assertEqual(result.matched, expected)
                self.assertEqual(len(result), len(oracle_nodes))

                actual = [(n["matched"], n["literal"]) for n in result]
                oracle = [(n["matched"], n["literal"]) for n in oracle_nodes]
                self.assertEqual(actual, oracle)

    def test_01_short_circuit_identical(self) -> None:
        """Identical topics yield a single node whose literal is the full topic."""
        topic = PyTopic("a.b.c")
        result = topic.match(PyTopic("a.b.c"))
        self.assertTrue(result.matched)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["literal"], "a.b.c")
        self.assertEqual(len(topic.match(topic)), 1)

    def test_02_wildcard_captures_literal(self) -> None:
        """An any part captures the exact literal it matched."""
        result = PyTopic("base.+value").match(PyTopic("base.test"))
        self.assertEqual(result[1]["literal"], "test")

    def test_03_any_vs_any_fails(self) -> None:
        """Two wildcard parts never match (neither side is exact)."""
        result = PyTopic("a.+x").match(PyTopic("a.+y"))
        self.assertFalse(result)
        self.assertEqual(len(result), 2)

    def test_04_length_mismatch_residual_node(self) -> None:
        """A length mismatch appends a trailing failed node with the residual part."""
        result = PyTopic("a.b").match(PyTopic("a.b.c"))
        self.assertFalse(result)
        self.assertEqual(len(result), 3)
        self.assertTrue(result[0]["matched"])
        self.assertTrue(result[1]["matched"])
        self.assertFalse(result[2]["matched"])
        self.assertIsNone(result[2]["part_a"])
        self.assertIsInstance(result[2]["part_b"], PyTopicPartExact)
        self.assertEqual(result[2]["part_b"].part, "c")

    def test_05_fail_fast_node_count(self) -> None:
        """Matching stops at the first failing part (node count == failure position)."""
        result = PyTopic("x.b").match(PyTopic("a.b"))
        self.assertFalse(result)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["matched"])

        result = PyTopic("a.x").match(PyTopic("a.y"))
        self.assertFalse(result)
        self.assertEqual(len(result), 2)

    def test_06_pattern_unanchored(self) -> None:
        """Pattern parts use unanchored (POSIX regexec) semantics."""
        self.assertTrue(PyTopic("a./[0-9]{6}/.b").match(PyTopic.join(["a", "pre600010", "b"])))
        self.assertFalse(PyTopic("a./^x$/.b").match(PyTopic.join(["a", "xy", "b"])))

    def test_07_result_container(self) -> None:
        """MatchResult supports bool/len/getitem/iter/length/matched/to_dict."""
        result = PyTopic("a.+x").match(PyTopic("a.test"))
        self.assertIsInstance(result, PyTopicMatchResult)
        self.assertEqual(result.length, 2)
        self.assertEqual(result.matched, True)
        self.assertEqual(result[0]["literal"], "a")
        self.assertEqual(result[-1]["literal"], "test")

        d = result.to_dict()
        self.assertEqual(d, {"a": result[0]["part_b"], "test": result[1]["part_b"]})

        with self.assertRaises(IndexError):
            result[2]

    def test_08_to_dict_short_circuit(self) -> None:
        """to_dict on a short-circuited match maps the full literal to the first part."""
        result = PyTopic("a.b").match(PyTopic("a.b"))
        d = result.to_dict()
        self.assertEqual(list(d.keys()), ["a.b"])
        self.assertIsInstance(d["a.b"], PyTopicPartExact)


class TestPyTopicFormatMapContract(unittest.TestCase):
    """Contract: format_map / format / __call__ with strict & internalized."""

    def test_00_strict_all_keys(self) -> None:
        """strict=True with all keys present yields an exact topic."""
        template = PyTopic("realtime.{ticker}.{dtype}")
        formatted = template.format_map({"ticker": "600010.SH", "dtype": "TickData"}, strict=True)
        self.assertEqual(formatted.value, "realtime.600010.SH.TickData")
        self.assertTrue(formatted.is_exact)
        self.assertTrue(formatted.match(PyTopic("realtime.600010.SH.TickData")))
        self.assertEqual(len(formatted), 3)

    def test_01_strict_missing_key_raises(self) -> None:
        """strict=True with a missing key raises KeyError with the key name."""
        template = PyTopic("realtime.{ticker}.{dtype}")
        with self.assertRaises(KeyError) as ctx:
            template.format_map({"ticker": "600010.SH"}, strict=True)
        self.assertEqual(str(ctx.exception), "'dtype'")

    def test_02_lenient_keeps_wildcard(self) -> None:
        """strict=False keeps unfilled wildcards as any parts."""
        template = PyTopic("realtime.{ticker}.{dtype}")
        formatted = template.format_map({"ticker": "600010.SH"}, strict=False)
        self.assertEqual(formatted.value, "realtime.600010.SH.{dtype}")
        self.assertFalse(formatted.is_exact)
        self.assertIsInstance(formatted[2], PyTopicPartAny)
        self.assertEqual(formatted[2].name, "dtype")

    def test_03_lenient_no_keys(self) -> None:
        """strict=False with no mapping keys keeps every wildcard."""
        template = PyTopic("realtime.{ticker}.{dtype}")
        formatted = template.format_map({}, strict=False)
        self.assertEqual(formatted.value, "realtime.{ticker}.{dtype}")
        self.assertFalse(formatted.is_exact)

    def test_04_format_and_call_default_lenient(self) -> None:
        """format() and __call__ default to strict=False."""
        template = PyTopic("realtime.{ticker}.{dtype}")
        self.assertEqual(template.format(ticker="600010.SH").value, "realtime.600010.SH.{dtype}")
        self.assertEqual(template(ticker="600010.SH").value, "realtime.600010.SH.{dtype}")

    def test_05_unsupported_part_raises(self) -> None:
        """format_map on a topic with range/pattern parts raises ValueError."""
        with self.assertRaises(ValueError):
            PyTopic("(a|b)").format_map({})
        with self.assertRaises(ValueError):
            PyTopic("./re/").format_map({})

    def test_06_mapped_value_with_separator(self) -> None:
        """A mapped value containing '.' becomes a single exact part."""
        formatted = PyTopic("{ticker}").format_map({"ticker": "600010.SH"})
        self.assertEqual(len(formatted), 1)
        self.assertEqual(formatted[0].part, "600010.SH")


class TestPyTopicInternalMapContract(unittest.TestCase):
    """Contract: topics are internalized; the global map can be queried."""

    def tearDown(self) -> None:
        clear_internal_map()

    def test_00_construction_internalizes(self) -> None:
        """Constructing a topic registers its literal in the internal map."""
        key = "internal.map.contract"
        PyTopic(key)
        topic = get_internal_topic(key)
        self.assertIsNotNone(topic)
        self.assertEqual(topic.value, key)

    def test_01_get_internal_map_dict(self) -> None:
        """get_internal_map returns a dict keyed by literal."""
        PyTopic("internal.map.dict")
        mapping = get_internal_map()
        self.assertIn("internal.map.dict", mapping)
        self.assertEqual(mapping["internal.map.dict"].value, "internal.map.dict")

    def test_02_missing_key_returns_none(self) -> None:
        """get_internal_topic returns None for unknown literals."""
        self.assertIsNone(get_internal_topic("no.such.topic.registered"))

    def test_03_clear_internal_map(self) -> None:
        """clear_internal_map empties the map."""
        PyTopic("internal.map.clear")
        self.assertIsNotNone(get_internal_topic("internal.map.clear"))
        clear_internal_map()
        self.assertIsNone(get_internal_topic("internal.map.clear"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
