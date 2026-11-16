"""Regression tests for the AUR publish workflow.

A release used to start two publishes at once. Both pushed, and AUR ended
with HEAD and refs/heads/master on different commits. The next clone stopped
in detached HEAD, so the deploy action's `git push master` failed with
"src refspec master does not match any".
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "update_aur.yml"
ATTACH_SCRIPT = REPOSITORY_ROOT / "scripts" / "aur_attach_master.sh"


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class TestUpdateAurWorkflow(unittest.TestCase):
    def test_release_event_does_not_publish_twice(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        types_line = next(
            line
            for line in workflow.splitlines()
            if line.strip().startswith("types:") and "released" in line
        )

        self.assertIn("released", types_line)
        self.assertIn("edited", types_line)
        self.assertNotIn("published", types_line)
        self.assertIn("group: update-aur", workflow)
        self.assertEqual(3, workflow.count("scripts/aur_attach_master.sh"))

    def test_attach_script_moves_detached_clone_onto_master(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root / "remote.git"
            source = root / "source"
            clone = root / "clone"
            subprocess.run(
                ["git", "init", "--bare", "-b", "master", str(remote)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "init", "-b", "master", str(source)],
                check=True,
                capture_output=True,
                text=True,
            )
            git(source, "config", "user.email", "test@example.com")
            git(source, "config", "user.name", "Test")
            (source / "PKGBUILD").write_text("pkgver=1.4.0\n", encoding="utf-8")
            (source / ".SRCINFO").write_text("pkgver = 1.4.0\n", encoding="utf-8")
            git(source, "add", "PKGBUILD", ".SRCINFO")
            git(source, "commit", "-m", "base")
            git(source, "remote", "add", "origin", str(remote))
            git(source, "push", "origin", "master")
            git(source, "commit", "--allow-empty", "-m", "sibling")
            sibling = git(source, "rev-parse", "HEAD")
            git(source, "push", "origin", f"{sibling}:refs/heads/side")
            (remote / "HEAD").write_text(f"{sibling}\n", encoding="utf-8")
            git(remote, "update-ref", "-d", "refs/heads/side")

            subprocess.run(
                ["git", "clone", str(remote), str(clone)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("ref:", (clone / ".git" / "HEAD").read_text(encoding="utf-8"))
            with self.assertRaises(subprocess.CalledProcessError):
                git(clone, "show-ref", "--verify", "--quiet", "refs/heads/master")

            (clone / "PKGBUILD").write_text("pkgver=1.4.1\n", encoding="utf-8")
            (clone / ".SRCINFO").write_text("pkgver = 1.4.1\n", encoding="utf-8")
            subprocess.run(
                ["bash", str(ATTACH_SCRIPT)],
                cwd=clone,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual("master", git(clone, "branch", "--show-current"))
            self.assertEqual(git(clone, "rev-parse", "origin/master"), git(clone, "rev-parse", "HEAD"))
            self.assertNotEqual(sibling, git(clone, "rev-parse", "HEAD"))
            self.assertEqual("pkgver=1.4.1\n", (clone / "PKGBUILD").read_text(encoding="utf-8"))
            self.assertEqual(
                "pkgver = 1.4.1\n",
                (clone / ".SRCINFO").read_text(encoding="utf-8"),
            )
            git(clone, "show-ref", "--verify", "--quiet", "refs/heads/master")
