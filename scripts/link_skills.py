#!/usr/bin/env python3
"""Expose one canonical SKILL.md to both Codex and Claude Code."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def link_skills(root: Path = ROOT) -> list[str]:
    source_root = root / ".agents" / "skills"
    target_roots = [root / ".codex" / "skills", root / ".claude" / "skills"]
    if not source_root.is_dir():
        raise ValueError(f"스킬 원본 디렉터리가 없습니다: {source_root}")
    for target_root in target_roots:
        target_root.mkdir(parents=True, exist_ok=True)

    linked = []
    for source in sorted(source_root.iterdir()):
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            continue
        created = False
        for target_root in target_roots:
            target = target_root / source.name
            if target.is_symlink():
                if target.resolve() != source.resolve():
                    raise ValueError(f"다른 곳을 가리키는 링크가 있습니다: {target}")
                continue
            if target.exists():
                raise ValueError(f"이미 별도 파일/폴더가 있습니다. 내용을 확인하세요: {target}")
            relative_source = os.path.relpath(source, start=target_root)
            target.symlink_to(relative_source, target_is_directory=True)
            created = True
        if created:
            linked.append(source.name)
    return linked


if __name__ == "__main__":
    try:
        created = link_skills()
        print("Codex·Claude Code 스킬 링크 확인 완료" + (f": {', '.join(created)}" if created else " (새 링크 없음)"))
    except (OSError, ValueError) as exc:
        print(f"스킬 링크 생성 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
