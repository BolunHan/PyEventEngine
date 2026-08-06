"""Contract tests for the allocator protocol (event_engine.base.c_allocator_protocol).

Verifies the module-level allocator singletons, the runtime config accessor,
and the EEConfigContext activation round-trip. Internal C state is relayed
through the ``AllocatorTestToolkit`` test toolkit in
``c_allocator_protocol.pyx``.
"""

import unittest

from event_engine.base import c_allocator_protocol as alloc
from event_engine.base.c_allocator_protocol import (
    EE_FREELIST,
    EE_LOCKED,
    EE_LOCKFREE,
    EE_SHARED,
    RUNTIME_ALLOCATOR_CONFIG,
    AllocatorTestToolkit,
)


class TestRuntimeConfig(unittest.TestCase):
    """Contract: RUNTIME_ALLOCATOR_CONFIG mirrors the live EE_CFG_* globals."""

    def test_00_initial_values(self) -> None:
        """Defaults: unlocked, local (no shm), freelist enabled."""
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_SHARED)
        self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_FREELIST)

    def test_01_toolkit_agrees_with_runtime_config(self) -> None:
        """Toolkit relays the same live values as the runtime accessor."""
        self.assertEqual(AllocatorTestToolkit.get_cfg_locked(), RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        self.assertEqual(AllocatorTestToolkit.get_cfg_shared(), RUNTIME_ALLOCATOR_CONFIG.EE_CFG_SHARED)
        self.assertEqual(AllocatorTestToolkit.get_cfg_freelist(), RUNTIME_ALLOCATOR_CONFIG.EE_CFG_FREELIST)


class TestAllocatorSingletons(unittest.TestCase):
    """Contract: the allocator protocols are configured as documented."""

    def test_00_default_allocator_config(self) -> None:
        """EE_DEFAULT_ALLOCATOR follows the live EE_CFG_* flags and has a heap."""
        cfg = AllocatorTestToolkit.get_default_allocator_config()
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["with_lock"], RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        self.assertEqual(cfg["with_shm"], RUNTIME_ALLOCATOR_CONFIG.EE_CFG_SHARED)
        self.assertEqual(cfg["with_freelist"], RUNTIME_ALLOCATOR_CONFIG.EE_CFG_FREELIST)
        self.assertTrue(cfg["has_heap"])

    def test_01_heap_allocator_config(self) -> None:
        """EE_HEAP_ALLOCATOR is locked, freelist-backed and heap-only."""
        cfg = AllocatorTestToolkit.get_heap_allocator_config()
        self.assertIsNotNone(cfg)
        self.assertTrue(cfg["with_lock"])
        self.assertTrue(cfg["with_freelist"])
        self.assertFalse(cfg["with_shm"])
        self.assertTrue(cfg["has_heap"])
        self.assertFalse(cfg["has_shm"])

    def test_02_local_only_build_has_no_shm(self) -> None:
        """EE_LOCAL_ONLY builds (default) expose no shared-memory allocator."""
        self.assertFalse(AllocatorTestToolkit.is_shm_available())

    def test_03_config_context_objects_exist(self) -> None:
        """The named EEConfigContext instances are importable and activatable."""
        for ctx in (EE_SHARED, EE_LOCKED, EE_LOCKFREE, EE_FREELIST):
            with self.subTest(ctx=repr(ctx)):
                self.assertIsInstance(ctx, alloc.EEConfigContext)


class TestEEConfigContext(unittest.TestCase):
    """Contract: EEConfigContext activation round-trips the EE_CFG_* globals."""

    def tearDown(self) -> None:
        # Ensure globals are restored regardless of assertion outcomes
        AllocatorTestToolkit.deactivate_context(EE_LOCKED)
        AllocatorTestToolkit.deactivate_context(EE_SHARED)
        AllocatorTestToolkit.deactivate_context(EE_LOCKFREE)
        AllocatorTestToolkit.deactivate_context(EE_FREELIST)

    def test_00_activate_deactivate_locked(self) -> None:
        """EE_LOCKED flips EE_CFG_LOCKED on and restores it afterwards."""
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        AllocatorTestToolkit.activate_context(EE_LOCKED)
        try:
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
            self.assertTrue(AllocatorTestToolkit.get_cfg_locked())
        finally:
            AllocatorTestToolkit.deactivate_context(EE_LOCKED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)

    def test_01_lockfree_sets_locked_false(self) -> None:
        """EE_LOCKFREE forces locked=False."""
        AllocatorTestToolkit.activate_context(EE_LOCKFREE)
        try:
            self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        finally:
            AllocatorTestToolkit.deactivate_context(EE_LOCKFREE)

    def test_02_shared_flips_shared_flag(self) -> None:
        """EE_SHARED flips EE_CFG_SHARED on and restores it afterwards."""
        AllocatorTestToolkit.activate_context(EE_SHARED)
        try:
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_SHARED)
        finally:
            AllocatorTestToolkit.deactivate_context(EE_SHARED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_SHARED)

    def test_03_freelist_roundtrip(self) -> None:
        """EE_FREELIST flips EE_CFG_FREELIST on and restores it."""
        self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_FREELIST)
        AllocatorTestToolkit.activate_context(EE_FREELIST)
        try:
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_FREELIST)
        finally:
            AllocatorTestToolkit.deactivate_context(EE_FREELIST)
        self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_FREELIST)

    def test_04_context_manager_protocol(self) -> None:
        """EEConfigContext supports the with-statement (__enter__/__exit__)."""
        with EE_LOCKED:
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)

    def test_05_nested_contexts_restore_originals(self) -> None:
        """Nested activation restores each layer's original values."""
        with EE_LOCKED:
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
            with EE_LOCKFREE:
                self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)

    def test_06_invert_operator(self) -> None:
        """~EE_LOCKED yields the inverted override."""
        inverted = ~EE_LOCKED
        self.assertFalse(AllocatorTestToolkit.get_cfg_locked())
        with inverted:
            self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)

    def test_07_merge_operator(self) -> None:
        """EE_LOCKED | EE_SHARED merges overrides."""
        merged = EE_LOCKED | EE_SHARED
        with merged:
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
            self.assertTrue(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_SHARED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_LOCKED)
        self.assertFalse(RUNTIME_ALLOCATOR_CONFIG.EE_CFG_SHARED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
