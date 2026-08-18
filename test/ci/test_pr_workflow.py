"""验证 PR 测试分片覆盖和 GitHub Actions 合同。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

from test.ci.preflight import canonical_machine, verify_environment
from test.ci.shards import SHARDS, Shard


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPOSITORY_ROOT / "test"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "pr-tests.yml"
LOCK_PATH = REPOSITORY_ROOT / "uv.lock"

HOSTED_PLATFORMS = (
    ("ubuntu-22.04", "3.10", "x86_64"),
    ("ubuntu-22.04", "3.13", "x86_64"),
    ("windows-latest", "3.12", "x86_64"),
    ("macos-latest", "3.12", "arm64"),
    ("macos-15-intel", "3.12", "x86_64"),
)

LINUX_RUNTIME_PACKAGES = (
    "libegl1",
    "libgl1",
    "libpulse-mainloop-glib0",
    "libxkbcommon-x11-0",
    "libxcb-cursor0",
    "libxcb-xinerama0",
)

ARM_APT_PACKAGES = (
    "curl",
    "build-essential",
    "python3-dev",
    "python3-venv",
    "python3-pyqt5",
    "python3-pyqt5.qtsvg",
    "python3-pyqt5.qtx11extras",
)

ARM_SUPPLEMENTAL_PINS = {
    "pyqt-fluent-widgets": "1.8.7",
    "pyqt5-frameless-window": "0.7.5",
    "darkdetect": "0.8.0",
    "xcffib": "1.12.0",
}

ARM_IMPORTS = (
    "PyQt5",
    "PyQt5.QtSvg",
    "PyQt5.QtX11Extras",
    "qfluentwidgets",
    "qframelesswindow",
    "xcffib",
)


def _module_path(path: Path) -> str:
    return ".".join(path.relative_to(REPOSITORY_ROOT).with_suffix("").parts)


def _product_modules() -> set[str]:
    return {
        _module_path(path)
        for path in TEST_ROOT.rglob("*.py")
        if path.name != "__init__.py" and "ci" not in path.relative_to(TEST_ROOT).parts
    }


def _owned_modules(shards: tuple[Shard, ...]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for shard in shards:
        for directory in shard.discovery_dirs:
            for path in sorted((REPOSITORY_ROOT / directory).glob("*.py")):
                if path.name == "__init__.py":
                    continue
                owners.setdefault(_module_path(path), []).append(shard.id)
        for module in shard.explicit_modules:
            owners.setdefault(module, []).append(shard.id)
    return owners


def inventory_problems(shards: tuple[Shard, ...]) -> tuple[set[str], dict[str, list[str]]]:
    """返回没有 owner 和拥有多个 owner 的产品测试模块。"""

    product_modules = _product_modules()
    owners = _owned_modules(shards)
    missing = product_modules - set(owners)
    duplicates = {
        module: shard_ids
        for module, shard_ids in owners.items()
        if module in product_modules and len(shard_ids) != 1
    }
    return missing, duplicates


def _locked_package_versions(lock_text: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for block in re.split(r"(?m)^\[\[package\]\]\s*$", lock_text)[1:]:
        name = re.search(r'(?m)^name = "([^"]+)"$', block)
        version = re.search(r'(?m)^version = "([^"]+)"$', block)
        if name and version:
            versions[name.group(1)] = version.group(1)
    return versions


def _arm_job(workflow: str) -> str:
    marker = "  linux-arm-shards:"
    if marker not in workflow:
        return ""
    section = workflow.split(marker, 1)[1]
    next_job = re.search(r"(?m)^  [a-z0-9-]+:\s*$", section)
    return section[: next_job.start()] if next_job else section


def arm_pin_problems(workflow: str) -> set[str]:
    """返回锁文件、批准版本或 ARM 安装命令不一致的包。"""

    lock_versions = _locked_package_versions(LOCK_PATH.read_text(encoding="utf-8"))
    arm_job = _arm_job(workflow)
    problems = set()
    for package, expected_version in ARM_SUPPLEMENTAL_PINS.items():
        if lock_versions.get(package) != expected_version:
            problems.add(package)
        if f"{package}=={expected_version}" not in arm_job:
            problems.add(package)
    return problems


class TestShardContract(unittest.TestCase):
    def test_every_product_test_module_has_exactly_one_owner(self) -> None:
        missing, duplicates = inventory_problems(SHARDS)
        self.assertEqual(set(), missing)
        self.assertEqual({}, duplicates)

    def test_missing_assignment_is_rejected(self) -> None:
        missing, duplicates = inventory_problems(SHARDS[:-1])
        self.assertTrue(missing)
        self.assertFalse(duplicates)

    def test_duplicate_assignment_is_rejected(self) -> None:
        missing, duplicates = inventory_problems(SHARDS + (SHARDS[0],))
        self.assertFalse(missing)
        self.assertTrue(duplicates)

    def test_shard_identifiers_and_sources_are_valid(self) -> None:
        self.assertEqual(len(SHARDS), len({shard.id for shard in SHARDS}))
        self.assertEqual(len(SHARDS), len({shard.name for shard in SHARDS}))

        for shard in SHARDS:
            with self.subTest(shard=shard.id):
                self.assertRegex(shard.id, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                for directory in shard.discovery_dirs:
                    self.assertTrue((REPOSITORY_ROOT / directory).is_dir(), directory)
                for module in shard.explicit_modules:
                    self.assertTrue(
                        (REPOSITORY_ROOT / Path(*module.split("."))).with_suffix(".py").is_file(),
                        module,
                    )


class TestPreflight(unittest.TestCase):
    def test_machine_aliases_are_canonical(self) -> None:
        self.assertEqual("x86_64", canonical_machine("AMD64"))
        self.assertEqual("x86_64", canonical_machine("x86_64"))
        self.assertEqual("arm64", canonical_machine("aarch64"))
        self.assertEqual("arm64", canonical_machine("arm64"))

    @patch("test.ci.preflight.platform.machine", return_value="AMD64")
    @patch("test.ci.preflight.importlib.import_module")
    def test_environment_verifies_machine_and_imports(self, import_module, _machine) -> None:
        import_module.reset_mock()
        verify_environment("x86_64", ("first.module", "second.module"))
        self.assertEqual(
            [unittest.mock.call("first.module"), unittest.mock.call("second.module")],
            import_module.call_args_list,
        )

    @patch("test.ci.preflight.platform.machine", return_value="aarch64")
    def test_environment_rejects_wrong_machine(self, _machine) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected='x86_64'.*actual='aarch64'"):
            verify_environment("x86_64")

    @patch(
        "test.ci.preflight.importlib.import_module",
        side_effect=ModuleNotFoundError("missing module"),
    )
    @patch("test.ci.preflight.platform.machine", return_value="aarch64")
    def test_environment_propagates_import_failure(self, _machine, _import_module) -> None:
        with self.assertRaisesRegex(ModuleNotFoundError, "missing module"):
            verify_environment("arm64", ("missing.module",))


class TestWorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_trigger_and_permission_contract(self) -> None:
        self.assertRegex(self.workflow, r"types:\s*\[opened, synchronize\]")
        self.assertNotIn("reopened", self.workflow)
        self.assertNotIn("workflow_dispatch", self.workflow)
        self.assertRegex(self.workflow, r"permissions:\s*\n\s+contents: read")

    def test_hosted_matrix_contains_all_shards_and_platforms(self) -> None:
        self.assertIn("test-shards:", self.workflow)
        self.assertRegex(self.workflow, r"test-shards:\s+name:.*\s+needs: test-contract")
        self.assertRegex(self.workflow, r"fail-fast:\s*false")

        for shard in SHARDS:
            with self.subTest(shard=shard.id):
                self.assertEqual(2, self.workflow.count(f"id: {shard.id}"))
                self.assertEqual(2, self.workflow.count(f"name: {shard.name}"))

        for operating_system, python_version, machine in HOSTED_PLATFORMS:
            with self.subTest(os=operating_system, python=python_version, machine=machine):
                platform_entry = re.compile(
                    rf"- os: {re.escape(operating_system)}\s+"
                    rf"python-version: [\"']{re.escape(python_version)}[\"']\s+"
                    rf"machine: {re.escape(machine)}"
                )
                self.assertEqual(1, len(platform_entry.findall(self.workflow)))

        self.assertIn(
            "python -m test.ci.preflight --expected-machine ${{ matrix.platform.machine }}",
            self.workflow,
        )
        self.assertIn(
            "python -m test.ci.run_shard ${{ matrix.shard.id }}",
            self.workflow,
        )

    def test_linux_arm_job_contract(self) -> None:
        arm_job = _arm_job(self.workflow)
        self.assertTrue(arm_job, "linux-arm-shards job is missing")
        self.assertIn("needs: test-contract", arm_job)
        self.assertIn("runs-on: ubuntu-22.04", arm_job)
        self.assertIn("docker/setup-qemu-action@v3", arm_job)
        self.assertIn("uraimo/run-on-arch-action@v2", arm_job)
        self.assertIn("arch: aarch64", arm_job)
        self.assertIn("distro: ubuntu22.04", arm_job)
        self.assertIn("https://astral.sh/uv/0.12.3/install.sh", arm_job)
        self.assertIn("uv venv --python python3 --system-site-packages .venv", arm_job)
        self.assertIn("uv sync --frozen --group dev", arm_job)
        self.assertIn("uv pip install --python .venv/bin/python --no-deps", arm_job)
        self.assertNotIn("rm -f uv.lock", arm_job)
        self.assertNotIn("uv lock", arm_job)
        self.assertNotIn("uv run", arm_job)

        for package in ARM_APT_PACKAGES:
            with self.subTest(package=package):
                self.assertIn(package, arm_job)
        for module in ARM_IMPORTS:
            with self.subTest(module=module):
                self.assertIn(f"--require-import {module}", arm_job)

        self.assertEqual(set(), arm_pin_problems(self.workflow))
        self.assertIn(
            ".venv/bin/python -m test.ci.run_shard ${{ matrix.shard.id }}",
            arm_job,
        )

    def test_wrong_arm_pin_is_rejected(self) -> None:
        mutated = self.workflow.replace("darkdetect==0.8.0", "darkdetect==0.8.1")
        self.assertIn("darkdetect", arm_pin_problems(mutated))

    def test_runtime_and_dependency_contract(self) -> None:
        self.assertIn('version: "0.12.3"', self.workflow)
        self.assertIn("uv sync --frozen --group dev", self.workflow)
        self.assertGreaterEqual(self.workflow.count("PYTHONUTF8: \"1\""), 3)
        self.assertGreaterEqual(self.workflow.count("QT_QPA_PLATFORM: offscreen"), 4)
        self.assertGreaterEqual(self.workflow.count("QT_OPENGL: software"), 4)
        for package in LINUX_RUNTIME_PACKAGES:
            with self.subTest(package=package):
                self.assertIn(package, self.workflow)

        self.assertRegex(
            self.workflow,
            r"existing-bug-regressions:\s+name: Existing bug regressions\s+needs: test-contract",
        )
        self.assertIn("LIBGL_ALWAYS_SOFTWARE: \"1\"", self.workflow)
        self.assertIn("Run historical bug regressions", self.workflow)
        self.assertIn("Run Issue 53 crawler challenge regression", self.workflow)

    def test_gate_aggregates_every_required_job(self) -> None:
        self.assertRegex(
            self.workflow,
            r"ci-gate:\s+name: CI Gate\s+if: always\(\)\s+needs: "
            r"\[test-contract, test-shards, linux-arm-shards, existing-bug-regressions\]",
        )
        for job in (
            "test-contract",
            "test-shards",
            "linux-arm-shards",
            "existing-bug-regressions",
        ):
            with self.subTest(job=job):
                self.assertIn(f"${{{{ needs.{job}.result }}}}", self.workflow)


if __name__ == "__main__":
    unittest.main()
