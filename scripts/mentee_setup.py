#!/usr/bin/env python3
"""Create a mentee's private local profile and GitHub credential file."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_existing_token(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "GH_TOKEN":
            return value.strip().strip('"\'')
    return ""


def save_token(path: Path, token: str) -> None:
    if not token or any(char.isspace() for char in token):
        raise ValueError("토큰은 공백 없이 입력해야 합니다.")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition("=")[0].strip() != "GH_TOKEN"]
    lines.append(f"GH_TOKEN={token}")
    old_umask = os.umask(0o077)
    try:
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    finally:
        os.umask(old_umask)


def save_profile(path: Path, profile: dict) -> None:
    path.parent.mkdir(mode=0o700, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
    finally:
        os.umask(old_umask)


def setup(name: str, email: str, token: str = "") -> None:
    mentees = json.loads((ROOT / "config" / "mentees.json").read_text(encoding="utf-8"))
    if name not in mentees:
        raise ValueError("등록되지 않은 이름입니다. 관리자에게 config/mentees.json 수정을 요청하세요.")
    if not email or "@" not in email or any(char.isspace() for char in email):
        raise ValueError("올바른 커밋 이메일을 입력하세요.")
    existing_hooks = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip()
    if existing_hooks and existing_hooks != ".githooks":
        raise ValueError("기존 Git hooksPath가 있어 보안 훅을 설치할 수 없습니다. 관리자에게 확인하세요.")
    if not (ROOT / ".githooks" / "pre-push").is_file():
        raise ValueError("푸시 전 비밀값 검사 파일이 없습니다. 저장소를 다시 확인하세요.")

    env_path = ROOT / ".env"
    if token:
        save_token(env_path, token)

    info = mentees[name]
    profile = {
        "name": name,
        "focus": info["focus"],
        "track": info["track"],
        "starter_task": info["starter_task"],
    }
    subprocess.run(["git", "config", "--local", "user.name", name], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "--local", "user.email", email], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=ROOT, check=True)
    save_profile(ROOT / ".mentee" / "profile.json", profile)
    print(f"설정 완료: {name} · 게시 대상 main · GitHub 토큰 {'설정됨' if read_existing_token(env_path) else '미설정'}")
    print("Git 푸시 전 비밀값 검사도 활성화했습니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="멘티별 로컬 개발 환경 초기화")
    parser.add_argument("--name", help="멘티 이름. 생략하면 대화형으로 질문합니다.")
    parser.add_argument("--json-stdin", action="store_true", help="에이전트가 전달한 JSON 설정을 표준 입력에서 읽습니다.")
    args = parser.parse_args()

    if args.json_stdin:
        if args.name:
            raise ValueError("--json-stdin과 --name은 함께 사용할 수 없습니다.")
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("설정 입력은 JSON 객체여야 합니다.")
        name, email = request.get("name"), request.get("email")
        token = request.get("github_token", "")
        if not isinstance(name, str) or not isinstance(email, str) or not isinstance(token, str):
            raise ValueError("이름, 이메일, 토큰은 문자열이어야 합니다.")
        setup(name.strip(), email.strip(), token.strip())
        return 0

    if not sys.stdin.isatty():
        print("대화형 터미널에서 실행하거나 --json-stdin을 사용하세요.", file=sys.stderr)
        return 2

    mentees = json.loads((ROOT / "config" / "mentees.json").read_text(encoding="utf-8"))
    name = (args.name or input(f"멘티 이름 ({', '.join(mentees)}): ")).strip()
    email = input("GitHub 커밋 이메일: ").strip()
    env_path = ROOT / ".env"
    token = ""
    if not read_existing_token(env_path):
        print("GitHub 토큰이 있으면 지금 입력하세요. 없으면 Enter로 건너뛸 수 있습니다.")
        token = getpass.getpass("GitHub 토큰 (화면에 표시되지 않음): ").strip()
    setup(name, email, token)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"초기 설정 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
