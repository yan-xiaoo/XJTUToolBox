"""Validate that product tests are registered in exactly one test domain."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from test.ci.shards import REGRESSION_MODULES, SHARDS, Shard


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPOSITORY_ROOT / "test"
DOMAIN_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXPECTED_DOMAINS = (
    ("ai", "AI core and features"),
    ("qt-ui", "Qt and desktop UI"),
    ("notification-crawler", "Notifications and crawler"),
    ("auth-session", "Authentication and sessions"),
    ("schedule", "Schedule"),
)


def module_name(path: Path, test_root: Path = TEST_ROOT) -> str:
    """Convert a Python path below ``test_root`` into a ``test.*`` import."""

    relative = path.relative_to(test_root).with_suffix("")
    return "test." + ".".join(relative.parts)


def product_test_modules(test_root: Path = TEST_ROOT) -> set[str]:
    """Discover product tests, excluding package markers and ``test/ci``."""

    return {
        module_name(path, test_root)
        for path in test_root.rglob("*.py")
        if path.name != "__init__.py"
        and path.relative_to(test_root).parts[0] != "ci"
    }


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
) -> tuple[set[str], dict[str, list[str]], set[str]]:
    """Return missing, multiply owned, and unexpected declared modules."""

    if product_modules is None:
        product_modules = product_test_modules()
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


def contract_errors(
    shards: tuple[Shard, ...] = SHARDS,
    repository_root: Path = REPOSITORY_ROOT,
    product_modules: set[str] | None = None,
) -> list[str]:
    """Collect every deterministic inventory, path and syntax violation."""

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

    if product_modules is None:
        product_modules = product_test_modules(repository_root / "test")
    missing, duplicates, unexpected = inventory_problems(shards, product_modules)
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
        except (OSError, SyntaxError) as error:
            errors.append(f"cannot parse {module}: {error}")

    for module in REGRESSION_MODULES:
        if module not in declared:
            errors.append(f"regression module is not in a domain: {module}")
    if len(REGRESSION_MODULES) != len(set(REGRESSION_MODULES)):
        errors.append("duplicate regression module")
    return errors


def main() -> int:
    errors = contract_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(product_test_modules())} product test modules are covered by "
        f"{len(SHARDS)} domains."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
