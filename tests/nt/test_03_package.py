"""Package integrity tests for the Windows (NT) deployment target.

Verifies that the shipped package exposes the full public surface, that the
compile-time config view agrees with the native layer's defaults (both
layers must default to the same queue/topic constants), and that logging
can be re-pointed through ``set_logger``.
"""

import logging
import re
import unittest

import event_engine
from event_engine import CONFIG_VIEW, __version__


class TestPackageSurface(unittest.TestCase):
    """Contract: the top-level package exposes the expected public API."""

    def test_00_version_format(self) -> None:
        """__version__ follows semver (e.g. 0.6.1, 0.6.1.post1)."""
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+(\.post\d+)?$")

    def test_01_capi_exports(self) -> None:
        """event_engine.capi exposes the full public API."""
        from event_engine import capi as capi_mod

        for name in (
            "TopicType", "TopicPart", "TopicPartExact", "TopicPartAny",
            "TopicPartRange", "TopicPartPattern", "TopicMatchResult", "Topic",
            "get_internal_topic", "get_internal_map",
            "MessagePayload", "EventHook", "EventHookEx",
            "Full", "Empty", "EventEngine", "EventEngineEx",
            "USING_FALLBACK", "set_logger",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(capi_mod, name), f"capi missing {name}")

    def test_02_native_exports(self) -> None:
        """event_engine.native exposes the full public API."""
        from event_engine import native as native_mod

        for name in (
            "PyTopicType", "PyTopicPart", "PyTopicPartExact", "PyTopicPartAny",
            "PyTopicPartRange", "PyTopicPartPattern", "PyTopicMatchResult", "PyTopic",
            "get_internal_topic", "get_internal_map", "init_allocator",
            "PyMessagePayload", "EventHook", "EventHookEx",
            "Full", "Empty", "EventEngine", "EventEngineEx",
            "USING_FALLBACK", "set_logger",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(native_mod, name), f"native missing {name}")

    def test_03_top_level_reexports(self) -> None:
        """The top-level package re-exports the engine and topic classes."""
        from event_engine import EventEngine, EventEngineEx, Full, Empty, Topic

        for name, cls in (
            ("EventEngine", EventEngine), ("EventEngineEx", EventEngineEx),
            ("Full", Full), ("Empty", Empty), ("Topic", Topic),
        ):
            self.assertIsNotNone(cls, f"{name} not re-exported")

    def test_04_include_paths_exist(self) -> None:
        """get_include() returns existing directories (wheel packaging)."""
        import os

        for path in event_engine.get_include():
            self.assertTrue(os.path.isdir(path), f"{path} does not exist")


class TestCrossLayerDefaults(unittest.TestCase):
    """Contract: native defaults agree with the compile-time config view."""

    def test_00_engine_defaults(self) -> None:
        """Native queue constants match CONFIG_VIEW['engine']."""
        from event_engine.native.engine import (
            DEFAULT_MQ_CAPACITY,
            DEFAULT_MQ_SPIN_LIMIT,
            DEFAULT_MQ_TIMEOUT_SECONDS,
        )

        engine_cfg = CONFIG_VIEW["engine"]
        self.assertEqual(DEFAULT_MQ_CAPACITY, engine_cfg["DEFAULT_MQ_CAPACITY"])
        self.assertEqual(DEFAULT_MQ_SPIN_LIMIT, engine_cfg["DEFAULT_MQ_SPIN_LIMIT"])
        self.assertEqual(DEFAULT_MQ_TIMEOUT_SECONDS, engine_cfg["DEFAULT_MQ_TIMEOUT_SECONDS"])

    def test_01_topic_defaults(self) -> None:
        """Native topic grammar constants match CONFIG_VIEW['topic']."""
        from event_engine.native.topic import (
            DEFAULT_OPTION_SEP,
            DEFAULT_PATTERN_DELIM,
            DEFAULT_RANGE_BRACKETS,
            DEFAULT_TOPIC_SEP,
            DEFAULT_WILDCARD_BRACKETS,
            DEFAULT_WILDCARD_MARKER,
        )

        topic_cfg = CONFIG_VIEW["topic"]
        self.assertEqual(DEFAULT_TOPIC_SEP, topic_cfg["DEFAULT_TOPIC_SEP"])
        self.assertEqual(DEFAULT_OPTION_SEP, topic_cfg["DEFAULT_OPTION_SEP"])
        self.assertEqual(DEFAULT_RANGE_BRACKETS, topic_cfg["DEFAULT_RANGE_BRACKETS"])
        self.assertEqual(DEFAULT_WILDCARD_BRACKETS, topic_cfg["DEFAULT_WILDCARD_BRACKETS"])
        self.assertEqual(DEFAULT_WILDCARD_MARKER, topic_cfg["DEFAULT_WILDCARD_MARKER"])
        self.assertEqual(DEFAULT_PATTERN_DELIM, topic_cfg["DEFAULT_PATTERN_DELIM"])

    def test_02_topic_type_enum_values(self) -> None:
        """Both TopicType enums use identical numeric values."""
        from event_engine.capi import TopicType as CapiTopicType
        from event_engine.native import PyTopicType as NativeTopicType

        for member in ("TOPIC_PART_EXACT", "TOPIC_PART_ANY", "TOPIC_PART_RANGE", "TOPIC_PART_PATTERN"):
            with self.subTest(member=member):
                self.assertEqual(
                    getattr(CapiTopicType, member).value,
                    getattr(NativeTopicType, member).value,
                )


class TestSetLogger(unittest.TestCase):
    """Contract: set_logger re-points the package loggers."""

    def test_00_capi_set_logger(self) -> None:
        """capi.set_logger wires the provided logger into the submodules."""
        from event_engine import capi as capi_mod

        handler = logging.Handler()
        logger = logging.getLogger("test.nt.custom")
        logger.addHandler(handler)
        try:
            capi_mod.set_logger(logger)
            self.assertIs(capi_mod.LOGGER, logger)
            self.assertEqual(capi_mod.c_topic.LOGGER.name, "test.nt.custom")
            self.assertEqual(capi_mod.c_event.LOGGER.name, "test.nt.custom.Event")
            self.assertEqual(capi_mod.c_engine.LOGGER.name, "test.nt.custom.Engine")
        finally:
            logger.removeHandler(handler)

    def test_01_native_set_logger(self) -> None:
        """native.set_logger wires the provided logger into the submodules."""
        from event_engine import native as native_mod

        logger = logging.getLogger("test.nt.native.custom")
        native_mod.set_logger(logger)
        self.assertIs(native_mod.LOGGER, logger)
        self.assertIs(native_mod.topic.LOGGER, logger)
        self.assertEqual(native_mod.event.LOGGER.name, "test.nt.native.custom.Event")
        self.assertEqual(native_mod.engine.LOGGER.name, "test.nt.native.custom.Engine")


if __name__ == "__main__":
    unittest.main(verbosity=2)
