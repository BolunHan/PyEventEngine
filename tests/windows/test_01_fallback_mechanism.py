"""Fallback-mechanism tests for the Windows (NT) deployment target.

On Windows source checkouts without a Cython build, ``event_engine.capi``
cannot be imported and ``event_engine`` must transparently fall back to the
pure-Python ``event_engine.native`` implementation. These tests simulate the
unavailability of the capi package (and of the compiled ``c_engine`` module)
in isolated subprocesses and assert the fallback behavior.
"""

import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_BLOCK_CAPI_SCRIPT = r'''
import sys

class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "event_engine.capi" or name.startswith("event_engine.capi."):
            raise ImportError(f"blocked: {name}")
        return None

sys.meta_path.insert(0, _Blocker())

import event_engine
from event_engine import EventEngine, Topic

engine = EventEngine(capacity=8)
topic = Topic("fallback.check.topic")
received = []

def handler(a, topic=None):
    received.append((a, topic.value))

engine.register_handler(topic, handler)
engine.start()
engine.put(topic, 42)
import time as _t
deadline = _t.time() + 3
while not received and _t.time() < deadline:
    _t.sleep(0.01)
engine.stop()
assert received == [(42, "fallback.check.topic")], received
engine.clear()
print("FALLBACK_OK")
'''

_BLOCK_C_ENGINE_SCRIPT = r'''
import sys

class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "event_engine.capi.c_engine":
            raise ImportError(f"blocked: {name}")
        return None

sys.meta_path.insert(0, _Blocker())

import event_engine
import event_engine.capi as capi_mod

assert capi_mod.USING_FALLBACK is True, "expected USING_FALLBACK=True"

engine = capi_mod.EventEngine(capacity=8)
topic = capi_mod.Topic("fallback.engine.check")
received = []

def handler(a, topic=None):
    received.append((a, topic.value))

engine.register_handler(topic, handler)
engine.start()
engine.put(topic, 1)
import time as _t
deadline = _t.time() + 3
while not received and _t.time() < deadline:
    _t.sleep(0.01)
engine.stop()
assert received == [(1, "fallback.engine.check")], received
engine.clear()
print("C_ENGINE_FALLBACK_OK")
'''


def _run_python(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": REPO_ROOT},
    )


class TestFallbackMechanism(unittest.TestCase):
    """Contract: the package degrades gracefully when capi is unavailable."""

    @unittest.skipUnless(sys.platform == "win32", "subprocess blocker only works on Windows (no .so linkage)")
    def test_00_top_level_falls_back_to_native(self) -> None:
        """event_engine imports native when event_engine.capi is blocked."""
        result = _run_python(_BLOCK_CAPI_SCRIPT)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("FALLBACK_OK", result.stdout)

    @unittest.skipUnless(sys.platform == "win32", "subprocess blocker only works on Windows (no .so linkage)")
    def test_01_capi_falls_back_to_fallback_engine(self) -> None:
        """event_engine.capi uses fallback_engine when c_engine is blocked."""
        result = _run_python(_BLOCK_C_ENGINE_SCRIPT)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("C_ENGINE_FALLBACK_OK", result.stdout)

    def test_02_native_using_fallback_flag(self) -> None:
        """The native package reports USING_FALLBACK=True."""
        from event_engine import native as native_mod

        self.assertTrue(native_mod.USING_FALLBACK)

    def test_03_fallback_engine_module_exists(self) -> None:
        """The fallback engine module is importable."""
        from event_engine.capi import fallback_engine

        self.assertTrue(hasattr(fallback_engine, "EventEngine"))
        self.assertIsInstance(fallback_engine.EventEngine(capacity=8), object)


if __name__ == "__main__":
    unittest.main(verbosity=2)
