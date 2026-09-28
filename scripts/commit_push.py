#!/usr/bin/env python3
"""Commit on main, synchronize without force, and push after agent validation."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from mentee_setup import ROOT, read_existing_token
from secret_guard import contains_secret, is_secret_path

EXPECTED_REMOTE = "https://github.com/donggwonY/PublicData_AI_Agent.git"


class GitError(Exception):
    pass


def git(root: Path, *args: str, auth: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = os.environ.get("GH_TOKEN") or read_existing_token(root / ".env")
    command = ["git"]
    if auth and token:
        env.update({
            "GH_TOKEN": token,
            "MENTEE_GIT_AUTH": "1",
            "GIT_ASKPASS": str(root / "scripts" / "git_askpass.py"),
        })
        command += ["-c", "credential.helper="]
    result = subprocess.run(command + list(args), cwd=root, env=env, capture_output=True, text=True)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        last_line = detail[-1] if detail else "상세 오류 없음"
        if token:
            last_line = last_line.replace(token, "[숨김]")
        raise GitError(f"git {args[0]} 실패: {last_line}")
    return result


def staged_blob(root: Path, name: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f":{name}"], cwd=root, capture_output=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def verify_repository(root: Path, expected_remote: str) -> None:
    remote = git(root, "config", "--get", "remote.origin.url").stdout.strip()
    if remote not in {expected_remote, expected_remote.removesuffix(".git")}:
        raise ValueError("origin 주소가 이 프로젝트의 원격 저장소와 다릅니다. 토큰 포함 URL도 사용할 수 없습니다.")
    branch = git(root, "branch", "--show-current").stdout.strip()
    if branch != "main":
        raise ValueError(f"현재 브랜치는 {branch or '분리된 HEAD'}입니다. main에서만 게시할 수 있습니다.")


def rebase_in_progress(root: Path) -> bool:
    for name in ("rebase-merge", "rebase-apply"):
        path = Path(git(root, "rev-parse", "--git-path", name).stdout.strip())
        if (root / path).exists() if not path.is_absolute() else path.exists():
            return True
    return False


def ensure_clean(root: Path) -> None:
    if git(root, "status", "--porcelain=v1").stdout.strip():
        raise ValueError("동기화 전에 작업 파일을 먼저 커밋하거나 충돌 해결을 완료하세요.")


def is_ancestor(root: Path, older: str, newer: str) -> bool:
    result = git(root, "merge-base", "--is-ancestor", older, newer, check=False)
    if result.returncode not in (0, 1):
        raise GitError("Git 이력 비교에 실패했습니다.")
    return result.returncode == 0


def prepare(message: str, root: Path = ROOT, expected_remote: str = EXPECTED_REMOTE) -> None:
    verify_repository(root, expected_remote)
    if rebase_in_progress(root):
        raise ValueError("리베이스 충돌 해결 중입니다. 먼저 충돌을 마무리하세요.")
    if not message.strip() or "\n" in message:
        raise ValueError("한 줄짜리 커밋 설명이 필요합니다.")

    git(root, "add", "-A")
    names = git(root, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
    token = os.environ.get("GH_TOKEN") or read_existing_token(root / ".env")
    for name in filter(None, names):
        if is_secret_path(name):
            git(root, "restore", "--staged", "--", name)
            raise ValueError(f"비밀 파일이 포함되어 커밋을 중단했습니다: {name}")
        blob = staged_blob(root, name)
        if blob is not None and contains_secret(blob, token):
            git(root, "restore", "--staged", "--", name)
            raise ValueError(f"비밀값으로 보이는 내용이 있어 커밋을 중단했습니다: {name}")
    git(root, "diff", "--cached", "--check")
    if not any(names):
        print("새로 커밋할 변경이 없습니다. 원격 main 동기화를 계속할 수 있습니다.")
        return
    git(root, "commit", "-m", message.strip())
    print("커밋 완료. 다음 단계: 원격 main 동기화")


def sync(root: Path = ROOT, expected_remote: str = EXPECTED_REMOTE) -> int:
    verify_repository(root, expected_remote)
    if rebase_in_progress(root):
        raise ValueError("리베이스 충돌 해결 중입니다. 충돌 파일을 수정하고 rebase --continue 하세요.")
    ensure_clean(root)
    git(root, "fetch", "origin", "main", auth=True)
    local = git(root, "rev-parse", "HEAD").stdout.strip()
    remote = git(root, "rev-parse", "origin/main").stdout.strip()
    if is_ancestor(root, local, remote):
        if local != remote:
            git(root, "merge", "--ff-only", "origin/main")
            print("원격 main을 fast-forward로 반영했습니다. 검증 후 게시하세요.")
        else:
            print("원격 main과 같은 상태입니다.")
        return 0
    if is_ancestor(root, remote, local):
        print("로컬 커밋이 원격 main 위에 있습니다. 검증 후 게시하세요.")
        return 0

    result = git(root, "rebase", "origin/main", check=False)
    if result.returncode:
        if rebase_in_progress(root):
            print("충돌이 발생했습니다. 에이전트가 충돌 내용을 통합하고 rebase --continue 해야 합니다.", file=sys.stderr)
            return 3
        raise GitError("리베이스에 실패했습니다. Git 상태를 확인하세요.")
    print("로컬 커밋을 최신 main 위에 반영했습니다. 다시 검증한 뒤 게시하세요.")
    return 0


def push(root: Path = ROOT, expected_remote: str = EXPECTED_REMOTE) -> int:
    verify_repository(root, expected_remote)
    if rebase_in_progress(root):
        raise ValueError("충돌 해결 중에는 푸시할 수 없습니다.")
    ensure_clean(root)
    hook_path = git(root, "config", "--local", "--get", "core.hooksPath", check=False).stdout.strip()
    if hook_path != ".githooks" or not (root / ".githooks" / "pre-push").is_file():
        raise ValueError("푸시 전 비밀값 검사 훅이 없습니다. 먼저 mentee-init 설정을 완료하세요.")

    git(root, "fetch", "origin", "main", auth=True)
    local = git(root, "rev-parse", "HEAD").stdout.strip()
    remote = git(root, "rev-parse", "origin/main").stdout.strip()
    if not is_ancestor(root, remote, local):
        print("원격 main이 갱신되었습니다. 다시 동기화하고 검증하세요.", file=sys.stderr)
        return 4
    if local == remote:
        print("원격 main이 이미 최신 상태입니다.")
        return 0

    result = git(root, "push", "origin", "main:main", auth=True, check=False)
    if result.returncode:
        git(root, "fetch", "origin", "main", auth=True)
        if not is_ancestor(root, "origin/main", "HEAD"):
            print("푸시 사이에 원격 main이 갱신되었습니다. 다시 동기화하고 검증하세요.", file=sys.stderr)
            return 4
        raise GitError("푸시에 실패했습니다. 원격 저장소 권한 또는 브랜치 규칙을 확인하세요.")
    print("main 커밋·푸시 완료")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="멘티의 변경을 main에 안전하게 반영")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="현재 브랜치와 변경 상태 확인")
    prepare_parser = actions.add_parser("prepare", help="변경 검사 후 main에 커밋")
    prepare_parser.add_argument("--message", required=True)
    actions.add_parser("sync", help="원격 main을 fast-forward 또는 rebase로 반영")
    actions.add_parser("push", help="검증을 마친 main을 force 없이 푸시")
    args = parser.parse_args()
    try:
        if args.action == "status":
            verify_repository(ROOT, EXPECTED_REMOTE)
            print(git(ROOT, "status", "--short", "--branch").stdout.strip())
            return 0
        if args.action == "prepare":
            prepare(args.message)
            return 0
        if args.action == "sync":
            return sync()
        return push()
    except (GitError, OSError, ValueError) as exc:
        print(f"commit-push 중단: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
