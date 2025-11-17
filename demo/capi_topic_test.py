import unittest
from event_engine.capi import (
    PyTopicPartExact,
    PyTopicPartAny,
    PyTopicPartRange,
    PyTopicPartPattern,
    PyTopic,
    PyTopicType
)


class TestTopicParsing(unittest.TestCase):

    def _assert_part_exact(self, part, expected: str):
        self.assertIsInstance(part, PyTopicPartExact)
        self.assertEqual(part.part, expected)

    def _assert_part_any(self, part, expected_name: str):
        self.assertIsInstance(part, PyTopicPartAny)
        self.assertEqual(part.name, expected_name)

    def _assert_part_range(self, part, expected_options):
        self.assertIsInstance(part, PyTopicPartRange)
        self.assertEqual(list(part.options()), expected_options)

    def _assert_part_pattern(self, part, expected_pattern: str):
        self.assertIsInstance(part, PyTopicPartPattern)
        self.assertEqual(part.pattern, expected_pattern)

    def test_basic_tokens(self):
        cases = [
            ("exact", [PyTopicPartExact]),
            ("+valid", [PyTopicPartAny]),
            ("(a|b)", [PyTopicPartRange]),
            ("./pat/.", [PyTopicPartPattern]),
        ]
        for topic_str, expected_types in cases:
            with self.subTest(topic=topic_str):
                t = PyTopic(topic_str)
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
                t = PyTopic(topic_str)
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
        t = PyTopic(r'pre.+')
        parts = list(t)
        self.assertEqual(len(parts), 2)
        self._assert_part_exact(parts[0], 'pre')
        self._assert_part_exact(parts[1], '+')  # NOT Any!

        # Case 2: standalone +
        t = PyTopic(r'+')
        self.assertEqual(len(t), 1)
        self._assert_part_exact(t[0], '+')

        # Case 3: + with name → valid ANY
        t = PyTopic(r'+abc')
        self.assertEqual(len(t), 1)
        self._assert_part_any(t[0], 'abc')

        # Case 4: pattern followed by lone +
        t = PyTopic(r'./pat/.+')
        parts = list(t)
        self.assertEqual(len(parts), 2)
        self._assert_part_pattern(parts[0], 'pat')
        self._assert_part_exact(parts[1], '+')
        self._assert_part_pattern(PyTopic(r'/^[0-9]{6}\.(SZ|SH)$/.abc.(user|guest|admin)')[0], "^[0-9]{6}\.(SZ|SH)$")
        self._assert_part_pattern(PyTopic(r'abc.(user|guest|admin)./^[0-9]{6}\.(SZ|SH)$/')[-1], "^[0-9]{6}\.(SZ|SH)$")

        # Case 5: + in middle with name
        t = PyTopic(r'a.+b.c')
        parts = list(t)
        self.assertEqual(len(parts), 3)
        self._assert_part_exact(parts[0], 'a')
        self._assert_part_any(parts[1], 'b')
        self._assert_part_exact(parts[2], 'c')

    def test_range_edge_cases(self):
        # Empty range "()" → should be EXACT
        t = PyTopic(r'pre.().post')
        parts = list(t)
        self.assertEqual(len(parts), 3)
        self._assert_part_exact(parts[0], 'pre')
        self._assert_part_exact(parts[1], '()')
        self._assert_part_exact(parts[2], 'post')

        # Single char range → valid
        t = PyTopic(r'(x)')
        self.assertEqual(len(t), 1)
        self._assert_part_range(t[0], ['x'])

        # No closing → EXACT
        t = PyTopic(r'(unclosed')
        self.assertEqual(len(t), 1)
        self._assert_part_exact(t[0], '(unclosed')

    def test_malformed_pattern(self):
        # Unclosed pattern → should raise
        with self.assertRaises(Exception):  # MemoryError or RuntimeError
            PyTopic(r'abc./unclosed')

        # Pattern at end without closing → error
        with self.assertRaises(Exception):
            PyTopic(r'./no_close')

    def test_special_characters(self):
        # Literal dot in exact
        t = PyTopic(r'file.v1')
        self.assertEqual(len(t), 2)
        self._assert_part_exact(t[0], 'file')
        self._assert_part_exact(t[1], 'v1')

        # Escaped dot preserved in pattern
        t = PyTopic(r'./a\.b/.')
        self._assert_part_pattern(t[0], r'a\.b')

    def test_unicode_support(self):
        t = PyTopic('用户.+操作')
        parts = list(t)
        self.assertEqual(len(parts), 2)
        self._assert_part_exact(parts[0], '用户')
        self._assert_part_any(parts[1], '操作')


class TestTopicMatching(unittest.TestCase):

    def test_exact_match(self):
        t1 = PyTopic('a.b.c')
        t2 = PyTopic('a.b.c')
        match = t1.match(t2)
        self.assertTrue(match)

    def test_wildcard_match(self):
        # Valid ANY matches any single token
        t1 = PyTopic('base.+value')
        t2 = PyTopic('base.test')
        match = t1.match(t2)
        self.assertTrue(match)

        # But lone '+' is EXACT, so must match literal '+'
        t1 = PyTopic('cmd.+')
        t2 = PyTopic('cmd.+')  # both have EXACT "+"
        match = t1.match(t2)
        self.assertTrue(match)

        t1 = PyTopic('cmd.+')
        t2 = PyTopic('cmd.x')  # t1 expects literal '+', t2 has 'x'
        match = t1.match(t2)
        self.assertFalse(match)

    def test_range_match(self):
        t1 = PyTopic('event.(user|admin).action')
        t2 = PyTopic('event.admin.action')
        self.assertTrue(t1.match(t2))

        t2 = PyTopic('event.guest.action')
        self.assertFalse(t1.match(t2))

    def test_pattern_match(self):
        t1 = PyTopic(r'log./[0-9]{6}/.+suffix')
        t2 = PyTopic.join(['log', '123456', 'extra.suffix'])
        self.assertTrue(t1.match(t2))

        t2 = PyTopic('log.123.extra.suffix')  # too short
        self.assertFalse(t1.match(t2))

    def test_real_world_case(self):
        template = PyTopic(r'abc.(user|guest|admin)./^[0-9]{6}\.(SZ|SH)$/.+suffix')
        valid = PyTopic.join(['abc', 'user', '600000.SZ', 'extra.suffix'])
        self.assertTrue(template.match(valid))

        invalid_range = PyTopic('abc.hacker.600000.SZ.extra.suffix')
        self.assertFalse(template.match(invalid_range))

        invalid_pattern = PyTopic('abc.user.123.SZ.extra.suffix')
        self.assertFalse(template.match(invalid_pattern))

    def test_length_mismatch(self):
        self.assertFalse(PyTopic('a.b').match(PyTopic('a.b.c')))
        self.assertFalse(PyTopic('a.b.c').match(PyTopic('a.b')))

    def test_match_result_introspection(self):
        t1 = PyTopic('a.+x')
        t2 = PyTopic('a.test')
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
        t1 = PyTopic('a.{b}.{c}.{d}.{e}')
        t2 = PyTopic('a.2.3.4.5')
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
        t1 = PyTopic('realtime.{ticker}.{dtype}')
        t2 = PyTopic('realtime.600010.SH.TransactionData')
        match = t1.match(t2)
        # This should not match because t1 has 3 parts but t2 has 4 parts
        self.assertFalse(match)
        
        # Corrected version with proper structure
        t1_corrected = PyTopic('realtime.{ticker}.{dtype}')
        t2_corrected = PyTopic('realtime.600010.TransactionData')
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


if __name__ == '__main__':
    unittest.main()
