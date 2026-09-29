#!/usr/bin/env python3
"""Bring a clean local main up to origin/main using fast-forward only."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from commit_push import (
    EXPECTED_REMOTE,
    GitError,
    ensure_clean,
    git,
    is_ancestor,
    rebase_in_progress,
    verify_repository,
)
from mentee_setup import ROOT


def pull_main(root: Path = ROOT, expected_remote: str = EXPECTED_REMOTE) -> str:
    verify_repository(root, expected_remote)
    if rebase_in_progress(root):
        raise ValueError("충돌 해결 중입니다. 진행 중인 Git 작업을 먼저 마무리해야 합니다.")
    ensure_clean(root)

    git(root, "fetch", "origin", "main", auth=True)
    local = git(root, "rev-parse", "HEAD").stdout.strip()
    remote = git(root, "rev-parse", "origin/main").stdout.strip()

    if local == remote:
        print("원격 main과 이미 같은 커밋입니다.")
        return "current"
    if is_ancestor(root, local, remote):
        git(root, "merge", "--ff-only", "origin/main")
        print("원격 main의 최신 커밋을 fast-forward로 반영했습니다.")
        return "updated"
    if is_ancestor(root, remote, local):
        print("원격 main의 변경은 모두 포함되어 있습니다. 아직 푸시하지 않은 로컬 커밋이 있습니다.")
        return "ahead"
    raise ValueError(
        "로컬 main과 원격 main이 서로 다른 커밋을 가지고 있어 fast-forward할 수 없습니다. "
        "기존 변경은 보존했습니다. 에이전트가 양쪽 이력을 확인하고 commit-push 흐름으로 통합해야 합니다."
    )


if __name__ == "__main__":
    try:
        pull_main()
    except (GitError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"pull 중단: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
