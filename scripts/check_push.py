#!/usr/bin/env python3
"""Reject pushes containing local credential files or recognizable tokens."""

from __future__ import annotations

import subprocess
import sys

from mentee_setup import ROOT, read_existing_token
from secret_guard import contains_secret, is_secret_path


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def check_range(local_sha: str, remote_sha: str) -> None:
    if set(local_sha) == {"0"}:  # deleted remote branch
        return
    rev_range = [f"{remote_sha}..{local_sha}"] if set(remote_sha) != {"0"} else [local_sha]
    commits = git_bytes("rev-list", *rev_range).decode("ascii").splitlines()
    current_token = read_existing_token(ROOT / ".env")

    for commit in commits:
        changed = git_bytes("diff-tree", "--root", "-m", "--no-commit-id", "--name-only", "-r", "-z", commit)
        for raw_path in set(changed.split(b"\0")) - {b""}:
            path = raw_path.decode("utf-8", errors="surrogateescape")
            if is_secret_path(path):
                raise ValueError(f"비밀 파일이 커밋 기록에 포함되어 푸시를 중단했습니다: {path}")
            blob = subprocess.run(
                ["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=False,
            )
            if blob.returncode != 0:  # deleted file
                continue
            if contains_secret(blob.stdout, current_token):
                raise ValueError(f"비밀값으로 보이는 내용이 커밋 기록에 포함되어 푸시를 중단했습니다: {path}")


def main() -> int:
    for line in sys.stdin:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("Git pre-push 입력 형식이 올바르지 않습니다.")
        check_range(fields[1], fields[3])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"푸시 전 검사 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
