"""验证 CI runner 的 CPU 架构和必需模块。"""

from __future__ import annotations

import argparse
import importlib
import platform
from collections.abc import Sequence


MACHINE_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
}


def canonical_machine(machine: str) -> str:
    """把 GitHub runner 常见的架构名称归一化。"""

    normalized = machine.strip().lower()
    return MACHINE_ALIASES.get(normalized, normalized)


def verify_environment(expected_machine: str, imports: tuple[str, ...] = ()) -> None:
    """验证实际架构，并导入当前 job 要求的模块。"""

    actual = platform.machine()
    if canonical_machine(actual) != canonical_machine(expected_machine):
        raise RuntimeError(
            f"runner architecture mismatch: expected={expected_machine!r}, actual={actual!r}"
        )

    for module in imports:
        importlib.import_module(module)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-machine", required=True)
    parser.add_argument("--require-import", action="append", default=[])
    args = parser.parse_args(argv)

    verify_environment(args.expected_machine, tuple(args.require_import))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
