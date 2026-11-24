"""인허가 원본 주간·월간 갱신 (E-04 데이터 주간 갱신, 2026-11-24).

    # 주간: 지금 원본의 가장 늦은 데이터갱신시점 - 1일 이후 바뀐 행만 받아 data/raw 에 갱신분 파일로 얹는다
    python -m pipeline.refresh_license weekly
    # 월 1회: 대구 전체를 받아 지금 원본(기존 + 갱신분)과 대조하고, 이상이 없으면 원본을 전체본으로 바꾼다
    python -m pipeline.refresh_license monthly [--from-dir data/raw_api/full_20261123]

- 주간 갱신분은 `<분류>_<업종>_api_delta<YYYYMMDD>.csv`. 배치(build.load_raw)가 같은 가게(자치단체코드+관리번호+업종)는
  최종수정시점이 가장 늦은 행만 남기므로 기존 파일 위에 얹기만 하면 된다.
- API에는 삭제 표시가 없다(데이터갱신구분 I·U만, 2026-11-24 확인). 원천에서 지워진 행은 주간 갱신으로 알 수 없어
  월 1회 전체본으로 원본을 통째로 바꿀 때 빠진다.
- 월간 교체 전 대조에서 '설명 안 되는 값 차이'(파일 이후 바뀐 것이 아닌데 값이 다름)가 있거나 업종이 빠지면 멈춘다.
- 교체된 이전 원본은 지우지 않고 data/raw_archive/<날짜>/ 로 옮긴다(배치는 data/raw 아래 하위 폴더도 읽으므로 바깥에 둔다).
- 이 스크립트는 원본 파일만 바꾼다. 배치·점검·DB 적재는 TEAM_WORKFLOW 의 데이터 갱신 절차대로 따로 실행한다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
import config as C  # noqa: E402
from pipeline import compare_license, fetch_license  # noqa: E402

API_DIR = SERVICE_DIR / "data" / "raw_api"
ARCHIVE_DIR = SERVICE_DIR / "data" / "raw_archive"
OVERLAP = timedelta(days=1)   # 포털 반영 지연·시계 차이를 감안해 하루 겹쳐 받는다(겹친 행은 배치가 하나로 합친다)


def latest_update_point() -> datetime:
    """지금 원본 전체에서 가장 늦은 데이터갱신시점."""
    best = None
    for paths in compare_license.raw_files().values():
        for p in paths:
            enc = "utf-8-sig" if "_api" in p.stem else "cp949"
            s = pd.read_csv(p, encoding=enc, encoding_errors="replace", dtype=str, usecols=["데이터갱신시점"])
            m = pd.to_datetime(s["데이터갱신시점"], errors="coerce").max()
            if pd.notna(m) and (best is None or m > best):
                best = m
    if best is None:
        raise SystemExit("data/raw 에 데이터갱신시점이 있는 원본이 없습니다.")
    return best.to_pydatetime()


def target_name(api_file: str, tag: str) -> str:
    """'식품_일반음식점_api.csv' + 'delta20261130' → '식품_일반음식점_api_delta20261130.csv'."""
    return api_file.removesuffix(".csv") + f"_{tag}.csv"


def _manifest_ok(out: Path, n: int) -> dict:
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    done = man["services"]
    bad = [k for k, v in done.items() if not v["complete"]]
    if len(done) < n or bad:
        raise SystemExit(f"수집이 끝나지 않았습니다: 완료 {len(done)}/{n}, 행 수 불일치 {bad}. 같은 명령을 다시 실행하면 이어 받습니다.")
    return man


def weekly(a) -> int:
    since = a.since or (latest_update_point() - OVERLAP).strftime("%Y-%m-%d %H:%M:%S")
    tag = f"delta{date.today():%Y%m%d}"
    out = API_DIR / tag
    print(f"주간 갱신: 데이터갱신시점 {since} 이후 바뀐 행 → {out}", flush=True)
    fetch_license.main(["--since", since, "--out", str(out), "--workers", str(a.workers)])
    man = _manifest_ok(out, len(C.SERVICES))
    copied = {}
    for svc, r in sorted(man["services"].items()):
        if r["rows"]:
            shutil.copy2(out / r["file"], C.RAW_DIR / target_name(r["file"], tag))
            copied[svc] = r["rows"]
    print(f"data/raw 에 갱신분 {len(copied)}개 업종 · {sum(copied.values()):,}행 추가: {copied}")
    return 0


def monthly(a) -> int:
    tag = f"full{date.today():%Y%m%d}"
    out = Path(a.from_dir) if a.from_dir else API_DIR / tag
    out = out if out.is_absolute() else SERVICE_DIR / out
    if not a.from_dir:
        fetch_license.main(["--full", "--out", str(out), "--workers", str(a.workers)])
    man = _manifest_ok(out, len(C.SERVICES))
    print("지금 원본(기존 + 갱신분)과 전체본 대조", flush=True)
    res = compare_license.compare_dir(out, verbose=False)
    tot = res["total"]
    (out / "compare.json").write_bytes(json.dumps(res, ensure_ascii=False, indent=1).encode("utf-8"))
    print(f"원본 {tot['file_rows']:,} · 전체본 {tot['api_rows']:,} · 원천에서 지워짐 {tot['only_file']:,} · 신규 {tot['only_api']:,}"
          f" · 갱신 {tot['newer_in_api']:,} · 설명 안 되는 값 차이 {tot['value_diff_not_explained']:,} · 대조 불가 {tot['missing']}")
    if tot["value_diff_not_explained"] or tot["missing"]:
        raise SystemExit(f"대조 이상으로 원본을 바꾸지 않았습니다. {out / 'compare.json'} 를 확인하세요.")
    if a.dry_run:
        print("--dry-run: 원본은 바꾸지 않았습니다.")
        return 0
    arch = ARCHIVE_DIR / date.today().strftime("%Y%m%d")
    arch.mkdir(parents=True, exist_ok=True)
    moved = 0
    for paths in compare_license.raw_files().values():
        for p in paths:
            dest = arch / p.relative_to(C.RAW_DIR)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), dest)
            moved += 1
    for r in man["services"].values():
        shutil.copy2(out / r["file"], C.RAW_DIR / target_name(r["file"], tag))
    print(f"이전 원본 {moved}개 → {arch} · 전체본 {len(man['services'])}개 → data/raw")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    w = sub.add_parser("weekly", help="바뀐 행만 받아 얹기")
    w.add_argument("--since", help='직접 지정, 예 "2026-11-22 00:00:00" (기본: 원본의 가장 늦은 데이터갱신시점 - 1일)')
    m = sub.add_parser("monthly", help="전체를 받아 대조 후 원본 교체")
    m.add_argument("--from-dir", help="이미 받은 전체본 폴더(다시 받지 않음)")
    m.add_argument("--dry-run", action="store_true", help="대조만 하고 원본은 그대로")
    for p in (w, m):
        p.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    return weekly(a) if a.mode == "weekly" else monthly(a)


if __name__ == "__main__":
    sys.exit(main())
