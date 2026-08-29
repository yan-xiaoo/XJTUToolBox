"""Discover pull-request test domains from metadata in each test module.

The domain definitions in this module are intentionally stable.  Product test
files own their membership through a top-level ``TEST_DOMAIN`` assignment; the
scanner below reads that assignment with :mod:`ast` so checking the inventory
never imports (or executes) a product test module.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPOSITORY_ROOT / "test"


@dataclass(frozen=True)
class Shard:
    """A named, independently runnable group of test modules."""

    id: str
    name: str
    # ``modules`` remains public for runners and synthetic contract tests.  It
    # is populated automatically for the real ``SHARDS`` value below.
    modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class TestModule:
    """AST-level metadata for one product test file."""

    module: str
    path: Path
    marker_values: tuple[Any, ...] = ()
    parse_error: str | None = None
    regression_values: tuple[Any, ...] = ()


# Keep this tuple as the only source of stable domain IDs, display names, and
# their matrix order.  Adding a test to an existing domain does not touch it.
DOMAIN_DEFINITIONS: tuple[Shard, ...] = (
    Shard("ai", "AI core and features"),
    Shard("qt-ui", "Qt and desktop UI"),
    Shard("notification-crawler", "Notifications and crawler"),
    Shard("auth-session", "Authentication and sessions"),
    Shard("schedule", "Schedule"),
)


def _is_product_test(path: Path, test_root: Path) -> bool:
    """Return whether ``path`` belongs to the product-test inventory."""

    relative = path.relative_to(test_root)
    return (
        path.suffix == ".py"
        and path.name != "__init__.py"
        and (not relative.parts or relative.parts[0] != "ci")
    )


def iter_product_test_files(test_root: Path = TEST_ROOT) -> Iterator[Path]:
    """Yield product test files in deterministic relative-path order."""

    if not test_root.is_dir():
        return
    paths = (
        path
        for path in test_root.rglob("*.py")
        if _is_product_test(path, test_root)
    )
    yield from sorted(paths, key=lambda path: path.relative_to(test_root).as_posix())


def module_name(path: Path, test_root: Path = TEST_ROOT) -> str:
    """Convert a Python path below ``test_root`` into a ``test.*`` import."""

    relative = path.relative_to(test_root).with_suffix("")
    return "test." + ".".join(relative.parts)


def _marker_values(
    tree: ast.Module, marker_name: str = "TEST_DOMAIN"
) -> tuple[Any, ...]:
    """Read one direct marker declaration and reject every other binding.

    Exactly one direct, top-level literal assignment is valid.  Writes inside
    module-level control flow, imports, loops, context managers, exception
    handlers, named expressions, augmented assignments, deletions, chained
    assignments, and dynamic values produce invalid sentinels.  Function and
    class bodies are separate scopes and are not metadata declarations.
    """

    class MarkerBindingVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.values: list[Any] = []
            self.direct_target_ids: set[int] = set()

        def read_direct_declarations(self) -> None:
            for statement in tree.body:
                targets: tuple[ast.expr, ...]
                value: ast.expr | None
                if isinstance(statement, ast.Assign):
                    targets = tuple(statement.targets)
                    value = statement.value
                elif isinstance(statement, ast.AnnAssign):
                    targets = (statement.target,)
                    value = statement.value
                else:
                    continue
                marker_targets = [
                    target
                    for target in targets
                    if isinstance(target, ast.Name) and target.id == marker_name
                ]
                if not marker_targets:
                    continue
                self.direct_target_ids.update(id(target) for target in marker_targets)
                if len(targets) != 1 or not isinstance(targets[0], ast.Name):
                    self.values.append(None)
                elif isinstance(value, ast.Constant):
                    self.values.append(value.value)
                else:
                    self.values.append(None)

        def visit_Name(self, node: ast.Name) -> None:
            if (
                node.id == marker_name
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and id(node) not in self.direct_target_ids
            ):
                self.values.append(None)

        def visit_alias(self, node: ast.alias) -> None:
            bound_name = node.asname or node.name.split(".", 1)[0]
            if bound_name == marker_name:
                self.values.append(None)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name == marker_name:
                self.values.append(None)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_MatchAs(self, node: ast.MatchAs) -> None:
            if node.name == marker_name:
                self.values.append(None)
            if node.pattern is not None:
                self.visit(node.pattern)

        def visit_MatchStar(self, node: ast.MatchStar) -> None:
            if node.name == marker_name:
                self.values.append(None)

        def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
            if node.rest == marker_name:
                self.values.append(None)
            self.generic_visit(node)

        def _visit_definition_header(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef
        ) -> None:
            if node.name == marker_name:
                self.values.append(None)
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)
            if node.returns is not None:
                self.visit(node.returns)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_definition_header(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_definition_header(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            if node.name == marker_name:
                self.values.append(None)
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)

    visitor = MarkerBindingVisitor()
    visitor.read_direct_declarations()
    visitor.visit(tree)
    return tuple(visitor.values)


def scan_test_modules(test_root: Path = TEST_ROOT) -> tuple[TestModule, ...]:
    """Parse product tests and return their marker metadata without imports."""

    records: list[TestModule] = []
    for path in iter_product_test_files(test_root):
        module = module_name(path, test_root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as error:
            records.append(TestModule(module, path, parse_error=str(error)))
        else:
            records.append(
                TestModule(
                    module,
                    path,
                    marker_values=_marker_values(tree),
                    regression_values=_marker_values(tree, "TEST_REGRESSION"),
                )
            )
    return tuple(records)


def shards_for_test_root(test_root: Path = TEST_ROOT) -> tuple[Shard, ...]:
    """Build domain shards from valid markers below ``test_root``."""

    modules_by_domain = {definition.id: [] for definition in DOMAIN_DEFINITIONS}
    for record in scan_test_modules(test_root):
        if len(record.marker_values) != 1:
            continue
        domain = record.marker_values[0]
        if isinstance(domain, str) and domain in modules_by_domain:
            modules_by_domain[domain].append(record.module)
    return tuple(
        Shard(definition.id, definition.name, tuple(modules_by_domain[definition.id]))
        for definition in DOMAIN_DEFINITIONS
    )


def regression_modules(
    records: tuple[TestModule, ...] | None = None,
) -> tuple[str, ...]:
    """Return modules marked for historical regression coverage.

    The default scan is intentionally AST-only.  A caller checking another
    checkout can pass records from :func:`scan_test_modules` or use
    :func:`regression_modules_for_test_root`.
    """

    if records is None:
        records = scan_test_modules()
    return tuple(
        record.module
        for record in records
        if len(record.regression_values) == 1
        and record.regression_values[0] is True
    )


def regression_modules_for_test_root(test_root: Path = TEST_ROOT) -> tuple[str, ...]:
    """Return marked regression modules discovered below ``test_root``."""

    return regression_modules(scan_test_modules(test_root))


# The runner imports this value directly.  It is generated once per process,
# while the contract checker can rescan an arbitrary root for isolated tests.
SHARDS: tuple[Shard, ...] = shards_for_test_root()

# Backward-compatible generated view for callers that imported the former
# hand-maintained constant.  New code should call ``regression_modules()`` so
# it can rescan an alternate test root when needed.
REGRESSION_MODULES: tuple[str, ...] = regression_modules()


def get_shard(shard_id: str) -> Shard:
    """Return a domain by ID, raising ``ValueError`` for unknown IDs."""

    for shard in SHARDS:
        if shard.id == shard_id:
            return shard
    raise ValueError(f"unknown test domain: {shard_id}")


def all_modules(shards: tuple[Shard, ...] = SHARDS) -> tuple[str, ...]:
    """Return modules in declaration order, retaining duplicate entries."""

    return tuple(module for shard in shards for module in shard.modules)
