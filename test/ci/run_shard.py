"""运行一个 PR 测试分片。"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path
from typing import Sequence

from test.ci.shards import SHARDS, get_shard


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def build_suite(shard_id: str) -> unittest.TestSuite:
    """从稳定分片定义构建一个 unittest suite。"""

    shard = get_shard(shard_id)
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()

    for directory in shard.discovery_dirs:
        suite.addTests(
            loader.discover(
                start_dir=str(REPOSITORY_ROOT / directory),
                pattern="*.py",
                top_level_dir=str(REPOSITORY_ROOT),
            )
        )
    for module in shard.explicit_modules:
        suite.addTests(loader.loadTestsFromName(module))

    return suite


def finish_result(
    result: unittest.TestResult, *, hard_exit_on_success: bool
) -> int:
    """返回测试结果；按需跳过已知会崩溃的成功后 teardown。"""

    if not result.wasSuccessful():
        return 1
    if hard_exit_on_success:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shard", choices=tuple(shard.id for shard in SHARDS))
    parser.add_argument(
        "--hard-exit-on-success",
        action="store_true",
        help="测试成功并刷新日志后跳过解释器 teardown",
    )
    args = parser.parse_args(argv)

    result = unittest.TextTestRunner(verbosity=2).run(build_suite(args.shard))
    return finish_result(
        result,
        hard_exit_on_success=args.hard_exit_on_success,
    )


if __name__ == "__main__":
    raise SystemExit(main())
