#!/usr/bin/env python3
"""배포 전후 점검 (E-04 3단계, docs/e04/README.md). 푸시는 하지 않는다.

  python3 scripts/deploy_check.py pre    # deploy 로 올리기 전: Git 상태·바뀌는 파일·테스트·smoke·데이터 점검
  python3 scripts/deploy_check.py post   # deploy 푸시와 Reboot 뒤: deploy = main·공개 앱 응답·DB 현재 버전 점검

pre 가 통과해야 배포한다. deploy 푸시 자체는 염동권 확인 뒤 별도로 한다(TEAM_WORKFLOW 배포 순서).
테스트와 데이터 점검은 service/.venv 의 Python 으로 실행한다. DB 접속 정보는 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from commit_push import EXPECTED_REMOTE, GitError, ensure_clean, git, is_ancestor, verify_repository
from mentee_setup import ROOT

SERVICE = ROOT / "service"
APP_URL = "https://pubdai.streamlit.app"
HEALTH_URL = APP_URL + "/~/+/_stcore/health"
# 배포 환경(Streamlit Cloud)이 다시 설치해야 하는 파일. 바뀌면 배포 로그의 패키지 버전을 꼭 확인한다.
ENV_FILES = ("service/requirements.txt", "service/runtime.txt", "service/packages.txt", "service/.streamlit/config.toml")


class Checks:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, level: str, name: str, detail: str = "") -> None:
        self.rows.append((level, name, detail))
        print(f"[{level:4}] {name}" + (f" — {detail}" if detail else ""), flush=True)

    @property
    def failed(self) -> bool:
        return any(r[0] == "FAIL" for r in self.rows)


def venv_python() -> Path:
    for p in (SERVICE / ".venv/Scripts/python.exe", SERVICE / ".venv/bin/python"):
        if p.exists():
            return p
    raise SystemExit("service/.venv 가 없습니다. service/README.md 의 가상환경 준비를 먼저 하세요.")


def run_service(c: Checks, name: str, args: list[str], timeout: int = 900) -> None:
    env = dict(os.environ, APP_DATA_SOURCE="parquet", PYTHONIOENCODING="utf-8")
    t0 = time.time()
    r = subprocess.run([str(venv_python()), *args], cwd=SERVICE, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
    c.add("OK" if r.returncode == 0 else "FAIL", name, f"{tail[0][:120]} ({time.time() - t0:.0f}s)")


def data_check(c: Checks) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("APP_DATA_SOURCE", None)
    r = subprocess.run([str(venv_python()), "-m", "pipeline.check_data", "--db", "--pubdai"], cwd=SERVICE, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    out = (r.stdout + r.stderr).strip().splitlines()
    for line in out:
        if line.startswith(("[WARN]", "[FAIL]")):
            print("       " + line)
    summary = next((l for l in reversed(out) if l.startswith("요약")), out[-1] if out else "")
    c.add("OK" if r.returncode == 0 else "FAIL", "데이터 점검(check_data --db --pubdai)", summary)


def git_state(c: Checks, need_clean: bool = True) -> tuple[str, str]:
    verify_repository(ROOT, EXPECTED_REMOTE)
    branch = git(ROOT, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main":
        c.add("FAIL", "현재 브랜치", f"{branch} (main 에서 실행)")
    if need_clean:
        try:
            ensure_clean(ROOT)
        except (GitError, ValueError) as e:
            c.add("FAIL", "작업 폴더 깨끗함", "커밋하지 않은 변경이 있음" if isinstance(e, ValueError) else str(e))
    git(ROOT, "fetch", "origin", "main", "deploy", auth=True)
    main = git(ROOT, "rev-parse", "origin/main").stdout.strip()
    deploy = git(ROOT, "rev-parse", "origin/deploy").stdout.strip()
    head = git(ROOT, "rev-parse", "HEAD").stdout.strip()
    c.add("OK" if head == main else "FAIL", "로컬 main = origin/main", f"{head[:7]} / {main[:7]}")
    return main, deploy


def pre(_args) -> int:
    c = Checks()
    main, deploy = git_state(c)
    if main == deploy:
        c.add("OK", "deploy = main", f"{main[:7]} — 올릴 커밋 없음")
    elif is_ancestor(ROOT, deploy, main):
        n = git(ROOT, "rev-list", "--count", f"{deploy}..{main}").stdout.strip()
        c.add("OK", "fast-forward 가능", f"deploy {deploy[:7]} → main {main[:7]} ({n}개 커밋)")
    else:
        c.add("FAIL", "fast-forward 가능", "deploy 가 main 에 없는 커밋을 가짐(Codespaces 커밋 등). TEAM_WORKFLOW 참고")
    files = git(ROOT, "diff", "--name-only", deploy, main).stdout.split()
    svc = [f for f in files if f.startswith("service/")]
    c.add("OK", "바뀌는 파일", f"전체 {len(files)}개 · service/ {len(svc)}개" +
          ("" if svc else " → 공개 앱 코드·데이터는 그대로(배포 불필요할 수 있음)"))
    env_changed = [f for f in files if f in ENV_FILES]
    if env_changed:
        c.add("WARN", "배포 환경 파일 변경", f"{env_changed} → 배포 로그의 패키지 설치·버전 확인")
    data_changed = [f for f in svc if f.startswith("service/data/processed/")]
    if data_changed:
        c.add("WARN", "가공 데이터 변경", f"{len(data_changed)}개 → DB 현재 버전과 같은 배치인지 데이터 점검으로 확인")
    run_service(c, "service 테스트", ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
    run_service(c, "smoke 테스트", ["-m", "tests.smoke_test"])
    data_check(c)
    print("\n" + ("배포 전 점검 FAIL: deploy 로 올리지 않습니다." if c.failed else
                  f"배포 전 점검 통과. 확인 뒤 `git push origin {main[:7]}:deploy` (fast-forward) → Streamlit Cloud Reboot → post 점검."))
    return 1 if c.failed else 0


def fetch_health() -> tuple[int, str]:
    """(HTTP 상태, 본문). curl 이 있으면 curl 을 쓴다(일부 Python 배포판은 OS 인증서 저장소를 못 읽는다)."""
    if shutil.which("curl"):
        r = subprocess.run(["curl", "-s", "-m", "20", "-w", "\n%{http_code}", HEALTH_URL],
                           capture_output=True, text=True, timeout=30)
        body, _, code = r.stdout.rpartition("\n")
        return int(code or 0), body.strip()
    with urllib.request.urlopen(HEALTH_URL, timeout=20) as r:
        return r.status, r.read(100).decode("utf-8", "replace").strip()


def health(c: Checks, tries: int, wait: int) -> None:
    last = ""
    for i in range(tries):
        try:
            status, body = fetch_health()
            if status == 200 and body == "ok":
                c.add("OK", "공개 앱 응답", f"{HEALTH_URL} → ok ({i + 1}회째)")
                return
            last = f"{status} {body[:40]}"
        except Exception as e:  # noqa: BLE001 — 네트워크·HTTP 오류 모두 재시도
            last = type(e).__name__
        if i + 1 < tries:
            time.sleep(wait)
    c.add("FAIL", "공개 앱 응답", f"{tries}회 실패: {last}")


def post(args) -> int:
    c = Checks()
    main, deploy = git_state(c, need_clean=False)
    c.add("OK" if deploy == main else "FAIL", "origin/deploy = origin/main", f"{deploy[:7]} / {main[:7]}")
    health(c, args.tries, args.wait)
    data_check(c)
    print("\n화면 확인(사람 또는 에이전트 브라우저): 사이드바 '데이터 db v<번호>'·기준일·누적 건수가 "
          "데이터 점검의 현재 버전과 같은지, 이번 배포로 바뀐 화면이 보이는지.")
    print("배포 후 점검 FAIL" if c.failed else "배포 후 점검 통과")
    return 1 if c.failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pre", help="deploy 로 올리기 전 점검").set_defaults(fn=pre)
    p = sub.add_parser("post", help="deploy 푸시·Reboot 뒤 점검")
    p.add_argument("--tries", type=int, default=6)
    p.add_argument("--wait", type=int, default=20, help="공개 앱 응답 재시도 간격(초)")
    p.set_defaults(fn=post)
    args = ap.parse_args()
    try:
        return args.fn(args)
    except (GitError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"점검 중단: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
