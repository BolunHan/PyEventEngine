import unittest
from event_engine.capi import (
    TopicPartExact,
    TopicPartAny,
    TopicPartRange,
    TopicPartPattern,
    Topic,
    TopicType
)


class TestTopicParsing(unittest.TestCase):

    def _assert_part_exact(self, part, expected: str):
        self.assertIsInstance(part, TopicPartExact)
        self.assertEqual(part.part, expected)

    def _assert_part_any(self, part, expected_name: str):
        self.assertIsInstance(part, TopicPartAny)
        self.assertEqual(part.name, expected_name)

    def _assert_part_range(self, part, expected_options):
        self.assertIsInstance(part, TopicPartRange)
        self.assertEqual(list(part.options()), expected_options)

    def _assert_part_pattern(self, part, expected_pattern: str):
        self.assertIsInstance(part, TopicPartPattern)
        self.assertEqual(part.pattern, expected_pattern)

    def test_basic_tokens(self):
        cases = [
            ("exact", [TopicPartExact]),
            ("+valid", [TopicPartAny]),
            ("(a|b)", [TopicPartRange]),
            ("./pat/.", [TopicPartPattern]),
        ]
        for topic_str, expected_types in cases:
            with self.subTest(topic=topic_str):
                t = Topic(topic_str)
                self.assertEqual(len(t), 1)
                self.assertIsInstance(list(t)[0], expected_types[0])

    def test_complex_valid_topics(self):
        test_cases = [
            (
                r'base./user\.(test|prod)/.+suffix',
                [
                    ('exact', 'base'),
                    ('pattern', r'user\.(test|prod)'),
                    ('any', 'suffix')
                ]
            ),
            (
                r'./a\.b\.[0-9]/.(x|y|z).+end',
                [
                    ('pattern', r'a\.b\.[0-9]'),
                    ('range', ['x', 'y', 'z']),
                    ('any', 'end')
                ]
            ),
            (
                r'pre.(opt1|opt2)./complex\${1,3}\.txt/.+value',
                [
                    ('exact', 'pre'),
                    ('range', ['opt1', 'opt2']),
                    ('pattern', r'complex\${1,3}\.txt'),
                    ('any', 'value')
                ]
            ),
        ]

        for topic_str, expected_parts in test_cases:
            with self.subTest(topic=topic_str):
                t = Topic(topic_str)
                parts = list(t)
                self.assertEqual(len(parts), len(expected_parts))
                for part, (ptype, pvalue) in zip(parts, expected_parts):
                    if ptype == 'exact':
                        self._assert_part_exact(part, pvalue)
                    elif ptype == 'any':
                        self._assert_part_any(part, pvalue)
                    elif ptype == 'range':
                        self._assert_part_range(part, pvalue)
                    elif ptype == 'pattern':
                        self._assert_part_pattern(part, pvalue)

    def test_wildcard_edge_cases(self):
        """Test that lone '+' is treated as EXACT, not ANY."""
        # Case 1: trailing .+
        t = Topic(r'pre.+')
        parts = list(t)
        self.assertEqual(len(parts), 2)
        self._assert_part_exact(parts[0], 'pre')
        self._assert_part_exact(parts[1], '+')  # NOT Any!

        # Case 2: standalone +
        t = Topic(r'+')
        self.assertEqual(len(t), 1)
        self._assert_part_exact(t[0], '+')

        # Case 3: + with name → valid ANY
        t = Topic(r'+abc')
        self.assertEqual(len(t), 1)
        self._assert_part_any(t[0], 'abc')

        # Case 4: pattern followed by lone +
        t = Topic(r'./pat/.+')
        parts = list(t)
        self.assertEqual(len(parts), 2)
        self._assert_part_pattern(parts[0], 'pat')
        self._assert_part_exact(parts[1], '+')
        self._assert_part_pattern(Topic(r'/^[0-9]{6}\.(SZ|SH)$/.abc.(user|guest|admin)')[0], "^[0-9]{6}\.(SZ|SH)$")
        self._assert_part_pattern(Topic(r'abc.(user|guest|admin)./^[0-9]{6}\.(SZ|SH)$/')[-1], "^[0-9]{6}\.(SZ|SH)$")

        # Case 5: + in middle with name
        t = Topic(r'a.+b.c')
        parts = list(t)
        self.assertEqual(len(parts), 3)
        self._assert_part_exact(parts[0], 'a')
        self._assert_part_any(parts[1], 'b')
        self._assert_part_exact(parts[2], 'c')

    def test_range_edge_cases(self):
        # Empty range "()" → should be EXACT
        t = Topic(r'pre.().post')
        parts = list(t)
        self.assertEqual(len(parts), 3)
        self._assert_part_exact(parts[0], 'pre')
        self._assert_part_exact(parts[1], '()')
        self._assert_part_exact(parts[2], 'post')

        # Single char range → valid
        t = Topic(r'(x)')
        self.assertEqual(len(t), 1)
        self._assert_part_range(t[0], ['x'])

        # No closing → EXACT
        t = Topic(r'(unclosed')
        self.assertEqual(len(t), 1)
        self._assert_part_exact(t[0], '(unclosed')

    def test_malformed_pattern(self):
        # Unclosed pattern → should raise
        with self.assertRaises(Exception):  # MemoryError or RuntimeError
            Topic(r'abc./unclosed')

        # Pattern at end without closing → error
        with self.assertRaises(Exception):
            Topic(r'./no_close')

    def test_special_characters(self):
        # Literal dot in exact
        t = Topic(r'file.v1')
        self.assertEqual(len(t), 2)
        self._assert_part_exact(t[0], 'file')
        self._assert_part_exact(t[1], 'v1')

        # Escaped dot preserved in pattern
        t = Topic(r'./a\.b/.')
        self._assert_part_pattern(t[0], r'a\.b')

    def test_unicode_support(self):
        t = Topic('用户.+操作')
        parts = list(t)
        self.assertEqual(len(parts), 2)
        self._assert_part_exact(parts[0], '用户')
        self._assert_part_any(parts[1], '操作')


