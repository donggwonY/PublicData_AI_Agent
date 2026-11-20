"""배치 산출물(parquet 13개 + meta.json)을 Supabase(PostgreSQL)에 버전 단위로 적재한다.

흐름 (E-02 설계, docs/e02/README.md):
  1. dataset_versions 에 새 버전을 status='loading' 으로 만든다.
  2. 표마다 version_id 를 붙여 COPY 로 넣는다. 표가 없으면 parquet 자료형으로 만든다.
  3. 표별 행 수를 parquet 와 비교한다. 다르면 status='failed' 로 남기고 멈춘다.
  4. 통과하면 status='validated'. --activate 를 주면 current_version 한 줄만 바꿔 서비스 버전을 교체한다.

앱이 읽는 버전은 current_version 이 가리키는 하나뿐이라, 적재 도중 실패해도 서비스 데이터는 섞이지 않는다.
접속 정보는 환경변수 APP_DATABASE_URL(또는 --env-file 의 같은 키)에서 읽고 화면에 출력하지 않는다.

사용 예:
  python -m pipeline.load_supabase --processed data/processed --env-file ../.env --dry-run
  python -m pipeline.load_supabase --processed <폴더> --env-file ../.env --note "15업종 시험 적재"
  python -m pipeline.load_supabase --drop-retired 3 5 --env-file ../.env --dry-run   # 지울 retired 버전 확인

적재 전에 pipeline/check_data.py 의 계약 검사를 parquet 에 돌려 FAIL 이면 DB 에 접속하지 않는다(E-04 2단계).
DDL·전환·삭제는 잠금을 LOCK_TIMEOUT 만큼만 기다린다. 앱의 읽기 연결이 표를 잡고 있으면 오래 매달리지 않고 실패한다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

from pipeline.check_data import Report, check_frames

SCHEMA = "app"
TABLES = ["stores", "units", "transitions", "area_year", "area_cycle", "survival", "vacancy_area",
          "poi", "area_context", "legal_admin_map", "station_traffic", "parking", "market",
          "vacancy_scores",  # E-03 공실 재입점 점수(오프라인 모델 결과, 2026-11-12 v6부터)
          "competition_forecast",  # E-06 구×업종 앞으로 1년 폐업 예측(오프라인 모델 결과, docs/e06)
          "population_forecast", "similar_areas",  # A-07 1년 뒤 거주 인구·A-09 비슷한 동네(scripts/area_outlook_export.py)
          "next_tenant_scores"]  # E-09 다음 가게 업종 확률(scripts/e09_next_tenant/export_service_scores.py)
# 기본 키(version_id 와 함께). D-02 결합 계약: 인허가는 org_code + service + mgmt_no, 자리는 uid.
PRIMARY_KEYS = {"stores": ["org_code", "service", "mgmt_no"], "units": ["uid"], "vacancy_scores": ["uid"],
                "competition_forecast": ["gu", "category"], "population_forecast": ["admin_code", "age_band"],
                "similar_areas": ["admin_code", "option", "rank"], "next_tenant_scores": ["uid"]}
INDEXES = {"stores": [["uid"], ["gu", "dong"]], "units": [["gu", "dong"]], "transitions": [["uid"]]}
LOCK_TIMEOUT = "15s"
# 적재 중 DB 크기 상한(MB). Pro 플랜 디스크 8GB, v10 적재 뒤 1,914MB. check_data 경고선(2,500MB)보다 위에서 멈춘다.
MAX_DB_MB = 3000


def pg_type(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "timestamp"
    if pd.api.types.is_integer_dtype(s):
        return "bigint"
    if pd.api.types.is_float_dtype(s):
        return "double precision"
    return "text"


def ddl(table: str, df: pd.DataFrame) -> list[str]:
    cols = ",\n  ".join(f'"{c}" {pg_type(df[c])}' for c in df.columns)
    # _row: parquet 의 원래 행 순서. 앱이 같은 순서로 읽어야 동률 정렬·first() 결과가 parquet 와 같다.
    stmts = [f'create table if not exists {SCHEMA}."{table}" (\n  version_id bigint not null '
             f'references {SCHEMA}.dataset_versions(version_id) on delete cascade,\n  "_row" bigint,\n  {cols}'
             + (f',\n  primary key (version_id, {", ".join(chr(34) + k + chr(34) for k in PRIMARY_KEYS[table])})'
                if table in PRIMARY_KEYS else "") + "\n)"]
    stmts.append(f'alter table {SCHEMA}."{table}" add column if not exists "_row" bigint')  # _row 도입 전에 만든 표
    # 새 버전에 열이 늘어난 경우(예: 42종 확장의 stores.occupant_id·is_primary, 2026-11-09) 기존 표에 열을 더한다.
    # 이전 버전 행에는 NULL 이 들어가며, 앱은 버전별 dtypes 로 읽으므로 이전 버전 조회에는 영향이 없다.
    for c in df.columns:
        stmts.append(f'alter table {SCHEMA}."{table}" add column if not exists "{c}" {pg_type(df[c])}')
    stmts.append(f'create index if not exists "{table}_version_row_idx" on {SCHEMA}."{table}" (version_id, "_row")')
    for cols_ in INDEXES.get(table, []):
        name = f'{table}_{"_".join(cols_)}_idx'
        stmts.append(f'create index if not exists "{name}" on {SCHEMA}."{table}" '
                     f'(version_id, {", ".join(chr(34) + c + chr(34) for c in cols_)})')
    # 공개 키(anon·authenticated)로는 읽을 수 없게 한다. 앱은 서버에서 접속 정보로만 읽는다.
    stmts.append(f'alter table {SCHEMA}."{table}" enable row level security')
    stmts.append(f'revoke all on {SCHEMA}."{table}" from anon, authenticated')
    return stmts


BASE_DDL = [
    f"create schema if not exists {SCHEMA}",
    f"revoke all on schema {SCHEMA} from anon, authenticated",
    f"""create table if not exists {SCHEMA}.dataset_versions (
  version_id bigint generated always as identity primary key,
  status text not null check (status in ('loading', 'validated', 'failed', 'current', 'retired')),
  reference_date date,
  built_at timestamp,
  services text[],
  note text,
  meta jsonb,
  row_counts jsonb,
  created_at timestamptz not null default now(),
  finished_at timestamptz
)""",
    f"""create table if not exists {SCHEMA}.current_version (
  singleton boolean primary key default true check (singleton),
  version_id bigint not null references {SCHEMA}.dataset_versions(version_id),
  switched_at timestamptz not null default now()
)""",
    # jsonb 는 키 순서를 바꾼다. 앱 문구(업종 목록 등)가 parquet 경로와 같도록 원문 JSON 과 pandas 자료형을 따로 둔다.
    f"alter table {SCHEMA}.dataset_versions add column if not exists meta_text text",
    f"alter table {SCHEMA}.dataset_versions add column if not exists dtypes jsonb",
    f"alter table {SCHEMA}.dataset_versions enable row level security",
    f"alter table {SCHEMA}.current_version enable row level security",
    f"revoke all on {SCHEMA}.dataset_versions, {SCHEMA}.current_version from anon, authenticated",
]


READER_ROLE = "app_reader"  # 공개 앱 전용 읽기 계정. 로그인 비밀번호는 DB 에서 따로 정하고 Streamlit Secrets 에만 둔다.


def reader_grants() -> list[str]:
    """app 스키마의 모든 표를 READER_ROLE 이 읽기만 할 수 있게 한다. --fresh 로 표를 다시 만들 때마다 다시 적용해야 한다."""
    stmts = [f"""do $$ begin
  if not exists (select 1 from pg_roles where rolname = '{READER_ROLE}') then create role {READER_ROLE} nologin; end if;
