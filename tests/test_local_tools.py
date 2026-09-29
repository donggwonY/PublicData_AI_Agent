"""Local-only checks for the credential and Git publishing helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mentee_setup import read_existing_token, save_token  # noqa: E402
from link_skills import link_skills  # noqa: E402
from commit_push import prepare, push, sync  # noqa: E402
from pull_main import pull_main  # noqa: E402
from secret_guard import is_secret_path  # noqa: E402

SOURCE_ROOT = Path(__file__).resolve().parents[1]


class LocalToolsTest(unittest.TestCase):
    def test_agent_setup_can_start_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(SOURCE_ROOT / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(SOURCE_ROOT / "config", root / "config")
            shutil.copytree(SOURCE_ROOT / ".githooks", root / ".githooks")
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            request = {"name": "김선경", "email": "student@example.com"}
            result = subprocess.run(
                [sys.executable, "scripts/mentee_setup.py", "--json-stdin"],
                cwd=root, input=json.dumps(request), capture_output=True, text=True, check=True,
            )
            self.assertIn("GitHub 토큰 미설정", result.stdout)
            self.assertFalse((root / ".env").exists())
            profile = json.loads((root / ".mentee" / "profile.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["name"], "김선경")
            self.assertEqual(profile["track"], "data-ml-agent")
            self.assertEqual(profile["starter_task"], "A-01")

    def test_agent_setup_and_push_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            shutil.copytree(SOURCE_ROOT / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(SOURCE_ROOT / "config", root / "config")
            shutil.copytree(SOURCE_ROOT / ".githooks", root / ".githooks")
            shutil.copy2(SOURCE_ROOT / ".gitignore", root / ".gitignore")
            (root / "README.md").write_text("safe\n", encoding="utf-8")
            remote = Path(directory) / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

            def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
                return subprocess.run(["git", *args], cwd=root, check=check, capture_output=True, text=True)

            git("init", "-b", "main")
            git("remote", "add", "origin", str(remote))
            fake_token = "github_pat_" + "X" * 30
            request = {
                "name": "염동권", "email": "tester@example.com", "github_token": fake_token,
            }
            result = subprocess.run(
                [sys.executable, "scripts/mentee_setup.py", "--json-stdin"],
                cwd=root, input=json.dumps(request), capture_output=True, text=True, check=True,
            )
            self.assertNotIn(fake_token, result.stdout + result.stderr)
            self.assertEqual(git("config", "--local", "core.hooksPath").stdout.strip(), ".githooks")
            profile = json.loads((root / ".mentee" / "profile.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["name"], "염동권")
            self.assertEqual(profile["track"], "engineering")
            self.assertEqual(profile["starter_task"], "E-01")
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)

            git("add", "README.md", ".gitignore")
            git("commit", "-m", "safe")
            safe_sha = git("rev-parse", "HEAD").stdout.strip()
            git("push", "origin", "main")

            git("add", "-f", ".env")
            git("commit", "-m", "accidental secret")
            blocked = git("push", "origin", "main", check=False)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("비밀 파일", blocked.stderr)
            self.assertNotIn(fake_token, blocked.stderr)
            remote_sha = subprocess.run(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(remote_sha, safe_sha)

    def test_new_skills_share_one_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ".agents" / "skills" / "example"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: example\ndescription: Test\n---\nOne source.\n", encoding="utf-8")

            self.assertEqual(link_skills(root), ["example"])
            for client in (".codex", ".claude"):
                target = root / client / "skills" / "example"
                self.assertTrue(target.is_symlink())
                self.assertEqual(target.resolve(), source.resolve())
            self.assertEqual(link_skills(root), [])

    def test_token_is_private_and_other_env_lines_survive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("OTHER=value\n", encoding="utf-8")
            save_token(path, "test-token-not-real")
            self.assertEqual(read_existing_token(path), "test-token-not-real")
            self.assertIn("OTHER=value", path.read_text(encoding="utf-8"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_secret_paths_are_blocked(self) -> None:
        for name in (".env", "backend/.env.prod", ".mentee/profile.json", ".streamlit/secrets.toml"):
            self.assertTrue(is_secret_path(name), name)
        self.assertFalse(is_secret_path(".env.example"))

    def test_pull_main_fast_forward_and_preserve_local_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, seed, student = base / "remote.git", base / "seed", base / "student"

            def git(root: Path, *args: str) -> str:
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            seed.mkdir()
            git(seed, "init", "-b", "main")
            git(seed, "config", "user.name", "Seed")
            git(seed, "config", "user.email", "seed@example.com")
            (seed / "README.md").write_text("first\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "commit", "-m", "initial")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "origin", "main")
            subprocess.run(["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
            subprocess.run(["git", "clone", str(remote), str(student)], check=True, capture_output=True)
            git(student, "config", "user.name", "Student")
            git(student, "config", "user.email", "student@example.com")

            (seed / "README.md").write_text("second\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "commit", "-m", "remote update")
            git(seed, "push", "origin", "main")
            self.assertEqual(pull_main(student, str(remote)), "updated")
            self.assertEqual((student / "README.md").read_text(encoding="utf-8"), "second\n")
            self.assertEqual(pull_main(student, str(remote)), "current")

            (student / "local.txt").write_text("student\n", encoding="utf-8")
            git(student, "add", "local.txt")
            git(student, "commit", "-m", "local work")
            local_head = git(student, "rev-parse", "HEAD")
            self.assertEqual(pull_main(student, str(remote)), "ahead")

            (student / "README.md").write_text("uncommitted\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "작업 파일"):
                pull_main(student, str(remote))
            self.assertEqual((student / "README.md").read_text(encoding="utf-8"), "uncommitted\n")
            git(student, "restore", "README.md")

            (seed / "README.md").write_text("third\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "commit", "-m", "another remote update")
            git(seed, "push", "origin", "main")
            with self.assertRaisesRegex(ValueError, "fast-forward"):
                pull_main(student, str(remote))
            self.assertEqual(git(student, "rev-parse", "HEAD"), local_head)
            self.assertEqual((student / "local.txt").read_text(encoding="utf-8"), "student\n")

    def test_main_fast_forward_rebase_and_conflict_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote = base / "remote.git"
            seed, student, other = base / "seed", base / "student", base / "other"

            def git(root: Path, *args: str) -> str:
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            seed.mkdir()
            git(seed, "init", "-b", "main")
            git(seed, "config", "user.name", "Seed")
            git(seed, "config", "user.email", "seed@example.com")
            (seed / "README.md").write_text("first line\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "commit", "-m", "initial")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "origin", "main")
            subprocess.run(["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
            subprocess.run(["git", "clone", str(remote), str(student)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
            for root in (student, other):
                git(root, "config", "user.name", "Tester")
                git(root, "config", "user.email", "tester@example.com")

            (other / "README.md").write_text("remote first\n", encoding="utf-8")
            git(other, "add", "README.md")
            git(other, "commit", "-m", "remote first")
            git(other, "push", "origin", "main")
            self.assertEqual(sync(student, str(remote)), 0)
            self.assertEqual((student / "README.md").read_text(), "remote first\n")

            shutil.copytree(SOURCE_ROOT / "scripts", student / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(SOURCE_ROOT / ".githooks", student / ".githooks")
            shutil.copytree(SOURCE_ROOT / "config", student / "config")
            shutil.copy2(SOURCE_ROOT / ".gitignore", student / ".gitignore")
            git(student, "config", "core.hooksPath", ".githooks")
            save_token(student / ".env", "test-token-not-real")

            (student / "README.md").write_text("student version\n", encoding="utf-8")
            prepare("student change", student, str(remote))
            (other / "README.md").write_text("other version\n", encoding="utf-8")
            git(other, "add", "README.md")
            git(other, "commit", "-m", "other change")
            git(other, "push", "origin", "main")
            self.assertEqual(sync(student, str(remote)), 3)
            self.assertIn("<<<<<<<", (student / "README.md").read_text())

            (student / "README.md").write_text("student and other version\n", encoding="utf-8")
            git(student, "add", "README.md")
            subprocess.run(
                ["git", "rebase", "--continue"], cwd=student, check=True,
                capture_output=True, text=True, env={**os.environ, "GIT_EDITOR": "true"},
            )
            self.assertEqual(sync(student, str(remote)), 0)
            self.assertEqual(push(student, str(remote)), 0)
            self.assertEqual(
                subprocess.run(
                    ["git", "--git-dir", str(remote), "show", "main:README.md"],
                    check=True, capture_output=True, text=True,
                ).stdout,
                "student and other version\n",
            )

            (student / "student.txt").write_text("student\n", encoding="utf-8")
            prepare("second student change", student, str(remote))
            self.assertEqual(sync(student, str(remote)), 0)
            git(other, "pull", "--ff-only", "origin", "main")
            (other / "other.txt").write_text("other\n", encoding="utf-8")
            git(other, "add", "other.txt")
            git(other, "commit", "-m", "other during push")
            git(other, "push", "origin", "main")
            self.assertEqual(push(student, str(remote)), 4)
            self.assertEqual(sync(student, str(remote)), 0)
            self.assertEqual(push(student, str(remote)), 0)
            self.assertEqual(
                subprocess.run(
                    ["git", "--git-dir", str(remote), "show", "main:student.txt"],
                    check=True, capture_output=True, text=True,
                ).stdout,
                "student\n",
            )
            (student / "bad.txt").write_text("github_pat_" + "Z" * 30 + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "비밀값"):
                prepare("should not commit", student, str(remote))


if __name__ == "__main__":
    unittest.main()
