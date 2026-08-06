"""Read-only online smoke test for bundled notification sources."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notification.crawlers import create_crawler
from notification.source import source_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_ids", nargs="*")
    parser.add_argument("--include-unverified", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--show-title", action="store_true")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="parallel source checks (1-32; default: sequential)",
    )
    args = parser.parse_args()
    if not 1 <= args.workers <= 32:
        parser.error("--workers must be between 1 and 32")

    selected = set(args.source_ids)
    sources = [
        source
        for source in source_registry.sources(include_unverified=args.include_unverified)
        if not selected or source.id in selected
    ]

    def check_source(source):
        started = time.monotonic()
        try:
            notifications = create_crawler(
                source.id,
                pages=1,
                allow_unverified=args.include_unverified,
            ).get_notifications()
            if not notifications:
                raise ValueError("no notification item extracted")
        except Exception as error:
            return {
                "source": source.id,
                "status": "fail",
                "count": 0,
                "seconds": round(time.monotonic() - started, 2),
                "error": f"{type(error).__name__}: {error}",
            }
        else:
            return {
                "source": source.id,
                "status": "ok",
                "count": len(notifications),
                "seconds": round(time.monotonic() - started, 2),
                "newest": max(item.date for item in notifications).isoformat(),
                "sample_title": notifications[0].title,
            }

    if args.workers == 1:
        results = [check_source(source) for source in sources]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            results = list(executor.map(check_source, sources))

    for source, result in zip(sources, results):
        if not args.json:
            sample = f" title={result.get('sample_title', '')}" if args.show_title else ""
            print(
                f"{result['status'].upper():4} {source.id:24} "
                f"items={result['count']:3} seconds={result['seconds']:6.2f} "
                f"{result.get('error', '')}{sample}",
                flush=True,
            )

    summary = {
        "checked": len(results),
        "passed": sum(result["status"] == "ok" for result in results),
        "failed": sum(result["status"] == "fail" for result in results),
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"SUMMARY checked={summary['checked']} passed={summary['passed']} failed={summary['failed']}",
            flush=True,
        )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
