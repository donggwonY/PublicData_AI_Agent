"""배치 산출물(parquet)을 파일 그대로 Supabase 에 버전별로 올린다 — 무료 플랜 운영용 (2026-11-27).

행 단위 표(`app` 스키마, load_supabase.py)는 한 버전이 약 350~570MB, 앱 시작마다 CSV 약 195MB 를 받는다.
무료 플랜(500MB·월 전송 5GB)에서는 빠듯하므로, 같은 parquet 파일을 `app_files.files` 에 bytea 로 저장한다.
한 버전 약 34MB 이고, 앱은 파일을 받아 바로 pd.read_parquet 한다(core/datasource.py load_db_files).

대상은 pubdai 프로젝트(ihaypnmvrnvbjdbtgiaq)만 허용한다. 공유 DB(uoiamnbkzlvlskngataq)는 행 단위 표를 계속 쓴다.

    python -m pipeline.load_parquet_files --processed data/processed --version 16 --env-file ../.env --dry-run
    python -m pipeline.load_parquet_files --processed data/processed --version 16 --env-file ../.env
    python -m pipeline.load_parquet_files --activate-version 16 --env-file ../.env
    python -m pipeline.load_parquet_files --grant-reader app_reader --env-file ../.env   # 읽기 권한만 부여

접속 문자열은 프로세스 환경변수 PUBDAI_DATABASE_URL > --env-file 의 같은 키 순서로 읽는다. 값은 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import datasource as ds  # noqa: E402

SCHEMA = ds.FILES_SCHEMA
URL_KEY = "PUBDAI_DATABASE_URL"
TARGET_PROJECT = "ihaypnmvrnvbjdbtgiaq"     # pubdai(무료, 서울)
FORBIDDEN_PROJECT = "uoiamnbkzlvlskngataq"  # 공유 DB(Pro) — 이 스크립트로는 쓰지 않는다
MAX_DB_MB = 450                             # 무료 500MB 대비 여유

DDL = f"""
create schema if not exists {SCHEMA};
create table if not exists {SCHEMA}.versions (
  version_id integer primary key,
  status text not null check (status in ('loading', 'validated', 'current', 'retired', 'failed')),
  meta jsonb not null,
  meta_text text not null,
  note text,
  created_at timestamptz not null default now()
);
create table if not exists {SCHEMA}.files (
  version_id integer not null references {SCHEMA}.versions(version_id) on delete cascade,
  table_name text not null,
  sha256 text not null,
  n_rows bigint not null,
  n_bytes bigint not null,
  data bytea not null,
  primary key (version_id, table_name)
);
create table if not exists {SCHEMA}.current_version (
  singleton boolean primary key default true check (singleton),
  version_id integer not null references {SCHEMA}.versions(version_id)
);
"""


def read_url(env_file: Path | None) -> str:
    url = os.environ.get(URL_KEY, "").strip()
    if not url and env_file and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{URL_KEY}="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        sys.exit(f"{URL_KEY} 가 없습니다. pubdai 프로젝트의 관리자 접속 문자열을 .env 에 넣어 주세요(값은 출력하지 않음).")
    check_target(url)
    return url


def check_target(url: str) -> None:
    """pubdai 가 아닌 곳(특히 공유 DB)에 쓰지 않게 막는다."""
    if FORBIDDEN_PROJECT in url:
        sys.exit("공유 DB(uoiamn…) 접속 문자열입니다. 이 스크립트는 pubdai 프로젝트에만 씁니다.")
    if TARGET_PROJECT not in url:
        sys.exit("접속 문자열에 pubdai 프로젝트 ID(ihaypn…)가 없습니다. 대상 확인 후 다시 실행하세요.")


def collect(processed: Path) -> tuple[dict, str, list[dict]]:
    """올릴 파일 목록: 표 이름·바이트·해시·행 수. 필수 표가 없으면 멈춘다."""
    meta_text = (processed / "meta.json").read_text(encoding="utf-8")
    meta = json.loads(meta_text)
    files = []
    for t in ds.TABLES:
        p = processed / f"{t}.parquet"
        if not p.exists():
            if t in ds.REQUIRED:
                sys.exit(f"필수 표 {t}.parquet 가 없습니다.")
            continue
        b = p.read_bytes()
        files.append({"table": t, "bytes": b, "sha256": hashlib.sha256(b).hexdigest(),
                      "rows": len(pd.read_parquet(io.BytesIO(b))), "n_bytes": len(b)})
    return meta, meta_text, files


def upload(url: str, processed: Path, version: int, note: str, dry_run: bool) -> None:
    meta, meta_text, files = collect(processed)
    total_mb = sum(f["n_bytes"] for f in files) / 1e6
    print(f"올릴 버전 v{version} · 기준일 {meta.get('reference_date')} · 배치 {meta.get('built_at')} · "
          f"파일 {len(files)}개 {total_mb:.1f}MB")
    for f in files:
        print(f"  {f['table']:22s} {f['rows']:>9,}행 {f['n_bytes'] / 1e6:6.2f}MB {f['sha256'][:12]}")
    if dry_run:
        print("변경 없음 (--dry-run)")
        return
    import psycopg

    with psycopg.connect(url, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute("select current_user, pg_database_size(current_database())")
        user, size = cur.fetchone()
        print(f"접속 계정 {user} · 적재 전 DB 크기 {size / 1e6:.0f}MB")
        if size / 1e6 + total_mb > MAX_DB_MB:
            sys.exit(f"적재 후 약 {size / 1e6 + total_mb:.0f}MB 로 상한 {MAX_DB_MB}MB 를 넘습니다. 중단.")
        cur.execute(DDL)
        cur.execute(f"select status from {SCHEMA}.versions where version_id = %s", (version,))
        if cur.fetchone():
            sys.exit(f"v{version} 이 이미 있습니다. 다른 번호를 쓰거나 기존 버전을 먼저 정리하세요.")
        cur.execute(f"insert into {SCHEMA}.versions (version_id, status, meta, meta_text, note) "
                    f"values (%s, 'loading', %s, %s, %s)", (version, json.dumps(meta, ensure_ascii=False), meta_text, note))
        for f in files:
            cur.execute(f"insert into {SCHEMA}.files (version_id, table_name, sha256, n_rows, n_bytes, data) "
                        f"values (%s, %s, %s, %s, %s, %s)",
                        (version, f["table"], f["sha256"], f["rows"], f["n_bytes"], f["bytes"]))
        # 서버에 저장된 바이트의 해시를 다시 계산해 보낸 파일과 대조한다
        cur.execute(f"select table_name, encode(sha256(data), 'hex'), octet_length(data) from {SCHEMA}.files "
                    f"where version_id = %s", (version,))
        got = {t: (h, n) for t, h, n in cur.fetchall()}
        bad = [f["table"] for f in files if got.get(f["table"]) != (f["sha256"], f["n_bytes"])]
        if bad or len(got) != len(files):
            conn.rollback()
            sys.exit(f"서버 해시 불일치로 되돌림: {bad or '파일 수 다름'}")
        cur.execute(f"update {SCHEMA}.versions set status = 'validated' where version_id = %s", (version,))
        conn.commit()
        cur.execute("select pg_database_size(current_database())")
        print(f"v{version} 적재·해시 검증 완료(validated) · DB 크기 {cur.fetchone()[0] / 1e6:.0f}MB")

    # 앱과 같은 읽기 경로로 다시 읽어 저장소 parquet 와 표 단위로 같은지 확인한다
    loaded = ds.load_db_files(url, version)
    local = ds.load_parquet(processed)
    for t in ds.TABLES:
        a, b = local.frames.get(t), loaded.frames.get(t)
        if (a is None) != (b is None) or (a is not None and not a.equals(b)):
            sys.exit(f"재조회 불일치: {t}")
    print(f"재조회 일치: 표 {sum(f is not None for f in loaded.frames.values())}개 · "
          f"{loaded.seconds:.1f}초 · {loaded.bytes_read / 1e6:.1f}MB 수신")


def activate(url: str, version: int) -> None:
    import psycopg

    with psycopg.connect(url, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute(f"select status from {SCHEMA}.versions where version_id = %s", (version,))
        row = cur.fetchone()
        if not row or row[0] not in ("validated", "current"):
            sys.exit(f"v{version} 이 없거나 검증되지 않았습니다(status={row and row[0]}).")
        cur.execute(f"update {SCHEMA}.versions set status = 'retired' where status = 'current' and version_id <> %s",
                    (version,))
        cur.execute(f"update {SCHEMA}.versions set status = 'current' where version_id = %s", (version,))
        cur.execute(f"insert into {SCHEMA}.current_version (singleton, version_id) values (true, %s) "
                    f"on conflict (singleton) do update set version_id = excluded.version_id", (version,))
        conn.commit()
    print(f"현재 버전 → v{version}")


def grant_reader(url: str, role: str) -> None:
    """읽기 전용 역할에 이 스키마 조회 권한만 준다. 역할 생성·로그인·비밀번호는 다루지 않는다."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(url, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute("select rolcanlogin from pg_roles where rolname = %s", (role,))
        row = cur.fetchone()
        if not row:
            sys.exit(f"역할 {role} 이 없습니다. 역할 생성은 이 스크립트가 하지 않습니다.")
        r, s = sql.Identifier(role), sql.Identifier(SCHEMA)
        cur.execute(sql.SQL("grant usage on schema {} to {}").format(s, r))
        cur.execute(sql.SQL("grant select on all tables in schema {} to {}").format(s, r))
        conn.commit()
    print(f"{role}: {SCHEMA} 조회 권한 부여 (로그인 가능: {row[0]})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--processed", type=Path)
    ap.add_argument("--version", type=int, help="올릴 버전 번호(공유 DB 버전 번호와 맞춘다)")
    ap.add_argument("--activate-version", type=int)
    ap.add_argument("--grant-reader", metavar="ROLE")
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--note", default="")
    ap.add_argument("--dry-run", action="store_true", help="DB 에 접속하지 않고 올릴 파일만 확인")
    a = ap.parse_args()
    if a.processed and a.version is not None:
        url = "" if a.dry_run else read_url(a.env_file)
        upload(url, a.processed, a.version, a.note, a.dry_run)
    if a.activate_version is not None:
        activate(read_url(a.env_file), a.activate_version)
    if a.grant_reader:
        grant_reader(read_url(a.env_file), a.grant_reader)
    if not ((a.processed and a.version is not None) or a.activate_version is not None or a.grant_reader):
        ap.print_help()


if __name__ == "__main__":
    main()
