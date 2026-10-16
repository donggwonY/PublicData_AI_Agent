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

SCHEMA = "app"
TABLES = ["stores", "units", "transitions", "area_year", "area_cycle", "survival", "vacancy_area",
          "poi", "area_context", "legal_admin_map", "station_traffic", "parking", "market"]
# 기본 키(version_id 와 함께). D-02 결합 계약: 인허가는 org_code + service + mgmt_no, 자리는 uid.
PRIMARY_KEYS = {"stores": ["org_code", "service", "mgmt_no"], "units": ["uid"]}
INDEXES = {"stores": [["uid"], ["gu", "dong"]], "units": [["gu", "dong"]], "transitions": [["uid"]]}


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
    for t in TABLES + ["dataset_versions", "current_version"]:
        stmts += [f'grant select on {SCHEMA}."{t}" to {READER_ROLE}',
                  f'drop policy if exists {READER_ROLE}_select on {SCHEMA}."{t}"',
                  f'create policy {READER_ROLE}_select on {SCHEMA}."{t}" for select to {READER_ROLE} using (true)']
    return stmts


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
        for s in reader_grants():
            cur.execute(s)
        conn.commit()
    print(f"현재 서비스 버전 = {version_id} · {READER_ROLE} 읽기 권한 적용")


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
    ap.add_argument("--max-db-mb", type=float, default=450,
                    help="표를 하나 넣을 때마다 DB 크기를 확인해 이 값을 넘으면 중단(무료 플랜 500MB 대비 여유)")
    args = ap.parse_args()

    if args.activate_version is not None:
        activate_existing(read_url(args.env_file), args.activate_version)
        return
    if args.processed is None:
        ap.error("--processed 가 필요합니다.")

    meta = json.loads((args.processed / "meta.json").read_text(encoding="utf-8"))
    frames = {t: pd.read_parquet(args.processed / f"{t}.parquet") for t in TABLES}
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


if __name__ == "__main__":
    main()
