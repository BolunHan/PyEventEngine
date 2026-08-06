"""Contract tests for the compile-time config view (event_engine.config_view).

CONFIG_VIEW exposes every overridable compile-time constant as an immutable
nested mappingproxy. These tests pin the default build's values and verify
the view's immutability.
"""

import unittest
from types import MappingProxyType

from event_engine import CONFIG_VIEW, get_include
from event_engine.base import c_allocator_protocol


class TestConfigViewStructure(unittest.TestCase):
    """Contract: CONFIG_VIEW is a nested, immutable mappingproxy tree."""

    def test_00_is_mappingproxy(self) -> None:
        """CONFIG_VIEW is a MappingProxyType with the three expected sections."""
        self.assertIsInstance(CONFIG_VIEW, MappingProxyType)
        self.assertEqual(set(CONFIG_VIEW.keys()), {"engine", "topic", "allocator"})
        for section in CONFIG_VIEW.values():
            self.assertIsInstance(section, MappingProxyType)

    def test_01_immutable(self) -> None:
        """Assignment at any nesting level raises TypeError."""
        with self.assertRaises(TypeError):
            CONFIG_VIEW["engine"] = {}
        with self.assertRaises(TypeError):
            CONFIG_VIEW["engine"]["DEFAULT_MQ_CAPACITY"] = 1

    def test_02_include_paths_exist(self) -> None:
        """get_include() returns existing directories."""
        for path in get_include():
            import os

            self.assertTrue(os.path.isdir(path), f"{path} does not exist")


class TestConfigViewEngine(unittest.TestCase):
    """Contract: engine compile-time defaults."""

    def test_00_default_capacity(self) -> None:
        """DEFAULT_MQ_CAPACITY is 0x0fff (4095)."""
        self.assertEqual(CONFIG_VIEW["engine"]["DEFAULT_MQ_CAPACITY"], 0x0FFF)

    def test_01_default_spin_limit(self) -> None:
        """DEFAULT_MQ_SPIN_LIMIT is 0xffff (65535)."""
        self.assertEqual(CONFIG_VIEW["engine"]["DEFAULT_MQ_SPIN_LIMIT"], 0xFFFF)

    def test_02_default_timeout(self) -> None:
        """DEFAULT_MQ_TIMEOUT_SECONDS is 1.0."""
        self.assertEqual(CONFIG_VIEW["engine"]["DEFAULT_MQ_TIMEOUT_SECONDS"], 1.0)


class TestConfigViewTopic(unittest.TestCase):
    """Contract: topic syntax compile-time defaults."""

    def test_00_delimiters(self) -> None:
        """The topic grammar constants match the documented defaults."""
        topic = CONFIG_VIEW["topic"]
        self.assertEqual(topic["DEFAULT_TOPIC_SEP"], ".")
        self.assertEqual(topic["DEFAULT_OPTION_SEP"], "|")
        self.assertEqual(topic["DEFAULT_RANGE_BRACKETS"], "()")
        self.assertEqual(topic["DEFAULT_WILDCARD_BRACKETS"], "{}")
        self.assertEqual(topic["DEFAULT_WILDCARD_MARKER"], "+")
        self.assertEqual(topic["DEFAULT_PATTERN_DELIM"], "/")


class TestConfigViewAllocator(unittest.TestCase):
    """Contract: allocator compile-time defaults."""

    def test_00_local_only(self) -> None:
        """EE_LOCAL_ONLY defaults to True (heap-only, thread-local engine)."""
        self.assertTrue(CONFIG_VIEW["allocator"]["EE_LOCAL_ONLY"])

    def test_01_matches_runtime_config(self) -> None:
        """The static view's EE_LOCAL_ONLY is consistent with the live allocator."""
        from event_engine.base.c_allocator_protocol import AllocatorTestToolkit

        if CONFIG_VIEW["allocator"]["EE_LOCAL_ONLY"]:
            self.assertFalse(AllocatorTestToolkit.is_shm_available())
        else:
            self.assertTrue(AllocatorTestToolkit.is_shm_available())


if __name__ == "__main__":
    unittest.main(verbosity=2)
