"""E-09: 로컬 점수표 → 앱용 service/data/processed/next_tenant_scores.parquet (필요한 열만, 영문 열 이름).

- 점수표 SHA-256을 docs/e09/results/serve_scores.json 기록과 대조하고, 데이터 기준일이 앱 meta.json과 같은지 확인한다.
- 좌표가 없는 자리(no_coords)는 주변 변수가 비어 있어 화면에서 이동표만 보여 준다(serve_design.md §6, 2026-11-19 결정).
- 앱 parquet 모드에서 바로 읽힌다. 공개 앱(DB 모드)은 app 스키마 새 버전에 이 표를 올린 뒤 보인다.
실행(저장소 루트): C:/claude_workspace/e06_env/Scripts/python scripts/e09_next_tenant/export_service_scores.py
"""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "service/data/processed"
SUMMARY = ROOT / "docs/e09/results/serve_scores.json"
SRC = Path("C:/claude_workspace/e09_data/serve")
# 화면·DB용 영문 키(순서 = 모델 묶음 순서). 한글 이름은 service/config.py NEXT_TENANT_GROUPS.
EN = {"음식점": "food", "카페_제과": "cafe", "미용_이용": "beauty", "식품판매": "food_retail",
      "담배": "tobacco", "오락": "entertainment", "기타": "other"}


def main():
    summ = json.loads(SUMMARY.read_text(encoding="utf-8"))
    ref = json.loads((PROC / "meta.json").read_text(encoding="utf-8"))["reference_date"]
    path = SRC / f"next_tenant_scores_{ref}.parquet"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != summ["file_sha256"]:
        raise SystemExit(f"점수표 해시 불일치: {sha}")
    s = pd.read_parquet(path)
    if set(s.data_reference_date) != {ref}:
        raise SystemExit(f"점수 기준일 {set(s.data_reference_date)} ≠ 앱 데이터 기준일 {ref}")
    units = pd.read_parquet(PROC / "units.parquet", columns=["uid", "lat"]).set_index("uid")
    out = pd.DataFrame({"uid": s.uid.astype(str), "vacant_days": s.vacant_days.astype(int), "prev_group": s.prev_group7})
    for k, e in EN.items():
        out[f"p_{e}"] = s[f"p_{k}"].astype(float)
    for k, e in EN.items():
        out[f"typical_{e}"] = s[f"typical_{k}"].astype(float)
    out["no_coords"] = out.uid.map(units["lat"]).isna()
    out["data_reference_date"] = s.data_reference_date
    out["generated"] = s.generated
    out["model_version"] = s.model_version
    out["source_sha256"] = sha
    assert out.uid.is_unique
    out.to_parquet(PROC / "next_tenant_scores.parquet", index=False)
    print({"rows": len(out), "no_coords": int(out.no_coords.sum()), "reference_date": ref,
           "model_version": out.model_version.iloc[0]})


if __name__ == "__main__":
    main()
