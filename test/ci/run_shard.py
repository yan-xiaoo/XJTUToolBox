"""运行一个 PR 测试分片。"""

from __future__ import annotations

import argparse
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shard", choices=tuple(shard.id for shard in SHARDS))
    args = parser.parse_args(argv)

    result = unittest.TextTestRunner(verbosity=2).run(build_suite(args.shard))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
