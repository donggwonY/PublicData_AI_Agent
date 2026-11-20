"""배치 산출물·공유 DB 데이터 점검 (E-04 1단계, docs/e04/README.md).

데이터 계약(docs/e02/data_contract.md) 5절에서 사람이 하던 검사를 한 번에 돌린다. 읽기만 한다.

  python -m pipeline.check_data                       # 저장소 parquet(data/processed) 점검
  python -m pipeline.check_data --db --env-file ../.env   # + 공유 DB 현재 버전 점검, parquet 와 대조

DB 접속은 APP_READER_DATABASE_URL(읽기 전용 계정)을 먼저 쓰고, 없으면 APP_DATABASE_URL 을 쓴다.
환경변수가 .env 보다 우선한다. 접속 문자열은 출력하지 않는다.
결과: 항목마다 OK / WARN / FAIL. FAIL 이 하나라도 있으면 종료 코드 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
from core import datasource as ds  # noqa: E402

# 표별 키(데이터 계약 1절 "중복 0" 항목 + 결과 표의 기본 키). 미확정 키 표(transitions·poi·parking·market)는 뺀다.
KEYS = {
    "stores": ["org_code", "service", "mgmt_no"],
    "units": ["uid"],
    "area_year": ["level", "gu", "dong", "year"],
    "area_cycle": ["level", "gu", "dong"],
    "survival": ["level", "gu", "dong", "service", "category"],
    "vacancy_area": ["level", "gu", "dong"],
    "area_context": ["gu", "admin_dong"],
    "legal_admin_map": ["gu", "legal_dong"],
    "station_traffic": ["station"],
    "vacancy_scores": ["uid"],
    "competition_forecast": ["gu", "category"],
    "population_forecast": ["admin_code", "age_band"],
    "similar_areas": ["admin_code", "option", "rank"],
    "next_tenant_scores": ["uid"],
}
# uid 로 units 에 붙어야 하는 표
UID_JOINS = ["stores", "transitions", "vacancy_scores", "next_tenant_scores"]
# 0~1 확률 열
PROB_COLS = {"vacancy_scores": ["p_fill_1y"],
             "next_tenant_scores": ["p_food", "p_cafe", "p_beauty", "p_food_retail", "p_tobacco",
                                    "p_entertainment", "p_other"]}
# 행정동 미연결 비율. 15업종 v3 1.33%(데이터 계약 3절) → 42종 v5~v10 5.08%(번지 가림 주소의 동 결측) →
# E-12 수정 뒤 1.49%(docs/e12/README.md). 지금 수준에서 1%p 넘게 늘면 원인 확인 대상.
ADMIN_UNMATCHED_WARN = 0.025
# 확률 합 허용 오차: 결과 표는 반올림해 저장한다(최대 오차 2e-5 관측).
PROB_SUM_TOL = 1e-3
# DB 현재 버전과 비교할 때 행 수가 이보다 크게 줄면 경고
SHRINK_WARN = 0.05
# DB 크기 경고: Pro 플랜 디스크 8GB(자동 확장, 확장 뒤 4시간 재변경 불가). retired 버전이 쌓이면 커진다(v10 기준 1.9GB).
DB_SIZE_WARN_MB = 2500


@dataclass
class Report:
    rows: list[tuple[str, str, str, str]] = field(default_factory=list)

    def add(self, where: str, level: str, name: str, detail: str = "") -> None:
        self.rows.append((where, level, name, detail))

    def ok(self, where, name, detail=""):
        self.add(where, "OK", name, detail)

    def warn(self, where, name, detail=""):
        self.add(where, "WARN", name, detail)

    def fail(self, where, name, detail=""):
        self.add(where, "FAIL", name, detail)

    @property
    def failed(self) -> bool:
        return any(r[1] == "FAIL" for r in self.rows)

    def summary(self) -> dict:
        return {lv: sum(r[1] == lv for r in self.rows) for lv in ("OK", "WARN", "FAIL")}

    def print(self) -> None:
        for where, lv, name, detail in self.rows:
            print(f"[{lv:4}] {where:7} {name}" + (f" — {detail}" if detail else ""))
        s = self.summary()
        print(f"\n요약: OK {s['OK']} · WARN {s['WARN']} · FAIL {s['FAIL']}")


def check_frames(frames: dict[str, pd.DataFrame | None], meta: dict, where: str, rep: Report) -> None:
    """한 묶음(parquet 또는 DB 한 버전)의 계약 검사."""
    # 1. 표 존재·빈 표
    for t in ds.TABLES:
        df = frames.get(t)
        if df is None:
            (rep.fail if t in ds.REQUIRED else rep.warn)(where, f"{t} 표 있음", "없음")
        elif len(df) == 0:
            rep.fail(where, f"{t} 행 있음", "0행")
    present = {t: df for t, df in frames.items() if df is not None and len(df)}
    rep.ok(where, "표 존재", f"{len(present)}/{len(ds.TABLES)}개 · " +
           ", ".join(f"{t} {len(df):,}" for t, df in present.items()))

    # 2. 키 유일성·키 결측
    for t, key in KEYS.items():
        df = present.get(t)
        if df is None:
            continue
        miss = [k for k in key if k not in df.columns]
        if miss:
            rep.fail(where, f"{t} 키 열", f"없음: {miss}")
            continue
        dup = int(df.duplicated(key).sum())
        # level 이 상위(전체·구)인 행은 dong 등이 비어 있는 것이 정상이라 결측 검사는 level 없는 표만
        null = 0 if "level" in key else int(df[key].isna().any(axis=1).sum())
        if dup or null:
            rep.fail(where, f"{t} 키 {'+'.join(key)}", f"중복 {dup:,} · 결측 {null:,}")
        else:
            rep.ok(where, f"{t} 키 {'+'.join(key)}", "중복 0")

    # 3. uid → units 연결
    units = present.get("units")
    if units is not None:
        uids = set(units["uid"])
        for t in UID_JOINS:
            df = present.get(t)
            if df is None:
                continue
            # 번지가 가려진 인허가(E-12)는 자리 키가 없다. 그 밖의 빈 uid 는 실패로 본다.
            no_uid = df["uid"].isna()
            masked = df["addr_masked"].fillna(False).astype(bool) if "addr_masked" in df.columns else no_uid & False
            bad = int((~df["uid"].isin(uids) & ~(no_uid & masked)).sum())
            note = f" · 번지 가림(자리 없음) {int((no_uid & masked).sum()):,}" if masked.any() else ""
            (rep.fail if bad else rep.ok)(where, f"{t} → units (uid)", f"연결 실패 {bad:,} / {len(df):,}{note}")


    # 3-1. 번지가 가려진 주소로 만든 가짜 자리 키(E-12): 서로 다른 가게가 한 자리로 합쳐진다
    for t in ["units"] + UID_JOINS:
        df = present.get(t)
        if df is None:
            continue
        fake = int(df["uid"].dropna().astype(str).str.contains("*", regex=False).sum())
        (rep.fail if fake else rep.ok)(where, f"{t} 가려진 번지 자리 키 없음", f"{fake:,}행")

    # 3-2. 가려진 숫자가 남은 동 이름(예: '수성동*가', E-12 후속): 동 단위 집계에 가짜 동이 생긴다
    for t in ("stores", "area_cycle", "area_year", "survival", "vacancy_area", "units"):
        df = present.get(t)
        if df is None or "dong" not in df.columns:
            continue
        bad = int(df["dong"].dropna().astype(str).str.contains("*", regex=False).sum())
        (rep.fail if bad else rep.ok)(where, f"{t} 동 이름에 가려진 숫자 없음", f"{bad:,}행")

    # 4. 행정동 미연결 비율 (stores → legal_admin_map → area_context)
    stores, lam, ac = present.get("stores"), present.get("legal_admin_map"), present.get("area_context")
    if stores is not None and lam is not None and ac is not None:
        m = stores[["gu", "dong"]].merge(lam[["gu", "legal_dong", "admin_dong"]],
                                         left_on=["gu", "dong"], right_on=["gu", "legal_dong"], how="left")
        m = m.merge(ac[["gu", "admin_dong"]].assign(_hit=True), on=["gu", "admin_dong"], how="left")
        if len(m) != len(stores):
            rep.fail(where, "행정동 결합 행 수 보존", f"{len(stores):,} → {len(m):,}")
        rate = float(m["_hit"].isna().mean())
        msg = f"{int(m['_hit'].isna().sum()):,} / {len(m):,} ({rate:.2%}, 경고 기준 {ADMIN_UNMATCHED_WARN:.1%})"
        (rep.warn if rate > ADMIN_UNMATCHED_WARN else rep.ok)(where, "행정동 미연결 비율", msg)

    # 5. 확률 범위·합
    for t, cols in PROB_COLS.items():
        df = present.get(t)
        if df is None:
            continue
        cols = [c for c in cols if c in df.columns]
        v = df[cols]
        out = int(((v < 0) | (v > 1)).any(axis=1).sum())
        nan = int(v.isna().any(axis=1).sum())
        (rep.fail if out or nan else rep.ok)(where, f"{t} 확률 0~1", f"범위 밖 {out:,} · 결측 {nan:,}")
        if len(cols) > 1:
            dev = float((v.sum(axis=1) - 1).abs().max())
            (rep.fail if dev > PROB_SUM_TOL else rep.ok)(where, f"{t} 확률 합 = 1", f"최대 오차 {dev:.1e}")

    # 6. 결과 표 기준일 = 인허가 기준일
    ref = str(meta.get("reference_date", ""))
    if not ref:
        rep.fail(where, "meta 기준일", "reference_date 없음")
    for t in ("vacancy_scores", "next_tenant_scores"):
        df = present.get(t)
        if df is not None and "data_reference_date" in df.columns:
            vals = sorted(df["data_reference_date"].astype(str).unique())
            (rep.ok if vals == [ref] else rep.warn)(where, f"{t} 기준일", f"{vals} vs 인허가 {ref}")


def read_db_url(env_file: Path | None) -> tuple[str, str]:
    """(접속 문자열, 사용한 키 이름). 환경변수 → .env 순, 읽기 전용 키 우선."""
    file_vals = {}
    if env_file and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep:
                file_vals[k.strip()] = v.strip().strip("\"'")
    for key in ("APP_READER_DATABASE_URL", "APP_DATABASE_URL"):
        val = os.environ.get(key, "").strip() or file_vals.get(key, "")
        if val:
            return val, key
    sys.exit("DB 접속 정보가 없습니다 (APP_READER_DATABASE_URL 또는 APP_DATABASE_URL).")


EXPECTED_PROJECT = "uoiamnbkzlvlskngataq"


def check_db(url: str, rep: Report, version: int | None = None) -> tuple[ds.Loaded, dict]:
    """버전 표 상태 확인 후 현재 버전(또는 전환 전 확인할 version)을 읽는다."""
    import psycopg

    if EXPECTED_PROJECT not in url:
        sys.exit("접속 대상이 공유 DB(uoiamnbkzlvlskngataq)가 아닙니다. 점검을 멈춥니다.")
    with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
        cur.execute(f"select version_id from {ds.SCHEMA}.current_version where singleton")
        row = cur.fetchone()
        cur.execute(f"select version_id, status, reference_date::text from {ds.SCHEMA}.dataset_versions "
                    f"order by version_id")
        versions = cur.fetchall()
        cur.execute("select pg_database_size(current_database())")
        size_mb = cur.fetchone()[0] / 2**20
    if not row:
        rep.fail("db", "current_version", "비어 있음")
        sys.exit(1)
    cur_v = row[0]
    status = {v: s for v, s, _ in versions}
    refs = {v: r for v, _, r in versions}
    currents = [v for v, s in status.items() if s == "current"]
    if currents == [cur_v]:
        rep.ok("db", "current_version 상태", f"v{cur_v} = 유일한 'current'")
    else:
        rep.fail("db", "current_version 상태", f"포인터 v{cur_v}, status='current' 버전 {currents}")
    prev = [v for v in status if v < cur_v and status[v] in ("retired", "current", "validated")]
    if prev:
        p = max(prev)
        (rep.ok if refs[cur_v] >= refs[p] else rep.fail)(
            "db", "기준일이 이전 버전보다 앞섬", f"v{cur_v} {refs[cur_v]} vs v{p} {refs[p]}")
    newer = [v for v in status if v > cur_v and status[v] in ("validated", "loading") and v != version]
    if newer:
        rep.warn("db", "현재보다 새 버전", f"전환 안 된 버전 {newer}")
    target = cur_v
    if version is not None and version != cur_v:
        st = status.get(version)
        if st != "validated":
            rep.fail("db", f"점검 대상 v{version} 상태", f"{st} (전환 전 점검은 'validated' 만)")
            return None, {"version": version, "statuses": status}
        (rep.ok if refs[version] >= refs[cur_v] else rep.fail)(
            "db", f"v{version} 기준일이 현재 버전보다 앞섬", f"v{version} {refs[version]} vs 현재 v{cur_v} {refs[cur_v]}")
        target = version
    retired = [v for v, s in status.items() if s == "retired"]
    (rep.warn if size_mb > DB_SIZE_WARN_MB else rep.ok)(
        "db", "DB 크기", f"{size_mb:,.0f}MB (경고 기준 {DB_SIZE_WARN_MB:,}MB) · retired 버전 {retired}")
    loaded = ds.load_db(url, target)
    return loaded, {"version": target, "statuses": status}


def compare(pq: ds.Loaded, db: ds.Loaded, rep: Report) -> None:
    """저장소 parquet(앱의 대체 출처)와 DB 현재 버전이 같은 배치인지."""
    a, b = str(pq.meta.get("reference_date")), str(db.meta.get("reference_date"))
    (rep.ok if a == b else rep.warn)("비교", "인허가 기준일 parquet = DB", f"{a} vs {b}")
    for t in ds.TABLES:
        x, y = pq.frames.get(t), db.frames.get(t)
        if x is None and y is None:
            continue
        nx, ny = (len(x) if x is not None else 0), (len(y) if y is not None else 0)
        if nx == ny:
            rep.ok("비교", f"{t} 행 수", f"{nx:,}")
        else:
            lv = rep.fail if ny < nx * (1 - SHRINK_WARN) or ny == 0 else rep.warn
            lv("비교", f"{t} 행 수", f"parquet {nx:,} vs DB {ny:,}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--processed", type=Path, default=SERVICE / "data/processed")
    ap.add_argument("--db", action="store_true", help="공유 DB 현재 버전도 점검하고 parquet 와 대조")
    ap.add_argument("--version", type=int, help="--db 와 함께: 현재 버전 대신 전환 전(validated) 버전을 점검")
    ap.add_argument("--env-file", type=Path, default=SERVICE.parent / ".env")
    ap.add_argument("--json", type=Path, help="결과를 JSON 으로도 저장")
    args = ap.parse_args()

    rep = Report()
    pq = ds.load_parquet(args.processed)
    check_frames(pq.frames, pq.meta, "parquet", rep)
    info = {}
    if args.db:
        url, key = read_db_url(args.env_file)
        print(f"DB 접속 키: {key}")
        db, info = check_db(url, rep, args.version)
        if db is not None:
            check_frames(db.frames, db.meta, "db", rep)
            compare(pq, db, rep)
    rep.print()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "parquet_reference_date": pq.meta.get("reference_date"),
            "db_version": info.get("version"),
            "summary": rep.summary(),
            "checks": [dict(zip(("where", "level", "name", "detail"), r)) for r in rep.rows],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if rep.failed else 0)


if __name__ == "__main__":
    main()
