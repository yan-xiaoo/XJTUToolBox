"""Validate that product tests declare exactly one known test domain."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Iterable

from test.ci.shards import (
    DOMAIN_DEFINITIONS,
    MINIMUM_REGRESSION_MODULES,
    REPOSITORY_ROOT,
    SHARDS,
    TEST_ROOT,
    Shard,
    TestModule,
    module_name,
    regression_modules,
    scan_test_modules,
    shards_for_records,
)


DOMAIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXPECTED_DOMAINS = tuple(
    (definition.id, definition.name) for definition in DOMAIN_DEFINITIONS
)


def product_test_modules(test_root: Path = TEST_ROOT) -> set[str]:
    """Discover product-test import names without importing test modules."""

    return {record.module for record in scan_test_modules(test_root)}


def owned_modules(shards: tuple[Shard, ...] = SHARDS) -> dict[str, list[str]]:
    """Map each declared module to all domains that claim it."""

    owners: dict[str, list[str]] = {}
    for shard in shards:
        for module in shard.modules:
            owners.setdefault(module, []).append(shard.id)
    return owners


def inventory_problems(
    shards: tuple[Shard, ...] = SHARDS,
    product_modules: set[str] | None = None,
    test_root: Path = TEST_ROOT,
) -> tuple[set[str], dict[str, list[str]], set[str]]:
    """Return missing, multiply owned, and unexpected declared modules."""

    if product_modules is None:
        product_modules = product_test_modules(test_root)
    owners = owned_modules(shards)
    declared = set(owners)
    missing = product_modules - declared
    duplicates = {
        module: shard_ids
        for module, shard_ids in owners.items()
        if module in product_modules and len(shard_ids) > 1
    }
    unexpected = declared - product_modules
    return missing, duplicates, unexpected


def _marker_errors(records: Iterable[TestModule], known_domains: set[str]) -> list[str]:
    """Return deterministic errors for every malformed module marker."""

    errors: list[str] = []
    for record in records:
        if record.parse_error is not None:
            errors.append(f"cannot parse {record.module}: {record.parse_error}")
            continue
        if not record.marker_values:
            errors.append(f"missing TEST_DOMAIN marker: {record.module}")
            continue
        if len(record.marker_values) > 1:
            errors.append(f"duplicate TEST_DOMAIN marker: {record.module}")
            continue
        value = record.marker_values[0]
        if not isinstance(value, str):
            errors.append(
                f"TEST_DOMAIN must be a string: {record.module} (got {value!r})"
            )
            continue
        if not DOMAIN_ID_PATTERN.fullmatch(value):
            errors.append(f"invalid TEST_DOMAIN marker: {record.module} ({value!r})")
        elif value not in known_domains:
            errors.append(f"unknown TEST_DOMAIN domain: {record.module} ({value})")
    return errors


def _regression_marker_errors(records: Iterable[TestModule]) -> list[str]:
    """Validate optional top-level ``TEST_REGRESSION`` boolean markers."""

    errors: list[str] = []
    for record in records:
        if record.parse_error is not None or not record.regression_values:
            continue
        if len(record.regression_values) > 1:
            errors.append(f"duplicate TEST_REGRESSION marker: {record.module}")
            continue
        value = record.regression_values[0]
        if not isinstance(value, bool):
            errors.append(
                f"TEST_REGRESSION must be a boolean: {record.module} (got {value!r})"
            )
    return errors


def contract_errors(
    shards: tuple[Shard, ...] | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    product_modules: set[str] | None = None,
    minimum_regression_modules: int = MINIMUM_REGRESSION_MODULES,
) -> list[str]:
    """Collect deterministic inventory, marker, path, and syntax violations."""

    test_root = repository_root / "test"
    records = scan_test_modules(test_root)
    if shards is None:
        shards = shards_for_records(records)
    errors: list[str] = []
    domains = tuple((shard.id, shard.name) for shard in shards)
    ids = [shard.id for shard in shards]
    names = [shard.name for shard in shards]
    if domains != EXPECTED_DOMAINS:
        errors.append(f"unexpected domains: {domains!r}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate domain ID")
    if len(names) != len(set(names)):
        errors.append("duplicate domain name")
    for shard in shards:
        if not shard.modules:
            errors.append(f"empty domain: {shard.id}")
        if not DOMAIN_ID_PATTERN.fullmatch(shard.id):
            errors.append(f"invalid domain ID: {shard.id!r}")

    errors.extend(_marker_errors(records, {shard.id for shard in DOMAIN_DEFINITIONS}))
    errors.extend(_regression_marker_errors(records))
    if product_modules is None:
        product_modules = {record.module for record in records}
    missing, duplicates, unexpected = inventory_problems(
        shards, product_modules, test_root
    )
    errors.extend(f"missing test module: {module}" for module in sorted(missing))
    errors.extend(
        f"duplicate test module: {module} ({','.join(owners)})"
        for module, owners in sorted(duplicates.items())
    )
    errors.extend(
        f"unexpected declared module: {module}" for module in sorted(unexpected)
    )

    declared = set(owned_modules(shards))
    for module in sorted(declared):
        path = repository_root / Path(*module.split(".")).with_suffix(".py")
        if not path.is_file():
            errors.append(f"declared module has no file: {module}")
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as error:
            # Product files are normally parsed by ``scan_test_modules``; this
            # second check also covers an explicitly declared file under the
            # excluded ``test/ci`` tree or a synthetic contract fixture.
            parse_error = f"cannot parse {module}: {error}"
            if parse_error not in errors:
                errors.append(parse_error)

    regression_targets = regression_modules(records)
    if not regression_targets:
        errors.append("no regression test modules are marked")
    elif len(regression_targets) < minimum_regression_modules:
        errors.append(
            "too few regression test modules are marked: "
            f"{len(regression_targets)} (minimum {minimum_regression_modules})"
        )
    for module in regression_targets:
        if module not in declared:
            errors.append(f"regression module is not in a domain: {module}")
    if len(regression_targets) != len(set(regression_targets)):
        errors.append("duplicate regression module")
    return errors


def render_inventory_markdown(
    shards: tuple[Shard, ...] | None = None,
    product_modules: set[str] | None = None,
    regression_targets: tuple[str, ...] | None = None,
    test_root: Path = TEST_ROOT,
) -> str:
    """Render the current runtime inventory for humans and documentation."""

    records = scan_test_modules(test_root)
    if shards is None:
        shards = shards_for_records(records)
    if product_modules is None:
        product_modules = {record.module for record in records}
    if regression_targets is None:
        regression_targets = regression_modules(records)
    lines = [
        f"## Test inventory: {len(product_modules)} product test modules",
        f"Covered by {len(shards)} domains.",
        "",
        "| Domain ID | Display name | Module count | Modules |",
        "|---|---|---:|---|",
    ]
    for shard in shards:
        modules = ", ".join(f"`{module}`" for module in shard.modules) or "_none_"
        lines.append(
            f"| `{shard.id}` | {shard.name} | {len(shard.modules)} | {modules} |"
        )
    lines.extend(("", "### Regression modules", ""))
    if regression_targets:
        lines.extend(f"- `{module}`" for module in regression_targets)
    else:
        lines.append("_none_")
    return "\n".join(lines) + "\n"


def render_domain_matrix_json(
    definitions: tuple[Shard, ...] = DOMAIN_DEFINITIONS,
) -> str:
    """Render the validated domain definitions for GitHub Actions matrices."""

    return json.dumps(
        [{"id": definition.id, "name": definition.name} for definition in definitions],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _text_output(test_root: Path = TEST_ROOT) -> str:
    records = scan_test_modules(test_root)
    shards = shards_for_records(records)
    return (
        f"OK: {len(records)} product test modules are "
        f"covered by {len(shards)} domains."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("text", "markdown", "domain-json"),
        default="text",
        help="output format after the contract passes",
    )
    args = parser.parse_args(argv)
    errors = contract_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.format == "markdown":
        print(render_inventory_markdown(), end="")
    elif args.format == "domain-json":
        print(render_domain_matrix_json())
    else:
        print(_text_output())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