class TestTopicMatching(unittest.TestCase):

    def test_exact_match(self):
        t1 = Topic('a.b.c')
        t2 = Topic('a.b.c')
        match = t1.match(t2)
        self.assertTrue(match)

    def test_wildcard_match(self):
        # Valid ANY matches any single token
        t1 = Topic('base.+value')
        t2 = Topic('base.test')
        match = t1.match(t2)
        self.assertTrue(match)

        # But lone '+' is EXACT, so must match literal '+'
        t1 = Topic('cmd.+')
        t2 = Topic('cmd.+')  # both have EXACT "+"
        match = t1.match(t2)
        self.assertTrue(match)

        t1 = Topic('cmd.+')
        t2 = Topic('cmd.x')  # t1 expects literal '+', t2 has 'x'
        match = t1.match(t2)
        self.assertFalse(match)

    def test_range_match(self):
        t1 = Topic('event.(user|admin).action')
        t2 = Topic('event.admin.action')
        self.assertTrue(t1.match(t2))

        t2 = Topic('event.guest.action')
        self.assertFalse(t1.match(t2))

    def test_pattern_match(self):
        t1 = Topic(r'log./[0-9]{6}/.+suffix')
        t2 = Topic.join(['log', '123456', 'extra.suffix'])
        self.assertTrue(t1.match(t2))

        t2 = Topic('log.123.extra.suffix')  # too short
        self.assertFalse(t1.match(t2))

    def test_real_world_case(self):
        template = Topic(r'abc.(user|guest|admin)./^[0-9]{6}\.(SZ|SH)$/.+suffix')
        valid = Topic.join(['abc', 'user', '600000.SZ', 'extra.suffix'])
        self.assertTrue(template.match(valid))

        invalid_range = Topic('abc.hacker.600000.SZ.extra.suffix')
        self.assertFalse(template.match(invalid_range))

        invalid_pattern = Topic('abc.user.123.SZ.extra.suffix')
        self.assertFalse(template.match(invalid_pattern))

    def test_length_mismatch(self):
        self.assertFalse(Topic('a.b').match(Topic('a.b.c')))
        self.assertFalse(Topic('a.b.c').match(Topic('a.b')))

    def test_match_result_introspection(self):
        t1 = Topic('a.+x')
        t2 = Topic('a.test')
        match = t1.match(t2)
        self.assertTrue(match)
        res = list(match)
        self.assertEqual(len(res), 2)
        self.assertTrue(res[0]['matched'])
        self.assertTrue(res[1]['matched'])
        self.assertEqual(res[0]['literal'], 'a')
        self.assertEqual(res[1]['literal'], 'test')

    def test_multi_wildcard_match_results(self):
        """Test that all parts are returned in match results, not just first and last."""
        # Test case from the bug report: a.{b}.{c}.{d}.{e} vs a.2.3.4.5
        t1 = Topic('a.{b}.{c}.{d}.{e}')
        t2 = Topic('a.2.3.4.5')
        match = t1.match(t2)
        self.assertTrue(match)
        res = list(match)

        # Should have 5 match results (one for each part), not just 2
        self.assertEqual(len(res), 5, f"Expected 5 match results, got {len(res)}")

        # Verify each part matched
        for i, r in enumerate(res):
            self.assertTrue(r['matched'], f"Part {i} should be matched")

        # Verify literals
        self.assertEqual(res[0]['literal'], 'a')
        self.assertEqual(res[1]['literal'], '2')
        self.assertEqual(res[2]['literal'], '3')
        self.assertEqual(res[3]['literal'], '4')
        self.assertEqual(res[4]['literal'], '5')

    def test_realtime_ticker_dtype_match(self):
        """Test the specific example from the bug report."""
        t1 = Topic('realtime.{ticker}.{dtype}')
        t2 = Topic('realtime.600010.SH.TransactionData')
        match = t1.match(t2)
        # This should not match because t1 has 3 parts but t2 has 4 parts
        self.assertFalse(match)

        # Corrected version with proper structure
        t1_corrected = Topic('realtime.{ticker}.{dtype}')
        t2_corrected = Topic('realtime.600010.TransactionData')
        match = t1_corrected.match(t2_corrected)
        self.assertTrue(match)
        res = list(match)

        # Should have 3 match results
        self.assertEqual(len(res), 3, f"Expected 3 match results, got {len(res)}")

        # Verify each part matched
        self.assertTrue(res[0]['matched'])
        self.assertTrue(res[1]['matched'])
        self.assertTrue(res[2]['matched'])

        # Verify literals
        self.assertEqual(res[0]['literal'], 'realtime')
        self.assertEqual(res[1]['literal'], '600010')
        self.assertEqual(res[2]['literal'], 'TransactionData')


