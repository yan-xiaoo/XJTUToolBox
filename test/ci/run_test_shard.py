"""Run one registered pull-request test domain."""

from __future__ import annotations

import argparse
import importlib
import os
import platform
import sys
import unittest
from collections.abc import Sequence

from test.ci.shards import get_shard


MACHINE_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
}


def canonical_machine(machine: str) -> str:
    """Normalize common GitHub runner architecture labels."""

    value = machine.strip().lower()
    return MACHINE_ALIASES.get(value, value)


def verify_machine(expected: str) -> None:
    """Fail if the current process does not run on the expected architecture."""

    actual = platform.machine()
    if canonical_machine(actual) != canonical_machine(expected):
        raise RuntimeError(
            f"runner architecture mismatch: expected={expected!r}, actual={actual!r}"
        )


def verify_imports(imports: Sequence[str]) -> None:
    """Import required runtime modules and preserve import failures."""

    for module in imports:
        importlib.import_module(module)


def build_suite(domain_id: str) -> unittest.TestSuite:
    """Build a suite from exactly the modules declared for ``domain_id``."""

    shard = get_shard(domain_id)
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(
        loader.loadTestsFromName(module) for module in shard.modules
    )
    if suite.countTestCases() == 0:
        raise ValueError(f"test domain is empty: {domain_id}")
    return suite


def finish_result(
    result: unittest.TestResult, *, hard_exit_on_success: bool
) -> int:
    """Return the result, optionally bypassing a known-bad Qt teardown."""

    if not result.wasSuccessful():
        return 1
    if hard_exit_on_success:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--expected-machine")
    parser.add_argument("--require-import", action="append", default=[])
    parser.add_argument(
        "--hard-exit-on-success",
        action="store_true",
        help="flush logs and skip interpreter teardown after a successful suite",
    )
    args = parser.parse_args(argv)

    if args.expected_machine:
        verify_machine(args.expected_machine)
    verify_imports(args.require_import)
    shard = get_shard(args.domain)
    print(f"Domain: {shard.id} ({shard.name})", flush=True)
    print("Modules: " + ", ".join(shard.modules), flush=True)
    print(
        "Command: python -m unittest -v " + " ".join(shard.modules),
        flush=True,
    )
    result = unittest.TextTestRunner(verbosity=2).run(build_suite(args.domain))
    return finish_result(
        result,
        hard_exit_on_success=args.hard_exit_on_success,
    )


if __name__ == "__main__":
    raise SystemExit(main())
