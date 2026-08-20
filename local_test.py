"""Run the pull-request product tests in the current local environment."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from test.ci.shards import SHARDS


REPOSITORY_ROOT = Path(__file__).resolve().parent
XDG_DIRECTORIES = {
    "XDG_STATE_HOME": "state",
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    "XDG_CACHE_HOME": "cache",
}


@dataclass(frozen=True)
class TestCommand:
    """A named child process in the local test sequence."""

    label: str
    argv: tuple[str, ...]


ProcessRunner = Callable[..., subprocess.CompletedProcess[bytes]]


def test_commands(python: str = sys.executable) -> tuple[TestCommand, ...]:
    """Build the contract command followed by every registered test domain."""

    commands = [
        TestCommand(
            "Test contract",
            (python, "-m", "unittest", "-v", "test.ci.test_pr_workflow"),
        )
    ]
    commands.extend(
        TestCommand(
            f"Domain: {shard.id} ({shard.name})",
            (python, "-m", "test.ci.run_test_shard", "--domain", shard.id),
        )
        for shard in SHARDS
    )
    return tuple(commands)


def isolated_environment(
    root: Path, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Copy an environment and add writable, isolated Qt/XDG test settings."""

    environment = dict(os.environ if base is None else base)
    environment.update(
        {
            "PYTHONUTF8": "1",
            "QT_QPA_PLATFORM": "offscreen",
            "QT_OPENGL": "software",
            "LIBGL_ALWAYS_SOFTWARE": "1",
        }
    )
    for variable, directory_name in XDG_DIRECTORIES.items():
        directory = root / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        environment[variable] = str(directory)
    return environment


def run_local_tests(
    runner: ProcessRunner | None = None,
    *,
    python: str = sys.executable,
) -> int:
    """Run all local CI commands and return the first non-zero exit status."""

    process_runner = runner or subprocess.run
    commands = test_commands(python)
    with TemporaryDirectory(prefix="xjtu-local-test-") as temporary_root:
        environment = isolated_environment(Path(temporary_root))
        for command in commands:
            print(f"==> {command.label}", flush=True)
            result = process_runner(
                command.argv,
                cwd=REPOSITORY_ROOT,
                env=environment,
                check=False,
            )
            if result.returncode:
                print(
                    f"FAILED: {command.label} (exit {result.returncode})",
                    file=sys.stderr,
                    flush=True,
                )
                return result.returncode
    print(f"PASS: {len(commands)} local test commands succeeded.", flush=True)
    return 0


def main() -> int:
    return run_local_tests()


if __name__ == "__main__":
    raise SystemExit(main())