end $$""",
             f"grant usage on schema {SCHEMA} to {READER_ROLE}"]
    # 정책은 없을 때만 만든다. 예전처럼 매번 지우고 다시 만들면 앱의 읽기 연결과 잠금이 부딪힌다(v6 첫 전환 시간 초과).
    for t in TABLES + ["dataset_versions", "current_version"]:
        stmts += [f'grant select on {SCHEMA}."{t}" to {READER_ROLE}',
                  f"do $$ begin\n"
                  f"  if not exists (select 1 from pg_policies where schemaname = '{SCHEMA}' and tablename = '{t}'\n"
                  f"                 and policyname = '{READER_ROLE}_select') then\n"
                  f'    create policy {READER_ROLE}_select on {SCHEMA}."{t}" for select to {READER_ROLE} using (true);\n'
                  f"  end if;\nend $$"]
    return stmts


def missing_reader_access(cur) -> list[str]:
    """READER_ROLE 이 읽을 수 없는 표(권한 또는 정책 없음)."""
    cur.execute("select tablename from pg_policies where schemaname = %s and policyname = %s",
                (SCHEMA, f"{READER_ROLE}_select"))
    with_policy = {r[0] for r in cur.fetchall()}
    out = []
    for t in TABLES + ["dataset_versions", "current_version"]:
        cur.execute("select has_table_privilege(%s, %s, 'select')", (READER_ROLE, f'{SCHEMA}."{t}"'))
        if not cur.fetchone()[0] or t not in with_policy:
            out.append(t)
    return out


def precheck(frames: dict, meta: dict) -> Report:
    """적재 전 parquet 계약 검사(check_data). FAIL 이면 적재하지 않는다."""
    rep = Report()
    check_frames(frames, meta, "parquet", rep)
    return rep


def deletable(statuses: dict[int, str], requested: list[int]) -> tuple[list[int], dict[int, str]]:
    """지울 수 있는 retired·failed 버전과 거절 사유. 현재 버전과 가장 최근 retired(되돌릴 대상)는 요청해도 지우지 않는다."""
    retired = sorted(v for v, st in statuses.items() if st == "retired")
    keep = retired[-1] if retired else None
    ok, refused = [], {}
    for v in requested:
        st = statuses.get(v)
        if st not in ("retired", "failed"):
            refused[v] = f"status={st}"
        elif v == keep:
            refused[v] = "가장 최근 retired(되돌릴 대상)라 보존"
        else:
            ok.append(v)
    return ok, refused


def read_url(env_file: Path | None) -> str:
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url and env_file and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == "APP_DATABASE_URL":
                url = v.strip().strip("\"'")
    if not url:
        sys.exit("APP_DATABASE_URL 이 없습니다 (.env 또는 환경변수).")
    return url


def copy_frame(cur, table: str, df: pd.DataFrame, version_id: int) -> None:
    out = df.copy()
    out.insert(0, "_row", range(len(out)))
    out.insert(0, "version_id", version_id)
    for c in out.columns:
        if pd.api.types.is_bool_dtype(out[c]):
            out[c] = out[c].map({True: "t", False: "f"})
    buf = io.StringIO()
    out.to_csv(buf, index=False, header=False, na_rep="\\N", date_format="%Y-%m-%d %H:%M:%S")
    buf.seek(0)
    cols = ", ".join(f'"{c}"' for c in out.columns)
    with cur.copy(f'copy {SCHEMA}."{table}" ({cols}) from stdin with (format csv, null \'\\N\')') as cp:
        while chunk := buf.read(1 << 20):
            cp.write(chunk)


def activate_existing(url: str, version_id: int) -> None:
    """검증된 버전을 current_version 으로 지정한다. 한 트랜잭션이라 앱은 이전 버전 또는 새 버전 중 하나만 본다."""
    import psycopg

    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(f"set lock_timeout = '{LOCK_TIMEOUT}'")
        missing = missing_reader_access(cur)
        if missing:  # 권한은 적재 때 준다. 전환에서는 다시 만들지 않고 확인만 한다.
            sys.exit(f"{READER_ROLE} 이 읽을 수 없는 표가 있어 전환하지 않습니다: {missing}")
        cur.execute(f"select status from {SCHEMA}.dataset_versions where version_id = %s", (version_id,))
        row = cur.fetchone()
        if not row or row[0] not in ("validated", "current"):
            sys.exit(f"버전 {version_id} 은 지정할 수 없습니다 (status={row and row[0]}).")
        cur.execute(f"update {SCHEMA}.dataset_versions set status='retired' where status='current' and version_id <> %s",
                    (version_id,))
        cur.execute(f"""insert into {SCHEMA}.current_version (singleton, version_id) values (true, %s)
                        on conflict (singleton) do update set version_id = excluded.version_id, switched_at = now()""",
                    (version_id,))
        cur.execute(f"update {SCHEMA}.dataset_versions set status='current' where version_id = %s", (version_id,))
        conn.commit()
    print(f"현재 서비스 버전 = {version_id} · {READER_ROLE} 읽기 권한 확인")


def drop_retired(url: str, requested: list[int], dry_run: bool) -> None:
    """retired 버전을 지운다(모든 데이터 표에서 cascade). 디스크 공간은 vacuum 뒤 재사용된다(OS 로 바로 돌려주지 않음)."""
    import psycopg

    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(f"set lock_timeout = '{LOCK_TIMEOUT}'")
        cur.execute(f"select version_id, status, row_counts from {SCHEMA}.dataset_versions")
        rows = cur.fetchall()
        statuses = {v: st for v, st, _ in rows}
        counts = {v: rc for v, _, rc in rows}
        ok, refused = deletable(statuses, requested)
        for v, why in refused.items():
            print(f"  v{v} 지우지 않음: {why}")
        for v in ok:
            n = sum(c["db"] for c in (counts[v] or {}).values())
            print(f"  v{v} {'지울 예정' if dry_run else '삭제'}: {n:,}행")
        if dry_run or not ok:
            print("변경 없음" + (" (--dry-run)" if dry_run else ""))
            return
        cur.execute(f"delete from {SCHEMA}.dataset_versions where version_id = any(%s)", (ok,))
        conn.commit()
        cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
        print(f"삭제 완료 {ok} · DB 크기 {cur.fetchone()[0]} (공간은 vacuum 뒤 재사용)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--processed", type=Path, help="적재할 배치 산출물 폴더 (--activate-version 만 할 때는 생략)")
    ap.add_argument("--activate-version", type=int,
                    help="적재하지 않고, 이미 검증된(validated) 버전을 현재 서비스 버전으로 지정한다")
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--note", default="")
    ap.add_argument("--dry-run", action="store_true", help="DB에 접속하지 않고 생성할 DDL만 출력")
    ap.add_argument("--activate", action="store_true", help="검증 통과 시 current_version 을 새 버전으로 교체")
    ap.add_argument("--fresh", action="store_true",
                    help=f"적재 전에 {SCHEMA} 스키마를 통째로 지운다(기존 버전 전부 삭제). 무료 플랜은 행 삭제로 디스크가 줄지 않아 "
                         "한 버전만 유지할 때 쓴다. 되돌리기는 저장소의 parquet 로 다시 적재한다")
    ap.add_argument("--start-version", type=int, help="--fresh 와 함께: 새로 만든 버전 번호의 시작값")
    ap.add_argument("--drop-retired", type=int, nargs="+", metavar="VERSION",
                    help="retired·failed 버전 삭제(현재·가장 최근 retired 는 보호). --dry-run 이면 확인만")
    ap.add_argument("--max-db-mb", type=float, default=MAX_DB_MB,
                    help="표를 하나 넣을 때마다 DB 크기를 확인해 이 값을 넘으면 중단(무료 플랜 500MB 대비 여유)")
    args = ap.parse_args()

    if args.drop_retired:
        drop_retired(read_url(args.env_file), args.drop_retired, args.dry_run)
        return
    if args.activate_version is not None:
        activate_existing(read_url(args.env_file), args.activate_version)
        return
    if args.processed is None:
        ap.error("--processed 가 필요합니다.")

    meta = json.loads((args.processed / "meta.json").read_text(encoding="utf-8"))
    frames = {t: pd.read_parquet(args.processed / f"{t}.parquet") for t in TABLES}
    rep = precheck(frames, meta)
    for _, lv, name, detail in rep.rows:
        if lv != "OK":
            print(f"  사전 점검 [{lv}] {name} — {detail}")
    s = rep.summary()
    if rep.failed:
        sys.exit("사전 점검 FAIL: 적재하지 않습니다 (python -m pipeline.check_data 로 확인).")
    print(f"사전 점검 통과 (OK {s['OK']} · WARN {s['WARN']})")
    stmts = BASE_DDL + [s for t in TABLES for s in ddl(t, frames[t])]
    if args.dry_run:
        print(";\n\n".join(stmts) + ";")
        print(f"\n-- rows: " + ", ".join(f"{t}={len(frames[t]):,}" for t in TABLES))
        return

    import psycopg  # 적재할 때만 필요 (requirements-dev)

    url = read_url(args.env_file)
    t0 = time.time()
    with psycopg.connect(url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(f"set lock_timeout = '{LOCK_TIMEOUT}'")
            if args.fresh:
                cur.execute(f"drop schema if exists {SCHEMA} cascade")
                print(f"{SCHEMA} 스키마를 비웠습니다(--fresh).")
            for s in stmts + reader_grants():
                cur.execute(s)
            if args.fresh and args.start_version:
                cur.execute(f"alter table {SCHEMA}.dataset_versions alter column version_id restart with %s"
                            % int(args.start_version))
            meta_text = json.dumps(meta, ensure_ascii=False, default=str)
            dtypes = {t: {c: str(frames[t][c].dtype) for c in frames[t].columns} for t in TABLES}
            cur.execute(f"""insert into {SCHEMA}.dataset_versions
                              (status, reference_date, built_at, services, note, meta, meta_text, dtypes)
                            values ('loading', %s, %s, %s, %s, %s, %s, %s) returning version_id""",
                        (meta["reference_date"], meta["built_at"], [k for k in meta["records"] if k != "통합"],
                         args.note, meta_text, meta_text, json.dumps(dtypes)))
            version_id = cur.fetchone()[0]
        conn.commit()
        print(f"version_id={version_id} 적재 시작")

        counts, ok = {}, True
        try:
            with conn.cursor() as cur:
                for t in TABLES:
                    t1 = time.time()
                    copy_frame(cur, t, frames[t], version_id)
                    cur.execute(f'select count(*) from {SCHEMA}."{t}" where version_id = %s', (version_id,))
                    n = cur.fetchone()[0]
                    counts[t] = {"db": n, "parquet": len(frames[t])}
                    ok &= n == len(frames[t])
                    cur.execute("select pg_database_size(current_database())")
                    mb = cur.fetchone()[0] / 2**20
                    print(f"  {t:16} {n:>8,} / {len(frames[t]):>8,}  {time.time() - t1:5.1f}s  DB {mb:.0f}MB")
                    if mb > args.max_db_mb:
                        raise RuntimeError(f"DB 크기 {mb:.0f}MB 가 한도 {args.max_db_mb:.0f}MB 를 넘어 적재를 중단합니다.")
            conn.commit()
        except Exception:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(f"update {SCHEMA}.dataset_versions set status='failed', finished_at=now() where version_id=%s",
                            (version_id,))
            conn.commit()
            raise

        with conn.cursor() as cur:
            cur.execute(f"update {SCHEMA}.dataset_versions set status=%s, row_counts=%s, finished_at=now() "
                        f"where version_id=%s", ("validated" if ok else "failed", json.dumps(counts), version_id))
            if ok and args.activate:
                cur.execute(f"update {SCHEMA}.dataset_versions set status='retired' "
                            f"where status='current'")
                cur.execute(f"""insert into {SCHEMA}.current_version (singleton, version_id) values (true, %s)
                                on conflict (singleton) do update set version_id = excluded.version_id, switched_at = now()""",
                            (version_id,))
                cur.execute(f"update {SCHEMA}.dataset_versions set status='current' where version_id=%s", (version_id,))
            cur.execute("select pg_size_pretty(pg_database_size(current_database()))")
            size = cur.fetchone()[0]
        conn.commit()
    print(f"{'검증 통과' if ok else '행 수 불일치 → failed'} · {'현재 버전으로 교체' if ok and args.activate else '교체 안 함'}"
          f" · DB 크기 {size} · {time.time() - t0:.0f}s")
    if not ok:
        sys.exit(1)
    if not args.activate:
        print(f"전환 전 점검: python -m pipeline.check_data --db --version {version_id}")


if __name__ == "__main__":
    main()
