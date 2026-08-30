"""Run every product test module marked for historical regression coverage."""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from collections.abc import Sequence

from test.ci.shards import regression_modules


def build_suite(modules: Sequence[str] | None = None) -> unittest.TestSuite:
    """Build a suite from the AST-derived regression module inventory."""

    if modules is None:
        modules = regression_modules()
    if not modules:
        raise ValueError("no regression test modules are marked")
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(
        loader.loadTestsFromName(module) for module in modules
    )
    if suite.countTestCases() == 0:
        raise ValueError("regression test inventory contains no test cases")
    return suite


def finish_result(
    result: unittest.TestResult, *, hard_exit_on_success: bool
) -> int:
    """Return the result, optionally bypassing problematic Qt teardown."""

    if not result.wasSuccessful():
        return 1
    if hard_exit_on_success:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hard-exit-on-success",
        action="store_true",
        help="flush logs and skip interpreter teardown after a successful suite",
    )
    args = parser.parse_args(argv)
    modules = regression_modules()
    print("Regression modules: " + ", ".join(modules), flush=True)
    print(
        "Command: python -m unittest -v " + " ".join(modules),
        flush=True,
    )
    result = unittest.TextTestRunner(verbosity=2).run(build_suite(modules))
    return finish_result(result, hard_exit_on_success=args.hard_exit_on_success)


if __name__ == "__main__":
    raise SystemExit(main())
