#!/usr/bin/env python3
"""
NT test runner — discovers and runs unittest suites from the project's tests/ tree.

The test tree is organized into three suites:
    tests/capi/     contract tests for the Cython (capi) layer
    tests/native/   contract tests for the pure-Python native layer
    tests/nt/       fallback mechanism / cross-target package tests

Usage:
    python tests/nt_main.py            # discover and run all suites
    python tests/nt_main.py -v         # verbose
    python tests/nt_main.py -q         # quiet
    python tests/nt_main.py -f         # failfast
    python tests/nt_main.py <topic>    # run tests matching a topic across suites
                                       # (e.g. `topic`, `engine`, `performance`)
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.join(PROJECT_ROOT, "tests")
SUITES = ("capi", "native", "nt")


def _discover_suite(loader: unittest.TestLoader, pattern: str) -> unittest.TestSuite:
    """Discover ``pattern`` in every suite directory under tests/."""
    suite = unittest.TestSuite()
    for sub in SUITES:
        sub_dir = os.path.join(TEST_DIR, sub)
        if os.path.isdir(sub_dir):
            suite.addTests(loader.discover(sub_dir, pattern=pattern, top_level_dir=TEST_DIR))
    return suite


def main():
    # Parse simple flags
    argv = sys.argv[1:]
    verbosity = 1
    failfast = False
    topics = []

    for arg in argv:
        if arg in ("-v", "--verbose"):
            verbosity = 2
        elif arg in ("-q", "--quiet"):
            verbosity = 0
        elif arg in ("-f", "--failfast"):
            failfast = True
        elif arg.startswith("-"):
            print(f"Unknown flag: {arg}")
            sys.exit(2)
        else:
            topics.append(arg)

    loader = unittest.TestLoader()

    if topics:
        suite = unittest.TestSuite()
        for topic in topics:
            # `capi_topic` / `topic` / `test_01_topic.py` all resolve to the
            # topic-related test module(s) in every suite directory.
            if topic.startswith("test_") and topic.endswith(".py"):
                base = topic[:-3]
            else:
                base = topic.removeprefix("test_")
                if base.endswith("_test"):
                    base = base[:-5]
            base = base.removeprefix("01_")
            for sub in SUITES:
                sub_dir = os.path.join(TEST_DIR, sub)
                if not os.path.isdir(sub_dir):
                    continue
                for name in sorted(os.listdir(sub_dir)):
                    if not name.startswith("test_") or not name.endswith(".py"):
                        continue
                    if name[:-3] == base or name[:-3].endswith(f"_{base}"):
                        discovered = loader.discover(sub_dir, pattern=name, top_level_dir=TEST_DIR)
                        suite.addTests(discovered)
    else:
        suite = _discover_suite(loader, pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=verbosity, failfast=failfast)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