class TestTopicFormatMap(unittest.TestCase):
    """Test format_map with strict parameter."""

    def test_format_map_strict_true_all_keys_present(self):
        """Test format_map with strict=True when all keys are present."""
        template = Topic('realtime.{ticker}.{dtype}')
        formatted = template.format_map({'ticker': '600010.SH', 'dtype': 'TickData'}, strict=True)

        self.assertEqual(formatted.value, 'realtime.600010.SH.TickData')
        self.assertTrue(formatted.is_exact)
        self.assertEqual(len(formatted), 3)  # realtime, 600010.SH, TickData

    def test_format_map_strict_true_missing_key(self):
        """Test format_map with strict=True raises KeyError when key is missing."""
        template = Topic('realtime.{ticker}.{dtype}')

        with self.assertRaises(KeyError) as cm:
            template.format_map({'ticker': '600010.SH'}, strict=True)

        self.assertEqual(str(cm.exception), "'dtype'")

    def test_format_map_strict_false_all_keys_present(self):
        """Test format_map with strict=False when all keys are present."""
        template = Topic('realtime.{ticker}.{dtype}')
        formatted = template.format_map({'ticker': '600010.SH', 'dtype': 'TickData'}, strict=False)

        self.assertEqual(formatted.value, 'realtime.600010.SH.TickData')
        self.assertTrue(formatted.is_exact)
        self.assertEqual(len(formatted), 3)

    def test_format_map_strict_false_missing_key(self):
        """Test format_map with strict=False keeps wildcards when key is missing."""
        template = Topic('realtime.{ticker}.{dtype}')
        formatted = template.format_map({'ticker': '600010.SH'}, strict=False)

        # Should keep the {dtype} wildcard as-is
        self.assertEqual(formatted.value, 'realtime.600010.SH.{dtype}')
        self.assertFalse(formatted.is_exact)  # Not exact because it still has a wildcard
        self.assertEqual(len(formatted), 3)

        # Check parts
        parts = list(formatted)
        self.assertIsInstance(parts[0], TopicPartExact)
        self.assertEqual(parts[0].part, 'realtime')
        self.assertIsInstance(parts[1], TopicPartExact)
        self.assertEqual(parts[1].part, '600010.SH')
        self.assertIsInstance(parts[2], TopicPartAny)
        self.assertEqual(parts[2].name, 'dtype')
        self.assertTrue(formatted.match(Topic.join(["realtime", "600010.SH", "TickData"])))

    def test_format_map_strict_false_no_keys(self):
        """Test format_map with strict=False and no keys keeps all wildcards."""
        template = Topic('realtime.{ticker}.{dtype}')
        formatted = template.format_map({}, strict=False)

        # Should keep both wildcards as-is
        self.assertEqual(formatted.value, 'realtime.{ticker}.{dtype}')
        self.assertFalse(formatted.is_exact)
        self.assertEqual(len(formatted), 3)

        # Check parts
        parts = list(formatted)
        self.assertIsInstance(parts[0], TopicPartExact)
        self.assertEqual(parts[0].part, 'realtime')
        self.assertIsInstance(parts[1], TopicPartAny)
        self.assertEqual(parts[1].name, 'ticker')
        self.assertIsInstance(parts[2], TopicPartAny)
        self.assertEqual(parts[2].name, 'dtype')

    def test_format_map_strict_false_partial_replacement(self):
        """Test format_map with strict=False replaces some wildcards and keeps others."""
        template = Topic('{env}.{service}.{region}.{instance}')
        formatted = template.format_map({'env': 'prod', 'region': 'us-east-1'}, strict=False)

        # Should replace env and region, keep service and instance
        self.assertEqual(formatted.value, 'prod.{service}.us-east-1.{instance}')
        self.assertFalse(formatted.is_exact)
        self.assertEqual(len(formatted), 4)

        # Check parts
        parts = list(formatted)
        self.assertIsInstance(parts[0], TopicPartExact)
        self.assertEqual(parts[0].part, 'prod')
        self.assertIsInstance(parts[1], TopicPartAny)
        self.assertEqual(parts[1].name, 'service')
        self.assertIsInstance(parts[2], TopicPartExact)
        self.assertEqual(parts[2].part, 'us-east-1')
        self.assertIsInstance(parts[3], TopicPartAny)
        self.assertEqual(parts[3].name, 'instance')

    def test_format_default_strict_false(self):
        """Test that format() method defaults to strict=False."""
        template = Topic('realtime.{ticker}.{dtype}')
        formatted = template.format(ticker='600010.SH')

        # Should keep dtype wildcard
        self.assertEqual(formatted.value, 'realtime.600010.SH.{dtype}')
        self.assertFalse(formatted.is_exact)

    def test_call_syntax_strict_false(self):
        """Test that __call__ syntax defaults to strict=False."""
        template = Topic('realtime.{ticker}.{dtype}')
        formatted = template(ticker='600010.SH')

        # Should keep dtype wildcard
        self.assertEqual(formatted.value, 'realtime.600010.SH.{dtype}')
        self.assertFalse(formatted.is_exact)

    def test_format_map_internalized_parameter(self):
        """Test that internalized parameter works correctly."""
        template = Topic('realtime.{ticker}')

        # With internalized=True (default)
        formatted1 = template.format_map({'ticker': '600010.SH'}, internalized=True, strict=False)
        self.assertFalse(formatted1.owner)

        # With internalized=False
        formatted2 = template.format_map({'ticker': '600010.SH'}, internalized=False, strict=False)
        self.assertTrue(formatted2.owner)


if __name__ == '__main__':
    unittest.main()
