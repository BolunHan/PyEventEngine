#!/usr/bin/env python3
"""
NT test runner — discovers and runs unittest suites from the project's test/ directory.

Usage:
    python tests/nt_main.py            # discover and run all tests
    python tests/nt_main.py -v         # verbose
    python tests/nt_main.py -q         # quiet
    python tests/nt_main.py -f         # failfast
    python tests/nt_main.py <module>   # run a specific test module (e.g. capi_topic_test)
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.join(PROJECT_ROOT, "test")


def main():
    # Parse simple flags
    argv = sys.argv[1:]
    verbosity = 1
    failfast = False
    modules = []

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
            modules.append(arg)

    loader = unittest.TestLoader()

    if modules:
        suite = unittest.TestSuite()
        for mod in modules:
            if not mod.endswith("_test"):
                mod = f"{mod}_test"
            if not mod.endswith(".py"):
                mod = f"{mod}.py"
            pattern = mod
            discovered = loader.discover(TEST_DIR, pattern=pattern)
            suite.addTests(discovered)
    else:
        suite = loader.discover(TEST_DIR, pattern="*_test.py")

    runner = unittest.TextTestRunner(verbosity=verbosity, failfast=failfast)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
