"""Unit and static contract tests for the pull-request test workflow."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

import local_test

from test.ci.check_test_contract import (
    REPOSITORY_ROOT,
    contract_errors,
    inventory_problems,
    module_name,
    owned_modules,
    product_test_modules,
    render_domain_matrix_json,
    render_inventory_markdown,
)
from test.ci import run_test_regressions, run_test_shard
from test.ci.run_test_regressions import (
    build_suite as build_regression_suite,
    finish_result as finish_regression_result,
)
from test.ci.run_test_shard import (
    build_suite,
    canonical_machine,
    finish_result,
    verify_imports,
    verify_machine,
)
from test.ci.shards import (
    DOMAIN_DEFINITIONS,
    SHARDS,
    Shard,
    get_shard,
    regression_modules,
    regression_modules_for_test_root,
    scan_test_modules,
    shards_for_test_root,
)


WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "pr-tests.yml"
TESTING_DOC_PATH = REPOSITORY_ROOT / "docs" / "development" / "testing.md"
NOTIFICATION_DOC_PATH = REPOSITORY_ROOT / "docs" / "development" / "notification.md"
PR_TEMPLATE_PATH = REPOSITORY_ROOT / ".github" / "pull_request_template.md"

XDG_RUNNER_TEMP_ENV = (
    "XDG_STATE_HOME: ${{ runner.temp }}/xjtu-test-state",
    "XDG_CONFIG_HOME: ${{ runner.temp }}/xjtu-test-config",
    "XDG_DATA_HOME: ${{ runner.temp }}/xjtu-test-data",
    "XDG_CACHE_HOME: ${{ runner.temp }}/xjtu-test-cache",
)


HOSTED_PLATFORMS = (
    ("linux-x64-py310", "ubuntu-22.04", "3.10", "x86_64"),
    ("linux-x64-py313", "ubuntu-22.04", "3.13", "x86_64"),
    ("windows-x64-py312", "windows-latest", "3.12", "x86_64"),
    ("macos-arm64-py312", "macos-latest", "3.12", "arm64"),
    ("macos-intel-py312", "macos-15-intel", "3.12", "x86_64"),
)

EXPECTED_DOMAINS = tuple(
    (definition.id, definition.name) for definition in DOMAIN_DEFINITIONS
)

ARM_IMPORTS = (
    "PyQt5",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtSvg",
    "PyQt5.QtX11Extras",
    "qfluentwidgets",
    "qframelesswindow",
    "xcffib",
)

ARM_PINS = (
    "pyqt-fluent-widgets==1.8.7",
    "pyqt5-frameless-window==0.7.5",
    "darkdetect==0.8.0",
    "xcffib==1.12.0",
)

DOMAIN_MATRIX_EXPRESSION = "${{ fromJSON(needs.test-contract.outputs.domains) }}"


class TestLocalTestRunner(unittest.TestCase):
    def test_commands_reuse_contract_and_every_registered_domain(self) -> None:
        commands = local_test.test_commands("/example/python")

        self.assertEqual(
            (
                "/example/python",
                "-m",
                "unittest",
                "-v",
                "test.ci.test_pr_workflow",
            ),
            commands[0].argv,
        )
        self.assertEqual(
            [shard.id for shard in SHARDS],
            [command.argv[-1] for command in commands[1:]],
        )
        for command in commands[1:]:
            self.assertEqual(
                (
                    "/example/python",
                    "-m",
                    "test.ci.run_test_shard",
                    "--domain",
                ),
                command.argv[:-1],
            )

    def test_isolated_environment_creates_writable_qt_and_xdg_paths(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base = {"PRESERVED": "yes"}

            environment = local_test.isolated_environment(root, base)

            self.assertEqual("yes", environment["PRESERVED"])
            self.assertEqual("1", environment["PYTHONUTF8"])
            self.assertEqual("offscreen", environment["QT_QPA_PLATFORM"])
            self.assertEqual("software", environment["QT_OPENGL"])
            self.assertEqual("1", environment["LIBGL_ALWAYS_SOFTWARE"])
            for name in (
                "XDG_STATE_HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_CACHE_HOME",
            ):
                path = Path(environment[name])
                self.assertTrue(path.is_dir())
                self.assertTrue(path.is_relative_to(root))
            self.assertEqual({"PRESERVED": "yes"}, base)

    def test_run_local_tests_stops_at_the_first_failure(self) -> None:
        results = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 9),
        ]
        runner = Mock(side_effect=results)

        with patch("builtins.print"):
            return_code = local_test.run_local_tests(runner=runner)

        self.assertEqual(9, return_code)
        self.assertEqual(2, runner.call_count)

    def test_run_local_tests_runs_every_command_and_removes_temporary_paths(self) -> None:
        observed_roots: list[Path] = []

        def successful_runner(argv, *, cwd, env, check):
            self.assertEqual(REPOSITORY_ROOT, cwd)
            self.assertFalse(check)
            self.assertEqual(sys.executable, argv[0])
            root = Path(env["XDG_STATE_HOME"]).parent
            observed_roots.append(root)
            for name in (
                "XDG_STATE_HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_CACHE_HOME",
            ):
                self.assertTrue(Path(env[name]).is_dir())
            return subprocess.CompletedProcess(argv, 0)

        original_environment = os.environ.copy()
        with patch("builtins.print"):
            return_code = local_test.run_local_tests(runner=successful_runner)

        self.assertEqual(0, return_code)
        self.assertEqual(1 + len(SHARDS), len(observed_roots))
        self.assertEqual(1, len(set(observed_roots)))
        self.assertFalse(observed_roots[0].exists())
        self.assertEqual(original_environment, os.environ)


def job_section(workflow: str, job_id: str) -> str:
    marker = f"  {job_id}:"
    if marker not in workflow:
        return ""
    remainder = workflow.split(marker, 1)[1]
    next_job = re.search(r"(?m)^  [a-z0-9-]+:\s*$", remainder)
    return remainder[: next_job.start()] if next_job else remainder


def job_env_section(workflow: str, job_id: str) -> str:
    section = job_section(workflow, job_id)
    marker = "    env:\n"
    if marker not in section:
        return ""
    remainder = section.split(marker, 1)[1]
    next_property = re.search(r"(?m)^    [a-zA-Z][a-zA-Z0-9_-]*:", remainder)
    return remainder[: next_property.start()] if next_property else remainder


def named_step_section(workflow: str, job_id: str, step_name: str) -> str:
    section = job_section(workflow, job_id)
    marker = f"      - name: {step_name}"
    if marker not in section:
        return ""
    remainder = section.split(marker, 1)[1]
    next_step = re.search(r"(?m)^      - name: ", remainder)
    return remainder[: next_step.start()] if next_step else remainder


def named_step_env_section(workflow: str, job_id: str, step_name: str) -> str:
    section = named_step_section(workflow, job_id, step_name)
    marker = "\n        env:\n"
    if marker not in section:
        return ""
    remainder = section.split(marker, 1)[1]
    next_property = re.search(r"(?m)^        [a-zA-Z][a-zA-Z0-9_-]*:", remainder)
    return remainder[: next_property.start()] if next_property else remainder


def xdg_context_contract_errors(workflow: str) -> list[str]:
    errors: list[str] = []
    jobs_section = (
        workflow.split("jobs:\n", 1)[1] if "jobs:\n" in workflow else ""
    )
    for job_id in re.findall(r"(?m)^  ([a-z0-9-]+):\s*$", jobs_section):
        if re.search(r"\$\{\{\s*runner\.", job_env_section(workflow, job_id)):
            errors.append(f"{job_id} job env uses runner context")

    targets = (
        ("test-shards", "Run ${{ matrix.domain.name }} tests"),
        ("existing-bug-regressions", "Run historical bug regressions"),
    )
    for job_id, step_name in targets:
        step = named_step_section(workflow, job_id, step_name)
        if not step:
            errors.append(f"{job_id} test step is missing")
            continue
        step_env = named_step_env_section(workflow, job_id, step_name)
        for entry in XDG_RUNNER_TEMP_ENV:
            if step_env.count(entry) != 1:
                errors.append(f"{job_id} test step has unexpected {entry}")
    return errors


def matrix_records(
    workflow: str, job_id: str, axis: str
) -> tuple[dict[str, str], ...]:
    """Extract list records from one fixed-indentation matrix axis."""

    section = job_section(workflow, job_id)
    match = re.search(
        rf"(?m)^        {re.escape(axis)}:\n((?:          .*\n)*)",
        section,
    )
    if not match:
        return ()
    records: list[dict[str, str]] = []
    for line in match.group(1).splitlines():
        item = re.fullmatch(r"          - ([a-z-]+): (.+)", line)
        field = re.fullmatch(r"            ([a-z-]+): (.+)", line)
        if item:
            records.append({item.group(1): item.group(2).strip('"')})
        elif field and records:
            records[-1][field.group(1)] = field.group(2).strip('"')
    return tuple(records)


def matrix_axis_expression(workflow: str, job_id: str, axis: str) -> str | None:
    """Extract a scalar GitHub Actions expression from a matrix axis."""

    section = job_section(workflow, job_id)
    match = re.search(rf"(?m)^        {re.escape(axis)}: (.+)$", section)
    return match.group(1).strip() if match else None


def matrix_contract_errors(workflow: str) -> list[str]:
    """Return exact job, platform, matrix-expression, and display-name drift."""

    errors: list[str] = []
    jobs_section = workflow.split("jobs:\n", 1)[1] if "jobs:\n" in workflow else ""
    job_ids = tuple(re.findall(r"(?m)^  ([a-z0-9-]+):\s*$", jobs_section))
    expected_job_ids = (
        "test-contract",
        "test-shards",
        "linux-arm-shards",
        "existing-bug-regressions",
        "ci-gate",
    )
    expected_platforms = tuple(
        {
            "id": platform_id,
            "os": runner,
            "python-version": python_version,
            "machine": machine,
        }
        for platform_id, runner, python_version, machine in HOSTED_PLATFORMS
    )
    hosted_platforms = matrix_records(workflow, "test-shards", "platform")
    hosted_domain_expression = matrix_axis_expression(
        workflow, "test-shards", "domain"
    )
    arm_domain_expression = matrix_axis_expression(
        workflow, "linux-arm-shards", "domain"
    )
    if job_ids != expected_job_ids:
        errors.append(f"unexpected workflow jobs: {job_ids!r}")
    if hosted_platforms != expected_platforms:
        errors.append(f"unexpected hosted platforms: {hosted_platforms!r}")
    if hosted_domain_expression != DOMAIN_MATRIX_EXPRESSION:
        errors.append(
            f"unexpected hosted domain matrix: {hosted_domain_expression!r}"
        )
    if arm_domain_expression != DOMAIN_MATRIX_EXPRESSION:
        errors.append(f"unexpected QEMU domain matrix: {arm_domain_expression!r}")
    contract = job_section(workflow, "test-contract")
    if "domains: ${{ steps.domains.outputs.domains }}" not in contract:
        errors.append("test-contract does not expose the domain matrix output")
    if "id: domains" not in contract:
        errors.append("test-contract does not export the domain matrix")
    hosted_name = (
        "    name: ${{ matrix.domain.name }} "
        "(${{ matrix.platform.id }}, Python "
        "${{ matrix.platform.python-version }})"
    )
    arm_name = (
        "    name: ${{ matrix.domain.name }} "
        "(linux-arm64-qemu-py310, Python 3.10)"
    )
    if hosted_name not in job_section(workflow, "test-shards"):
        errors.append("unexpected hosted job name")
    if arm_name not in job_section(workflow, "linux-arm-shards"):
        errors.append("unexpected QEMU job name")
    return errors


def gate_script(workflow: str) -> str:
    section = job_section(workflow, "ci-gate")
    match = re.search(
        r"(?ms)^        run: \|\n((?:          .*\n?)*)", section
    )
    return textwrap.dedent(match.group(1)) if match else ""


def arm_hard_exit_contract_errors(workflow: str) -> list[str]:
    """Return drift from the QEMU-only Qt UI teardown workaround."""

    errors: list[str] = []
    arm = job_section(workflow, "linux-arm-shards")
    hosted = job_section(workflow, "test-shards")
    if workflow.count("--hard-exit-on-success") != 1:
        errors.append("unexpected hard-exit option count")
    if "--hard-exit-on-success" in hosted:
        errors.append("hosted job enables hard exit")
    if 'if [ "${{ matrix.domain.id }}" = "qt-ui" ]; then' not in arm:
        errors.append("Qt UI condition is missing")
    if 'hard_exit_arg="--hard-exit-on-success"' not in arm:
        errors.append("hard-exit assignment is missing")
    if "$hard_exit_arg" not in arm:
        errors.append("runner does not consume hard-exit argument")
    return errors


class TestInventoryContract(unittest.TestCase):
    def test_domain_ids_and_names_are_exact(self) -> None:
        self.assertEqual(
            EXPECTED_DOMAINS,
            tuple((shard.id, shard.name) for shard in SHARDS),
        )

    def test_current_modules_have_exactly_one_owner(self) -> None:
        missing, duplicates, unexpected = inventory_problems()
        self.assertEqual(set(), missing)
        self.assertEqual({}, duplicates)
        self.assertEqual(set(), unexpected)
        self.assertEqual(SHARDS, shards_for_test_root())
        self.assertTrue(all(not shard.modules for shard in DOMAIN_DEFINITIONS))
        self.assertEqual(product_test_modules(), set(owned_modules()))

    def test_missing_assignment_is_rejected(self) -> None:
        missing, duplicates, unexpected = inventory_problems(SHARDS[:-1])
        self.assertEqual(set(SHARDS[-1].modules), missing)
        self.assertEqual({}, duplicates)
        self.assertEqual(set(), unexpected)

    def test_duplicate_assignment_is_rejected(self) -> None:
        duplicate = Shard("duplicate", "Duplicate", SHARDS[0].modules)
        missing, duplicates, unexpected = inventory_problems(SHARDS + (duplicate,))
        self.assertEqual(set(), missing)
        module = SHARDS[0].modules[0]
        self.assertEqual(
            ["ai", "duplicate"], duplicates[module]
        )
        self.assertEqual(set(), unexpected)

    def test_discovery_excludes_only_the_contract_tree(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory) / "test"
            for relative in (
                "__init__.py",
                "ci.py",
                "ci/check_contract.py",
                "feature/ci/test_nested.py",
                "test_product.py",
            ):
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VALUE = 1\n", encoding="utf-8")
            self.assertEqual(
                {"test.ci", "test.feature.ci.test_nested", "test.test_product"},
                product_test_modules(test_root),
            )
            self.assertEqual(
                "test.feature.ci.test_nested",
                module_name(test_root / "feature/ci/test_nested.py", test_root),
            )

    def test_marker_scan_is_ast_only_and_does_not_import_modules(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory) / "test"
            module_path = test_root / "explosive.py"
            module_path.parent.mkdir(parents=True)
            module_path.write_text(
                'TEST_DOMAIN = "ai"\n'
                "TEST_REGRESSION = True\n"
                'raise RuntimeError("must not import")\n',
                encoding="utf-8",
            )

            records = scan_test_modules(test_root)

            self.assertEqual(1, len(records))
            self.assertEqual("test.explosive", records[0].module)
            self.assertEqual(("ai",), records[0].marker_values)
            self.assertEqual((True,), records[0].regression_values)
            self.assertEqual(
                ("test.explosive",), shards_for_test_root(test_root)[0].modules
            )
            self.assertEqual(
                ("test.explosive",),
                regression_modules_for_test_root(test_root),
            )

    def test_nested_marker_writes_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            path = test_root / "nested_marker.py"
            path.parent.mkdir(parents=True)
            path.write_text(
                "# TEST_DOMAIN = 'ai'\n"
                "text = 'TEST_DOMAIN = \\\"ai\\\"'\n"
                "def configure():\n"
                "    TEST_DOMAIN = 'ai'\n"
                "if False:\n"
                "    TEST_DOMAIN = 'ai'\n",
                encoding="utf-8",
            )

            records = scan_test_modules(test_root)
            errors = contract_errors(
                repository_root=repository_root,
                shards=shards_for_test_root(test_root),
            )

            self.assertEqual((None,), records[0].marker_values)
            self.assertIn(
                "TEST_DOMAIN must be a string: test.nested_marker (got None)",
                errors,
            )

    def test_global_and_nonlocal_marker_declarations_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            sources = {
                "global_marker.py": (
                    'TEST_DOMAIN = "ai"\n'
                    "def configure():\n"
                    "    global TEST_DOMAIN\n"
                    '    TEST_DOMAIN = "schedule"\n'
                ),
                "nested_nonlocal.py": (
                    'TEST_DOMAIN = "ai"\n'
                    "def configure():\n"
                    '    value = "outer"\n'
                    "    def nested():\n"
                    "        nonlocal TEST_DOMAIN\n"
                    '        TEST_DOMAIN = "schedule"\n'
                ),
            }
            for relative, source in sources.items():
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")

            records = scan_test_modules(test_root)
            errors = contract_errors(
                repository_root=repository_root,
                minimum_regression_modules=0,
            )

            self.assertIn(None, records[0].marker_values)
            self.assertIn(None, records[1].marker_values)
            self.assertIn(
                "duplicate TEST_DOMAIN marker: test.global_marker", errors
            )
            self.assertIn(
                "duplicate TEST_DOMAIN marker: test.nested_nonlocal", errors
            )

    def test_malformed_markers_are_rejected_without_evaluation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            sources = {
                "duplicate.py": 'TEST_DOMAIN = "ai"\nTEST_DOMAIN = "ai"\n',
                "unknown.py": 'TEST_DOMAIN = "future"\n',
                "invalid.py": 'TEST_DOMAIN = "bad_domain"\n',
                "non_string.py": "TEST_DOMAIN = 123\n",
                "dynamic.py": 'domain = "ai"\nTEST_DOMAIN = domain\n',
            }
            for relative, source in sources.items():
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")

            errors = contract_errors(
                repository_root=repository_root,
                shards=shards_for_test_root(test_root),
            )

            self.assertIn("duplicate TEST_DOMAIN marker: test.duplicate", errors)
            self.assertIn("unknown TEST_DOMAIN domain: test.unknown (future)", errors)
            self.assertIn(
                "invalid TEST_DOMAIN marker: test.invalid ('bad_domain')", errors
            )
            self.assertIn(
                "TEST_DOMAIN must be a string: test.non_string (got 123)", errors
            )
            self.assertIn(
                "TEST_DOMAIN must be a string: test.dynamic (got None)", errors
            )

    def test_malformed_regression_markers_are_rejected_without_evaluation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            sources = {
                "duplicate.py": (
                    'TEST_DOMAIN = "ai"\n'
                    "TEST_REGRESSION = True\n"
                    "TEST_REGRESSION = True\n"
                ),
                "non_boolean.py": (
                    'TEST_DOMAIN = "ai"\nTEST_REGRESSION = "yes"\n'
                ),
                "dynamic.py": (
                    'TEST_DOMAIN = "ai"\nvalue = True\nTEST_REGRESSION = value\n'
                ),
                "chained.py": (
                    'TEST_DOMAIN = "ai"\nTEST_REGRESSION = other = True\n'
                ),
                "false.py": 'TEST_DOMAIN = "ai"\nTEST_REGRESSION = False\n',
            }
            for relative, source in sources.items():
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")

            records = scan_test_modules(test_root)
            errors = contract_errors(
                repository_root=repository_root,
                shards=shards_for_test_root(test_root),
            )

            self.assertIn(
                "duplicate TEST_REGRESSION marker: test.duplicate", errors
            )
            self.assertIn(
                "TEST_REGRESSION must be a boolean: test.non_boolean "
                "(got 'yes')",
                errors,
            )
            self.assertIn(
                "TEST_REGRESSION must be a boolean: test.dynamic (got None)",
                errors,
            )
            self.assertIn(
                "TEST_REGRESSION must be a boolean: test.chained (got None)",
                errors,
            )
            self.assertEqual((), regression_modules(records))

    def test_chained_domain_marker_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            path = test_root / "chained.py"
            path.parent.mkdir(parents=True)
            path.write_text('TEST_DOMAIN = other = "ai"\n', encoding="utf-8")

            errors = contract_errors(
                repository_root=repository_root,
                shards=shards_for_test_root(test_root),
            )

            self.assertIn(
                "TEST_DOMAIN must be a string: test.chained (got None)", errors
            )

    def test_top_level_marker_mutations_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            sources = {
                "domain_augmented.py": (
                    'TEST_DOMAIN = "ai"\nTEST_DOMAIN += "-changed"\n'
                ),
                "domain_deleted.py": 'TEST_DOMAIN = "ai"\ndel TEST_DOMAIN\n',
                "regression_augmented.py": (
                    'TEST_DOMAIN = "ai"\n'
                    "TEST_REGRESSION = True\n"
                    "TEST_REGRESSION += False\n"
                ),
                "regression_deleted.py": (
                    'TEST_DOMAIN = "ai"\n'
                    "TEST_REGRESSION = True\n"
                    "del TEST_REGRESSION\n"
                ),
            }
            for relative, source in sources.items():
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")

            errors = contract_errors(repository_root=repository_root)

            self.assertIn(
                "duplicate TEST_DOMAIN marker: test.domain_augmented", errors
            )
            self.assertIn(
                "duplicate TEST_DOMAIN marker: test.domain_deleted", errors
            )
            self.assertIn(
                "duplicate TEST_REGRESSION marker: test.regression_augmented",
                errors,
            )
            self.assertIn(
                "duplicate TEST_REGRESSION marker: test.regression_deleted",
                errors,
            )

    def test_module_control_flow_cannot_mutate_markers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            sources = {
                "domain_conditional.py": (
                    'TEST_DOMAIN = "ai"\n'
                    "if condition:\n"
                    '    TEST_DOMAIN = "schedule"\n'
                ),
                "regression_conditional.py": (
                    'TEST_DOMAIN = "ai"\n'
                    "TEST_REGRESSION = True\n"
                    "try:\n"
                    "    TEST_REGRESSION = False\n"
                    "except Exception:\n"
                    "    pass\n"
                ),
            }
            for relative, source in sources.items():
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")

            errors = contract_errors(repository_root=repository_root)

            self.assertIn(
                "duplicate TEST_DOMAIN marker: test.domain_conditional", errors
            )
            self.assertIn(
                "duplicate TEST_REGRESSION marker: test.regression_conditional",
                errors,
            )

    def test_other_module_scope_bindings_cannot_mutate_markers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            mutations = {
                "except_target": (
                    "try:\n    pass\n"
                    "except Exception as TEST_DOMAIN:\n    pass\n"
                ),
                "for_target": "for TEST_DOMAIN in ():\n    pass\n",
                "with_target": (
                    "with context_manager() as TEST_DOMAIN:\n    pass\n"
                ),
                "import_alias": "import package as TEST_DOMAIN\n",
                "from_import_alias": "from package import value as TEST_DOMAIN\n",
                "named_expression": "if (TEST_DOMAIN := 'schedule'):\n    pass\n",
                "function_name": "def TEST_DOMAIN():\n    pass\n",
                "class_name": "class TEST_DOMAIN:\n    pass\n",
                "match_case": (
                    "match value:\n"
                    "    case 1:\n"
                    '        TEST_DOMAIN = "schedule"\n'
                ),
                "match_capture": (
                    "match value:\n"
                    "    case TEST_DOMAIN:\n"
                    "        pass\n"
                ),
            }
            for name, mutation in mutations.items():
                path = test_root / f"{name}.py"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    'TEST_DOMAIN = "ai"\n' + mutation,
                    encoding="utf-8",
                )

            errors = contract_errors(repository_root=repository_root)

            for name in mutations:
                with self.subTest(binding=name):
                    self.assertIn(
                        f"duplicate TEST_DOMAIN marker: test.{name}", errors
                    )

    def test_marker_discovery_is_sorted_and_new_files_need_no_central_edit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory) / "test"
            for relative in ("z_added.py", "a_existing.py", "feature/middle.py"):
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('TEST_DOMAIN = "ai"\n', encoding="utf-8")

            records = scan_test_modules(test_root)
            shard = shards_for_test_root(test_root)[0]

            self.assertEqual(
                ("test.a_existing", "test.feature.middle", "test.z_added"),
                tuple(record.module for record in records),
            )
            self.assertEqual(
                ("test.a_existing", "test.feature.middle", "test.z_added"),
                shard.modules,
            )
            self.assertEqual(
                tuple(
                    (definition.id, definition.name)
                    for definition in DOMAIN_DEFINITIONS
                ),
                tuple(
                    (definition.id, definition.name)
                    for definition in shards_for_test_root(test_root)
                ),
            )

    def test_parallel_pr_additions_compose_without_shared_inventory_edits(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory) / "test"
            baseline = {
                "ai/existing.py": 'TEST_DOMAIN = "ai"\n',
                "ui/existing.py": 'TEST_DOMAIN = "qt-ui"\n',
                "notification/existing.py": (
                    'TEST_DOMAIN = "notification-crawler"\n'
                ),
                "auth/existing.py": 'TEST_DOMAIN = "auth-session"\n',
                "schedule/existing.py": 'TEST_DOMAIN = "schedule"\n',
            }
            for relative, source in baseline.items():
                path = test_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")

            first_pr = test_root / "feature_a" / "test_first.py"
            first_pr.parent.mkdir(parents=True)
            first_pr.write_text('TEST_DOMAIN = "ai"\n', encoding="utf-8")
            first_inventory = shards_for_test_root(test_root)
            self.assertIn(
                "test.feature_a.test_first", first_inventory[0].modules
            )
            self.assertNotIn(
                "test.feature_b.test_second",
                {module for shard in first_inventory for module in shard.modules},
            )

            second_pr = test_root / "feature_b" / "test_second.py"
            second_pr.parent.mkdir(parents=True)
            second_pr.write_text(
                'TEST_DOMAIN = "schedule"\nTEST_REGRESSION = True\n',
                encoding="utf-8",
            )
            merged_inventory = shards_for_test_root(test_root)

            self.assertIn("test.feature_a.test_first", merged_inventory[0].modules)
            self.assertIn(
                "test.feature_b.test_second", merged_inventory[-1].modules
            )
            self.assertEqual(
                ("test.feature_b.test_second",),
                regression_modules_for_test_root(test_root),
            )
            self.assertEqual(
                [],
                contract_errors(
                    repository_root=test_root.parent,
                    minimum_regression_modules=1,
                ),
            )

    def test_added_product_module_is_missing(self) -> None:
        product_modules = product_test_modules() | {"test.new_product_test"}
        missing, duplicates, unexpected = inventory_problems(
            product_modules=product_modules
        )
        self.assertEqual({"test.new_product_test"}, missing)
        self.assertEqual({}, duplicates)
        self.assertEqual(set(), unexpected)

    def test_deleted_product_module_makes_declaration_unexpected(self) -> None:
        removed_module = sorted(product_test_modules())[0]
        product_modules = product_test_modules() - {removed_module}
        missing, duplicates, unexpected = inventory_problems(
            product_modules=product_modules
        )
        self.assertEqual(set(), missing)
        self.assertEqual({}, duplicates)
        self.assertEqual({removed_module}, unexpected)

    def test_existing_non_product_module_is_unexpected(self) -> None:
        shards = SHARDS + (
            Shard("ci-tool", "CI tool", ("test.ci.run_test_shard",)),
        )
        self.assertIn(
            "unexpected declared module: test.ci.run_test_shard",
            contract_errors(shards=shards),
        )

    def test_deleted_declared_file_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            errors = contract_errors(
                shards=(Shard("deleted", "Deleted", ("test.deleted",)),),
                repository_root=Path(temporary_directory),
                product_modules={"test.deleted"},
            )
        self.assertIn("declared module has no file: test.deleted", errors)

    def test_syntax_error_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            path = repository_root / "test" / "broken.py"
            path.parent.mkdir(parents=True)
            path.write_text("def broken(:\n", encoding="utf-8")
            errors = contract_errors(
                shards=(Shard("broken", "Broken", ("test.broken",)),),
                repository_root=repository_root,
                product_modules={"test.broken"},
            )
        self.assertTrue(
            any(error.startswith("cannot parse test.broken:") for error in errors),
            errors,
        )

    def test_explicit_empty_inventory_does_not_use_repository_default(self) -> None:
        missing, duplicates, unexpected = inventory_problems(product_modules=set())
        self.assertEqual(set(), missing)
        self.assertEqual({}, duplicates)
        self.assertEqual(set(owned_modules()), unexpected)

    def test_declared_modules_exist_and_parse(self) -> None:
        self.assertEqual([], contract_errors())

    def test_contract_uses_marker_inventory_for_an_isolated_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            path = repository_root / "test" / "only.py"
            path.parent.mkdir(parents=True)
            path.write_text('TEST_DOMAIN = "ai"\n', encoding="utf-8")

            errors = contract_errors(repository_root=repository_root)

            self.assertIn("empty domain: qt-ui", errors)
            self.assertNotIn("missing test module: test.only", errors)

    def test_contract_rejects_an_empty_regression_inventory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            for domain in DOMAIN_DEFINITIONS:
                path = test_root / domain.id / "test_existing.py"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f'TEST_DOMAIN = "{domain.id}"\n', encoding="utf-8"
                )

            errors = contract_errors(repository_root=repository_root)

            self.assertIn("no regression test modules are marked", errors)

    def test_contract_enforces_the_regression_module_floor(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            test_root = repository_root / "test"
            for domain in DOMAIN_DEFINITIONS:
                path = test_root / domain.id / "test_existing.py"
                path.parent.mkdir(parents=True, exist_ok=True)
                marker = "\nTEST_REGRESSION = True" if domain.id == "ai" else ""
                path.write_text(
                    f'TEST_DOMAIN = "{domain.id}"{marker}\n',
                    encoding="utf-8",
                )

            errors = contract_errors(
                repository_root=repository_root,
                minimum_regression_modules=2,
            )

            self.assertIn(
                "too few regression test modules are marked: 1 (minimum 2)",
                errors,
            )

    def test_regressions_are_unique_and_owned(self) -> None:
        modules = regression_modules()
        self.assertTrue(modules)
        self.assertEqual(len(modules), len(set(modules)))
        self.assertLessEqual(set(modules), set(owned_modules()))

    def test_contract_cli_succeeds(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "test.ci.check_test_contract",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            f"{len(product_test_modules())} product test modules",
            result.stdout,
        )

    def test_contract_cli_markdown_uses_runtime_inventory(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "test.ci.check_test_contract",
                "--format",
                "markdown",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(render_inventory_markdown().strip(), result.stdout.strip())

    def test_domain_json_uses_the_single_validated_definition(self) -> None:
        payload = json.loads(render_domain_matrix_json())

        self.assertEqual(
            [
                {"id": definition.id, "name": definition.name}
                for definition in DOMAIN_DEFINITIONS
            ],
            payload,
        )

    def test_contract_cli_domain_json_is_machine_readable(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "test.ci.check_test_contract",
                "--format",
                "domain-json",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(json.loads(render_domain_matrix_json()), json.loads(result.stdout))

    def test_markdown_renderer_rescans_the_requested_test_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory) / "test"
            for domain in DOMAIN_DEFINITIONS:
                path = test_root / domain.id / "test_existing.py"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f'TEST_DOMAIN = "{domain.id}"\n', encoding="utf-8"
                )
            added = test_root / "feature" / "test_added.py"
            added.parent.mkdir(parents=True)
            added.write_text(
                'TEST_DOMAIN = "ai"\nTEST_REGRESSION = True\n',
                encoding="utf-8",
            )

            markdown = render_inventory_markdown(test_root=test_root)

            self.assertIn("6 product test modules", markdown)
            self.assertIn("`test.feature.test_added`", markdown)
            self.assertIn("### Regression modules", markdown)


class TestShardRunner(unittest.TestCase):
    def test_unknown_domain_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown test domain"):
            get_shard("unknown")
        with self.assertRaisesRegex(ValueError, "unknown test domain"):
            build_suite("unknown")

    @patch(
        "test.ci.run_test_shard.unittest.defaultTestLoader.loadTestsFromName",
        return_value=unittest.TestSuite(),
    )
    def test_domain_with_zero_loaded_cases_is_rejected(self, _load_tests) -> None:
        with self.assertRaisesRegex(ValueError, "test domain is empty: ai"):
            build_suite("ai")

    @patch("test.ci.run_test_shard.unittest.defaultTestLoader.loadTestsFromName")
    def test_each_suite_loads_only_declared_modules(self, load_tests) -> None:
        load_tests.side_effect = lambda module: unittest.FunctionTestCase(
            lambda: None, description=module
        )
        for shard in SHARDS:
            with self.subTest(domain=shard.id):
                build_suite(shard.id)
                self.assertEqual(
                    [call.args[0] for call in load_tests.call_args_list],
                    list(shard.modules),
                )
                load_tests.reset_mock()

    def test_machine_aliases_are_canonical(self) -> None:
        self.assertEqual("x86_64", canonical_machine("AMD64"))
        self.assertEqual("x86_64", canonical_machine("x86_64"))
        self.assertEqual("arm64", canonical_machine("aarch64"))
        self.assertEqual("arm64", canonical_machine("arm64"))

    @patch("test.ci.run_test_shard.platform.machine", return_value="aarch64")
    def test_machine_mismatch_fails(self, _machine) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected='x86_64'.*actual='aarch64'"):
            verify_machine("x86_64")

    @patch("test.ci.run_test_shard.importlib.import_module")
    def test_required_imports_are_checked(self, importer) -> None:
        verify_imports(("first.module", "second.module"))
        self.assertEqual(
            [unittest.mock.call("first.module"), unittest.mock.call("second.module")],
            importer.call_args_list,
        )

    def test_hard_exit_flushes_logs_only_after_success(self) -> None:
        result = Mock()
        result.wasSuccessful.return_value = True
        stdout = Mock()
        stderr = Mock()
        hard_exit = Mock(side_effect=RuntimeError("hard exit intercepted"))
        events = Mock()
        events.attach_mock(stdout.flush, "stdout_flush")
        events.attach_mock(stderr.flush, "stderr_flush")
        events.attach_mock(hard_exit, "hard_exit")

        with patch.object(run_test_shard.sys, "stdout", stdout), patch.object(
            run_test_shard.sys, "stderr", stderr
        ), patch.object(run_test_shard.os, "_exit", hard_exit):
            with self.assertRaisesRegex(RuntimeError, "hard exit intercepted"):
                finish_result(result, hard_exit_on_success=True)

        self.assertEqual(
            [call.stdout_flush(), call.stderr_flush(), call.hard_exit(0)],
            events.mock_calls,
        )

    def test_normal_success_and_failure_return_without_hard_exit(self) -> None:
        result = Mock()
        with patch.object(run_test_shard.os, "_exit") as hard_exit:
            result.wasSuccessful.return_value = True
            self.assertEqual(0, finish_result(result, hard_exit_on_success=False))
            result.wasSuccessful.return_value = False
            self.assertEqual(1, finish_result(result, hard_exit_on_success=True))
        hard_exit.assert_not_called()


class TestRegressionRunner(unittest.TestCase):
    @patch("test.ci.run_test_regressions.regression_modules", return_value=())
    def test_empty_regression_inventory_is_rejected(self, _modules) -> None:
        with self.assertRaisesRegex(
            ValueError, "no regression test modules are marked"
        ):
            build_regression_suite()

    @patch("test.ci.run_test_regressions.unittest.defaultTestLoader.loadTestsFromName")
    @patch(
        "test.ci.run_test_regressions.regression_modules",
        return_value=("test.first", "test.second"),
    )
    def test_suite_loads_only_ast_derived_modules(self, _modules, load_tests) -> None:
        load_tests.side_effect = lambda module: unittest.FunctionTestCase(
            lambda: None, description=module
        )

        suite = build_regression_suite()

        self.assertEqual(2, suite.countTestCases())
        self.assertEqual(
            [call("test.first"), call("test.second")], load_tests.call_args_list
        )

    def test_failure_and_normal_success_return_without_hard_exit(self) -> None:
        result = Mock()
        with patch.object(run_test_regressions.os, "_exit") as hard_exit:
            result.wasSuccessful.return_value = True
            self.assertEqual(
                0,
                finish_regression_result(
                    result, hard_exit_on_success=False
                ),
            )
            result.wasSuccessful.return_value = False
            self.assertEqual(
                1,
                finish_regression_result(
                    result, hard_exit_on_success=True
                ),
            )
        hard_exit.assert_not_called()


class TestWorkflowContract(unittest.TestCase):
    def test_paths_exist(self) -> None:
        self.assertTrue(WORKFLOW_PATH.is_file())
        self.assertTrue(TESTING_DOC_PATH.is_file())
        self.assertTrue(NOTIFICATION_DOC_PATH.is_file())
        self.assertTrue(PR_TEMPLATE_PATH.is_file())

    def test_domain_export_propagates_contract_command_failures(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = named_step_section(
            workflow, "test-contract", "Export validated test domains"
        )
        self.assertIn(
            "run: |\n"
            "          domains=$(python -m test.ci.check_test_contract --format domain-json)\n"
            "          echo \"domains=$domains\" >> \"$GITHUB_OUTPUT\"",
            step,
        )
        self.assertNotIn(
            'run: echo "domains=$(python -m test.ci.check_test_contract', step
        )

    def test_triggers_permissions_and_concurrency_are_bounded(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("types: [opened, synchronize]", workflow)
        self.assertIn("push:\n    branches: [main]", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertNotIn("reopened", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("cancel-in-progress: true", workflow)
        self.assertNotIn("contents: write", workflow)

    def test_hosted_matrix_has_static_platforms_and_dynamic_domains(self) -> None:
        section = job_section(
            WORKFLOW_PATH.read_text(encoding="utf-8"), "test-shards"
        )
        self.assertIn("needs: test-contract", section)
        self.assertIn("fail-fast: false", section)
        for platform_id, runner, python_version, machine in HOSTED_PLATFORMS:
            with self.subTest(platform=platform_id):
                self.assertIn(f"id: {platform_id}", section)
                self.assertIn(f"os: {runner}", section)
                self.assertIn(f'python-version: "{python_version}"', section)
                self.assertIn(f"machine: {machine}", section)
        self.assertEqual(
            DOMAIN_MATRIX_EXPRESSION,
            matrix_axis_expression(
                WORKFLOW_PATH.read_text(encoding="utf-8"), "test-shards", "domain"
            ),
        )
        self.assertIn("uv sync --frozen --group dev", section)
        self.assertIn("--expected-machine ${{ matrix.platform.machine }}", section)

    def test_xdg_runner_context_is_step_scoped(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertEqual([], xdg_context_contract_errors(workflow))

        arm_marker = "  linux-arm-shards:"
        prefix, arm_and_after = workflow.split(arm_marker, 1)
        job_level_runner = prefix + arm_marker + arm_and_after.replace(
            '      LIBGL_ALWAYS_SOFTWARE: "1"\n',
            '      LIBGL_ALWAYS_SOFTWARE: "1"\n'
            "      BROKEN: ${{ runner.temp }}/broken\n",
            1,
        )
        self.assertIn(
            "linux-arm-shards job env uses runner context",
            xdg_context_contract_errors(job_level_runner),
        )

        for job_id, occurrence in (
            ("test-shards", 1),
            ("existing-bug-regressions", 2),
        ):
            with self.subTest(job=job_id):
                before, separator, after = workflow.partition(
                    "          XDG_CACHE_HOME: "
                    "${{ runner.temp }}/xjtu-test-cache\n"
                )
                if occurrence == 2:
                    second_before, separator, after = after.partition(
                        "          XDG_CACHE_HOME: "
                        "${{ runner.temp }}/xjtu-test-cache\n"
                    )
                    before += (
                        "          XDG_CACHE_HOME: "
                        "${{ runner.temp }}/xjtu-test-cache\n" + second_before
                    )
                self.assertTrue(separator)
                missing_step_xdg = before + after
                self.assertIn(
                    f"{job_id} test step has unexpected "
                    "XDG_CACHE_HOME: ${{ runner.temp }}/xjtu-test-cache",
                    xdg_context_contract_errors(missing_step_xdg),
                )

        xdg_in_run_script = workflow.replace(
            "        run: uv run --frozen python -m test.ci.run_test_shard",
            "        run: |\n"
            "          # XDG_CACHE_HOME: ${{ runner.temp }}/xjtu-test-cache\n"
            "          uv run --frozen python -m test.ci.run_test_shard",
            1,
        ).replace(
            "          XDG_CACHE_HOME: ${{ runner.temp }}/xjtu-test-cache\n",
            "",
            1,
        )
        self.assertIn(
            "test-shards test step has unexpected "
            "XDG_CACHE_HOME: ${{ runner.temp }}/xjtu-test-cache",
            xdg_context_contract_errors(xdg_in_run_script),
        )

    def test_matrix_members_and_job_names_are_exact(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertEqual([], matrix_contract_errors(workflow))

    def test_matrix_contract_rejects_member_and_job_mutations(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        extra_platform = workflow.replace(
            f"        domain: {DOMAIN_MATRIX_EXPRESSION}\n",
            "          - id: linux-extra-py312\n"
            "            os: ubuntu-22.04\n"
            '            python-version: "3.12"\n'
            "            machine: x86_64\n"
            f"        domain: {DOMAIN_MATRIX_EXPRESSION}\n",
            1,
        )
        missing_hosted_domain = workflow.replace(
            f"        domain: {DOMAIN_MATRIX_EXPRESSION}\n",
            "        domain: []\n",
            1,
        )
        arm_marker = "  linux-arm-shards:"
        prefix, arm_section = workflow.split(arm_marker, 1)
        broken_arm_domain = prefix + arm_marker + arm_section.replace(
            f"        domain: {DOMAIN_MATRIX_EXPRESSION}\n",
            "        domain: ${{ fromJSON(needs.other.outputs.domains) }}\n",
            1,
        )
        self.assertEqual(
            "${{ fromJSON(needs.other.outputs.domains) }}",
            matrix_axis_expression(
                broken_arm_domain, "linux-arm-shards", "domain"
            ),
        )
        extra_job = workflow.replace(
            "  ci-gate:\n",
            "  unexpected-job:\n"
            "    name: Unexpected\n"
            "    runs-on: ubuntu-latest\n"
            "    steps: []\n\n"
            "  ci-gate:\n",
            1,
        )
        for label, mutation in (
            ("extra-platform", extra_platform),
            ("missing-hosted-domain", missing_hosted_domain),
            ("broken-arm-domain", broken_arm_domain),
            ("extra-job", extra_job),
        ):
            with self.subTest(mutation=label):
                self.assertTrue(matrix_contract_errors(mutation))

    def test_arm_matrix_has_dynamic_domains_and_complete_qt_runtime(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        section = job_section(workflow, "linux-arm-shards")
        self.assertIn("needs: test-contract", section)
        self.assertIn("arch: aarch64", section)
        self.assertIn("distro: ubuntu22.04", section)
        self.assertIn('test "$(uname -m)" = "aarch64"', section)
        self.assertIn("XDG_STATE_HOME: /tmp/xjtu-test-state", section)
        self.assertIn("XDG_CONFIG_HOME: /tmp/xjtu-test-config", section)
        self.assertIn("XDG_DATA_HOME: /tmp/xjtu-test-data", section)
        self.assertIn("XDG_CACHE_HOME: /tmp/xjtu-test-cache", section)
        self.assertIn("--system-site-packages", section)
        self.assertIn("uv sync --frozen --group dev", section)
        self.assertNotIn("rm -f uv.lock", section)
        self.assertEqual(
            DOMAIN_MATRIX_EXPRESSION,
            matrix_axis_expression(
                WORKFLOW_PATH.read_text(encoding="utf-8"),
                "linux-arm-shards",
                "domain",
            ),
        )
        for import_name in ARM_IMPORTS:
            self.assertIn(f"--require-import {import_name}", section)
        for pin in ARM_PINS:
            self.assertIn(pin, section)
        self.assertIn(
            'if [ "${{ matrix.domain.id }}" = "qt-ui" ]; then', section
        )
        self.assertIn('hard_exit_arg="--hard-exit-on-success"', section)
        self.assertEqual(1, workflow.count("--hard-exit-on-success"))
        self.assertNotIn(
            "--hard-exit-on-success", job_section(workflow, "test-shards")
        )
        self.assertEqual([], arm_hard_exit_contract_errors(workflow))

    def test_arm_hard_exit_scope_mutations_are_rejected(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        wrong_domain = workflow.replace(
            'if [ "${{ matrix.domain.id }}" = "qt-ui" ]; then',
            'if [ "${{ matrix.domain.id }}" = "ai" ]; then',
        )
        duplicate = workflow.replace(
            "uv run --frozen python -m test.ci.run_test_shard",
            "uv run --frozen python -m test.ci.run_test_shard --hard-exit-on-success",
            1,
        )
        self.assertIn(
            "Qt UI condition is missing", arm_hard_exit_contract_errors(wrong_domain)
        )
        self.assertIn(
            "unexpected hard-exit option count",
            arm_hard_exit_contract_errors(duplicate),
        )

    def test_regression_job_uses_the_dynamic_runner(self) -> None:
        section = job_section(
            WORKFLOW_PATH.read_text(encoding="utf-8"),
            "existing-bug-regressions",
        )
        self.assertIn("needs: test-contract", section)
        self.assertEqual(
            1,
            section.count("python -m test.ci.run_test_regressions"),
        )
        for module in regression_modules():
            self.assertNotIn(module, section)

    def test_gate_needs_every_required_job(self) -> None:
        section = job_section(
            WORKFLOW_PATH.read_text(encoding="utf-8"), "ci-gate"
        )
        self.assertIn("if: always()", section)
        self.assertIn(
            "needs: [test-contract, test-shards, linux-arm-shards, existing-bug-regressions]",
            section,
        )
        for variable in ("CONTRACT", "HOSTED_SHARDS", "ARM_SHARDS", "REGRESSIONS"):
            self.assertIn(variable, section)

    def test_gate_accepts_only_all_success(self) -> None:
        script = gate_script(WORKFLOW_PATH.read_text(encoding="utf-8"))
        self.assertTrue(script)
        variables = ("CONTRACT", "HOSTED_SHARDS", "ARM_SHARDS", "REGRESSIONS")
        success_env = os.environ | {variable: "success" for variable in variables}
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            env=success_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        for bad_value in ("failure", "cancelled", "skipped"):
            for variable in variables:
                with self.subTest(variable=variable, value=bad_value):
                    env = success_env | {variable: bad_value}
                    failed = subprocess.run(
                        ["bash", "-euo", "pipefail", "-c", script],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(0, failed.returncode)
                    self.assertIn(bad_value, failed.stdout)

    def test_documentation_matches_matrix_and_rerun_policy(self) -> None:
        documentation = TESTING_DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("--domain <domain-id>", documentation)
        self.assertIn("python -m unittest <module> -v", documentation)
        for shard in SHARDS:
            for module in shard.modules:
                self.assertNotIn(module, documentation)
        self.assertIn("稳定的域 ID、Actions 显示名和矩阵顺序", documentation)
        self.assertIn("--format markdown", documentation)
        for platform_id, runner, _python_version, _machine in HOSTED_PLATFORMS:
            self.assertIn(platform_id, documentation)
            self.assertIn(runner.replace("windows-latest", "Windows latest").replace("macos-latest", "macOS latest").replace("macos-15-intel", "macOS 15 Intel").replace("ubuntu-22.04", "Ubuntu 22.04"), documentation)
        for phrase in (
            "uv run --frozen local_test.py",
            "test/ci/shards.py",
            "TEST_DOMAIN = \"qt-ui\"",
            "TEST_REGRESSION = True",
            "python -m test.ci.run_test_regressions",
            "check_test_contract --format markdown",
            "不需要修改共享分片清单、workflow 命令",
            "各自新增测试时只修改自己的测试文件",
            "新增域只需修改唯一的稳定域定义",
            "在途分支 rebase 后",
            "合同检查器通过 AST 扫描",
            "test/ci/**",
            "test/feature/ci/test_case.py",
            "每个产品测试模块恰好属于一个主测试域",
            "有意重跑",
            "本地用例数和耗时不能代替",
            "linux-arm64-qemu-py310",
            "<domain display name> (<platform id>, Python <version>)",
            "各平台 × 当前域定义的分片",
            "矩阵与 check 数会自动随之变化",
            "QEMU 结果是兼容",
            "synchronize",
            "workflow_dispatch",
            "required status check",
            "PR 测试成功不能替代构建成功",
        ):
            self.assertIn(phrase, documentation)

    def test_notification_documentation_uses_dynamic_regression_inventory(self) -> None:
        documentation = NOTIFICATION_DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("python -m test.ci.run_test_regressions", documentation)
        self.assertIn("TEST_REGRESSION = True", documentation)
        for module in product_test_modules():
            self.assertNotIn(module, documentation)

    def test_pr_template_requests_test_evidence_without_credentials(self) -> None:
        template = PR_TEMPLATE_PATH.read_text(encoding="utf-8")
        for phrase in (
            "PR Tests / CI Gate",
            "无法运行的测试或环境",
            "其它凭据",
            "cookie",
        ):
            self.assertIn(phrase, template)


if __name__ == "__main__":
    unittest.main()
