"""Read a demo snapshot without modifying it; emit a reproducible D-01 inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow


# Keys come from the grouping/selection code, not uniqueness guesses.
TABLES = {
    "stores": ("인허가 1건", ["org_code", "mgmt_no", "service"], "pipeline/build.py: clean/build_address/main"),
    "units": ("주소·층 기반 자리 1곳", ["uid"], "pipeline/build.py: build_units"),
    "transitions": ("단일 자리의 앞 인허가→다음 인허가 쌍", [], "pipeline/build.py: build_transitions"),
    "area_year": ("지역 수준별 연도", ["level", "gu", "dong", "year"], "pipeline/build.py: build_cycle"),
    "area_cycle": ("지역 수준별 사이클", ["level", "gu", "dong"], "pipeline/build.py: build_cycle"),
    "survival": ("수준·지역·업종/업태별 생존 요약", ["level", "gu", "dong", "service", "category"], "pipeline/build.py: build_survival"),
    "vacancy_area": ("구군/동별 공실 후보 집계", ["level", "gu", "dong"], "pipeline/build.py: build_vacancy_area"),
    "poi": ("상가정보 점포", [], "pipeline/external.py: build_poi"),
    "area_context": ("행정동별 맥락", ["gu", "admin_dong"], "pipeline/external.py: build_area_context"),
    "legal_admin_map": ("법정동별 대표 행정동", ["gu", "legal_dong"], "pipeline/external.py: build_poi"),
    "station_traffic": ("역별 승하차 요약", ["station"], "pipeline/external.py: build_station_traffic"),
    "parking": ("주차장", [], "pipeline/external.py: build_parking"),
    "market": ("전통시장", [], "pipeline/external.py: build_market"),
}


def table(frame: pd.DataFrame) -> str:
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join([
        "| " + " | ".join(map(cell, frame.columns)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
        *["| " + " | ".join(map(cell, row)) + " |" for row in frame.itertuples(index=False, name=None)],
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/d01"))
    args = parser.parse_args()
    root = args.demo.resolve()
    source = root / "data/processed"
    meta = json.loads((source / "meta.json").read_text(encoding="utf-8"))
    frames = {name: pd.read_parquet(source / f"{name}.parquet") for name in TABLES}
    revision = subprocess.check_output([
        "git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), "rev-parse", "HEAD"
    ], text=True).strip()
    manifest = {
        "source": "https://github.com/donggwonY/daegu_lifecycle_agent",
        "commit": revision, "reference_date": meta["reference_date"], "built_at": meta["built_at"],
        "versions": {"python": platform.python_version(), "pandas": pd.__version__, "pyarrow": pyarrow.__version__},
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.iterdir()) if p.is_file()},
        "raw_csv_count": len(list((root / "data/raw").rglob("*.csv"))),
        "external_csv_count": len(list((root / "data/external").rglob("*.csv"))),
    }
    overview, dictionary = [], []
    for name, df in frames.items():
        unit, keys, generator = TABLES[name]
        overview.append({"table": name, "rows": len(df), "columns": len(df.columns),
                         "duplicate_rows_extra": int(df.duplicated().sum()),
                         "key_duplicate_extra": int(df.duplicated(keys).sum()) if keys else "고유키 미보존/미확정",
                         "unit": unit})
        columns = []
        for col in df:
            s = df[col]
            blank = int(s.map(lambda x: isinstance(x, str) and not x.strip()).sum())
            columns.append({"column": col, "dtype": str(s.dtype), "null": int(s.isna().sum()),
                            "null_pct": round(float(s.isna().mean() * 100), 2),
                            "blank": blank, "distinct_non_null": int(s.nunique())})
        dictionary.extend([f"## {name}", f"관측 단위: {unit}. 생성 코드: `{generator}`.",
                           "검사 키: " + (", ".join(f"`{k}`" for k in keys) if keys else "미확정. 행 번호를 영구 ID로 사용하지 않는다."),
                           table(pd.DataFrame(columns)), ""])

    st, units, trans = frames["stores"], frames["units"], frames["transitions"]
    ref = pd.Timestamp(meta["reference_date"])
    actual = {"total": len(st), "closed": int(st.closed.sum()), "active": int((~st.closed).sum()), "unique_units": st.uid.nunique()}
    checks = [{"check": f"meta.records.통합.{key}", "actual": int(val), "expected": meta["records"]["통합"][key],
               "pass": int(val) == meta["records"]["통합"][key]} for key, val in actual.items()]
    for name, count in {
        "stores uid absent from units": (~st.uid.isin(units.uid)).sum(),
        "transitions uid absent from units": (~trans.uid.isin(units.uid)).sum(),
        "closed without cd": (st.closed & st.cd.isna()).sum(),
        "cd before ld": (st.cd < st.ld).sum(),
        "duration inconsistent": (st.dur_days != (st.cd.where(st.closed, ref) - st.ld).dt.days.clip(lower=0)).sum(),
    }.items():
        checks.append({"check": name, "actual": int(count), "expected": 0, "pass": count == 0})
    groups = st.groupby("uid").size()
    checks.append({"check": "units.n_records differs from stores grouped count", "actual": int((units.set_index("uid").n_records != groups.reindex(units.uid).to_numpy()).sum()), "expected": 0})
    checks[-1]["pass"] = checks[-1]["actual"] == 0
    mapping = frames["legal_admin_map"]
    investigations = [
        ("좌표 결측", st, st.lat.isna() | st.lon.isna(), ["org_code", "mgmt_no", "service", "gu", "ld", "lat", "lon"],
         "좌표 변환 후 범위 밖/누락 값을 결측 처리한다. 원본이 없어 원천 누락과 변환 실패를 분리할 수 없다. 지도에서 빠지는 표본의 업종 편향을 추가 점검한다."),
        ("같은 날 개업·폐업", st, st.closed & st.dur_days.eq(0), ["org_code", "mgmt_no", "service", "ld", "cd", "dur_days"],
         "0일 기간은 데이터에서 관찰되지만 실제 당일 폐업인지 신고 정정인지 원본 확인이 필요하다. 자동 삭제하지 않는다."),
        ("한 자리에 다수 동시영업", units, units.max_concurrent.gt(1), ["uid", "n_records", "n_closed", "max_concurrent", "is_single_unit"],
         "주소·층 키는 개별 호실 ID가 아니다. 백화점/복합시설 등이 함께 묶일 수 있다. 생성 코드는 동시영업 1 이하만 단일 자리로 취급한다. 반복 폐업 횟수를 단일 점포 실패로 해석하지 않는다."),
        ("음수 전이 간격", trans, trans.gap_days.lt(0), ["uid", "from_service", "to_service", "to_open", "gap_days"],
         "다음 인허가가 앞 폐업 신고보다 먼저인 사례. 생성 코드는 -60일까지 허용한다. 실제 임대 공실 기간으로 해석하면 안 된다."),
        ("대표 행정동 점유율 100% 미만", mapping, mapping.share.lt(1), ["gu", "legal_dong", "admin_dong", "n", "share"],
         "법정동→행정동은 상가정보의 최빈 조합이며 행정 경계의 정확한 일대일 대응이 아니다. 조인 성공만으로 지역 정합성이 검증되지 않는다."),
    ]
    findings = []
    for title, df, mask, cols, note in investigations:
        count = int(mask.sum())
        findings.extend([f"## {title}", f"{count:,} / {len(df):,}행 ({count / len(df) * 100:.2f}%). {note}",
                         table(df.loc[mask, cols].head(5)), ""])
    coverage = st.groupby("service").agg(rows=("uid", "size"), missing_lat=("lat", lambda s: int(s.isna().sum())),
                                         ld_min=("ld", "min"), ld_max=("ld", "max"), cd_max=("cd", "max"))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "dictionary.md").write_text("# D-01 데이터 구조 사전 초안\n\n전체 컬럼의 자료형·결측·빈 문자열·고유값 수. null과 빈 문자열은 별도 집계한다. 지역 수준별 요약표의 상위 수준에서는 dong 등이 구조적으로 비어 있으므로 모든 결측을 오류로 세지 않는다. 컬럼별 의미 정의는 후속 작업이다.\n\n" + "\n\n".join(dictionary), encoding="utf-8")
    report = ["# D-01 첫 데이터 점검", f"출처: {manifest['source']} · commit `{revision}`.",
              f"인허가 기준일: {meta['reference_date']} · 빌드: {meta['built_at']}. 실행 환경과 파일 해시는 manifest.json에 기록.",
              f"원본 인허가 CSV {manifest['raw_csv_count']}개, 보조 CSV {manifest['external_csv_count']}개. 원본 재정제·CP949·제외 행은 검증하지 못했다. meta.quality는 원본 정제 단계 수치로 현재 Parquet 결측 수와 분모가 다르다.",
              "## 테이블 목록", table(pd.DataFrame(overview)), "## 일치 검사", table(pd.DataFrame(checks)),
              "## 업종별 범위", table(coverage.reset_index()),
              "ld_max/cd_max는 관찰된 사건의 최댓값이며 출처별 수집 완료일을 보장하지 않는다. 보조 데이터는 인허가 기준일을 공유한다고 가정하지 않는다. config.py의 파일명상 POI 2026-06, 인구 2026-08-31, 역별 자료 2026-07-31이며 원본 부재로 확인이 제한된다.",
              "## 조인 관계", "stores.uid → units.uid, transitions.uid → units.uid는 다대일. 지역 요약은 level을 포함해 사용한다. stores.(gu,dong) → legal_admin_map.(gu,legal_dong) → area_context.(gu,admin_dong)은 대표 매핑이므로 실패율과 대표 점유율을 확인해야 한다. poi·parking·market에는 원천 고유 ID가 보존되지 않아 이름만으로 조인하지 않는다. station_traffic에는 공간 조인 키가 없다.",
              *findings,
              "## 진행 상태", "D-01 진행 중. 전체 컬럼 의미·자료 출처별 수집일 확인, 조인 실패율, 이상 사례에 대한 학생의 가설/해석을 보완한 뒤 완료 여부를 판단한다. 인허가상 폐업은 사업 실패, 신규 인허가 부재는 실제 임대 공실을 직접 측정하지 않는다."]
    (args.output / "report.md").write_text("\n\n".join(report) + "\n", encoding="utf-8")
    print(table(pd.DataFrame(overview)))
    print(table(pd.DataFrame(checks)))
    for title, df, mask, _, _ in investigations:
        print(f"{title}: {int(mask.sum())}/{len(df)}")
    if not all(item["pass"] for item in checks):
        raise SystemExit("Consistency checks failed; inspect report.md")


if __name__ == "__main__":
    main()
