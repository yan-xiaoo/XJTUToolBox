"""Minimal PyInstaller probe for bundled declarative notification and AI data."""

from __future__ import annotations

import sys
from collections import Counter

from ai_assistant import PRESETS
from notification.source import source_registry


def main() -> None:
    sources = source_registry.sources()
    print(f"frozen={bool(getattr(sys, 'frozen', False))}")
    print(f"sources={len(sources)}")
    print(f"defaults={','.join(source_registry.defaults())}")
    print("statuses=" + ",".join(f"{key}:{value}" for key, value in sorted(Counter(one.status for one in sources).items())))
    print("protocols=" + ",".join(sorted({one.protocol for one in PRESETS})))


if __name__ == "__main__":
    main()
