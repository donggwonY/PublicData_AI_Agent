"""API로 받은 인허가와 지금 원본 파일 대조 (E-04 데이터 주간 갱신, 2026-11-24).

    python -m pipeline.compare_license data/raw_api/full_20261123 [--json ../docs/e04/results/api_vs_file.json]

지금 원본 = data/raw 의 업종 파일 전부(기존 파일 + 주간 갱신분, 배치와 같은 규칙으로 합침).

업종마다 행 수, 키(개방자치단체코드+관리번호) 겹침, 배치가 쓰는 열의 값 일치율을 센다.
값이 다른 행은 '파일 이후 바뀐 것'(최종수정시점·데이터갱신시점이 파일보다 늦음)과 그 밖으로 나눈다.
파일 이후 바뀐 것은 정상(API가 더 최신), 그 밖의 차이는 변환 오류 후보다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
import config as C  # noqa: E402
from pipeline.build import USECOLS  # noqa: E402

KEY = ["개방자치단체코드", "관리번호"]
TIME_COLS = ["최종수정시점", "데이터갱신시점"]


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig" if "_api" in path.stem else "cp949", encoding_errors="replace",
                       dtype=str, usecols=lambda c: c in USECOLS)


def _combined(paths: list[Path]) -> pd.DataFrame:
    """한 업종의 원본 여러 개(기존 파일 + 주간 갱신분)를 배치(build.load_raw)와 같은 규칙으로 합친다."""
    df = pd.concat([_read(p) for p in paths], ignore_index=True)
    df = df.sort_values(TIME_COLS, na_position="first")
    return df.drop_duplicates(KEY, keep="last").reset_index(drop=True)


def _norm(s: pd.Series, col: str) -> pd.Series:
    s = s.fillna("").astype(str).str.strip()
    if col.startswith("좌표") or col == "소재지면적":
        return pd.to_numeric(s, errors="coerce").round(3).astype("string").fillna("")
    return s


def compare_service(file_csv: Path | list[Path], api_csv: Path) -> dict:
    """file_csv = 지금 원본(여러 개면 합침), api_csv = API 전체본."""
    f = _combined(file_csv if isinstance(file_csv, list) else [file_csv])
    a = _read(api_csv)
    m = f.merge(a, on=KEY, how="outer", suffixes=("_f", "_a"), indicator=True)
    both = m[m["_merge"] == "both"]
    newer = pd.Series(False, index=both.index)
    for c in TIME_COLS:
        newer |= both[f"{c}_a"].fillna("") > both[f"{c}_f"].fillna("")
    cols, other_diff = {}, pd.Series(False, index=both.index)
    for c in USECOLS:
        if c in KEY or f"{c}_f" not in both or c in TIME_COLS or c == "데이터갱신구분":
            continue
        diff = _norm(both[f"{c}_f"], c) != _norm(both[f"{c}_a"], c)
        cols[c] = {"diff": int(diff.sum()), "diff_not_newer": int((diff & ~newer).sum())}
        other_diff |= diff & ~newer
    only_f = m[m["_merge"] == "left_only"]
    return {
        "file_rows": len(f), "api_rows": len(a), "both": len(both),
        "only_file": len(only_f), "only_api": int((m["_merge"] == "right_only").sum()),
        "newer_in_api": int(newer.sum()),
        "value_diff_not_explained": int(other_diff.sum()),
        "columns": {k: v for k, v in cols.items() if v["diff"]},
        "only_file_examples": only_f[["관리번호", "사업장명_f", "영업상태명_f"]].head(3).to_dict("records"),
    }


def raw_files() -> dict[str, list[Path]]:
    """data/raw 의 원본을 업종별로(배치와 같이 하위 폴더 포함, 파일 이름 두 번째 칸 = 업종)."""
    files: dict[str, list[Path]] = {}
    for p in sorted(C.RAW_DIR.rglob("*.csv")):
        parts = p.stem.split("_")
        if len(parts) >= 2 and parts[1] in C.SERVICES:
            files.setdefault(parts[1], []).append(p)
    return files


def compare_dir(api_dir: Path, verbose: bool = True) -> dict:
    files = raw_files()
    apis = {p.stem.split("_")[1]: p for p in api_dir.glob("*_api.csv")}
    out = {}
    for svc in C.SERVICES:
        if svc not in files or svc not in apis:
            out[svc] = {"missing": "file" if svc not in files else "api"}
            print(f"{svc:<16} 대조 불가({out[svc]['missing']} 없음)")
            continue
        r = out[svc] = compare_service(files[svc], apis[svc])
        if verbose:
            print(f"{svc:<16} 파일 {r['file_rows']:>6,} · API {r['api_rows']:>6,} · 파일만 {r['only_file']:>4} · API만 {r['only_api']:>4}"
                  f" · API가 최신 {r['newer_in_api']:>4} · 설명 안 되는 값 차이 {r['value_diff_not_explained']:>4}", flush=True)
    tot = {k: sum(v.get(k, 0) for v in out.values()) for k in
           ["file_rows", "api_rows", "only_file", "only_api", "newer_in_api", "value_diff_not_explained"]}
    tot["missing"] = sorted(k for k, v in out.items() if "missing" in v)
    return {"api_dir": api_dir.name, "total": tot, "services": out}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("api_dir")
    ap.add_argument("--json", help="결과 JSON 경로")
    a = ap.parse_args(argv)
    api_dir = Path(a.api_dir) if Path(a.api_dir).is_absolute() else SERVICE_DIR / a.api_dir
    res = compare_dir(api_dir)
    print("합계", res["total"])
    if a.json:
        p = Path(a.json) if Path(a.json).is_absolute() else SERVICE_DIR / a.json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(json.dumps(res, ensure_ascii=False, indent=1).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
