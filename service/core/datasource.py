"""데이터 출처 선택: Supabase(app 스키마) 또는 저장소의 parquet.

환경변수로 고른다 (배포에서는 app.py 가 Streamlit Secrets 의 같은 이름을 환경변수로 옮긴다).
    APP_DATA_SOURCE   auto(기본) | db | parquet
                      auto = APP_DATABASE_URL 이 있으면 DB, 실패하면 parquet 로 대체
                      db   = DB 만 사용(실패하면 오류) — 검증용
    APP_DATABASE_URL  Supabase Postgres 접속 문자열(비밀값, 출력하지 않는다)
    APP_DATA_VERSION  읽을 버전 번호. 없으면 app.current_version 이 가리키는 버전

DB 의 표는 pipeline/load_supabase.py 가 parquet 를 그대로 옮긴 것이다. 원래 행 순서는 _row 로 보존하고,
자료형은 Postgres 형식에서 parquet 와 같은 pandas 형식으로 되돌린다.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

SCHEMA = "app"
REQUIRED = ["stores", "units", "transitions", "area_cycle", "area_year", "survival", "vacancy_area"]
OPTIONAL = ["poi", "area_context", "legal_admin_map", "station_traffic", "parking", "market"]
TABLES = REQUIRED + OPTIONAL


@dataclass
class Loaded:
    frames: dict[str, pd.DataFrame | None]
    meta: dict
    source: str                      # "parquet" 또는 "db v<번호>"
    seconds: float = 0.0
    bytes_read: int = 0              # DB 에서 받은 CSV 바이트 수(전송량 근사)
    notes: list[str] = field(default_factory=list)


def load_parquet(processed_dir: Path) -> Loaded:
    t0 = time.time()
    if not (processed_dir / "meta.json").exists():
        raise FileNotFoundError(f"{processed_dir} 에 배치 산출물이 없습니다. `python -m pipeline.build` 를 먼저 실행하세요.")
    frames = {}
    for t in TABLES:
        path = processed_dir / f"{t}.parquet"
        if t in REQUIRED or path.exists():
            frames[t] = pd.read_parquet(path)
        else:
            frames[t] = None
    meta = json.loads((processed_dir / "meta.json").read_text(encoding="utf-8"))
    return Loaded(frames, meta, "parquet", time.time() - t0)


_PG_TO_PANDAS = {"boolean": "bool", "bigint": "int64", "double precision": "float64",
                 "timestamp without time zone": "datetime", "text": "str"}


def load_db(url: str, version: int | None = None) -> Loaded:
    import psycopg  # DB 를 쓸 때만 필요

    t0, total = time.time(), 0
    with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
        cur.execute("set extra_float_digits = 3")  # double 값을 잘림 없이 내보낸다(좌표 등)
        if version is None:
            cur.execute(f"select version_id from {SCHEMA}.current_version where singleton")
            row = cur.fetchone()
            if not row:
                raise LookupError("app.current_version 이 비어 있습니다. 적재 후 --activate 또는 APP_DATA_VERSION 을 지정하세요.")
            version = row[0]
        cur.execute(f"select status, meta, meta_text, dtypes from {SCHEMA}.dataset_versions where version_id = %s",
                    (version,))
        row = cur.fetchone()
        if not row or row[0] not in ("validated", "current"):
            raise LookupError(f"버전 {version} 이 없거나 검증되지 않았습니다 (status={row and row[0]}).")
        meta = json.loads(row[2]) if row[2] else row[1]   # meta_text 는 키 순서를 보존한 원문
        dtypes = row[3] or {}
        cur.execute("""select table_name, column_name, data_type from information_schema.columns
                       where table_schema = %s order by table_name, ordinal_position""", (SCHEMA,))
        cols: dict[str, list[tuple[str, str]]] = {}
        for t, c, dt in cur.fetchall():
            cols.setdefault(t, []).append((c, dt))
        frames: dict[str, pd.DataFrame | None] = {}
        for t in TABLES:
            spec = [(c, dt) for c, dt in cols.get(t, []) if c not in ("version_id", "_row")]
            if not spec:
                if t in REQUIRED:
                    raise LookupError(f"{SCHEMA}.{t} 표가 없습니다.")
                frames[t] = None
                continue
            order = '"_row"' if any(c == "_row" for c, _ in cols[t]) else "1"
            sel = ", ".join(f'"{c}"' for c, _ in spec)
            buf = io.BytesIO()
            with cur.copy(f'copy (select {sel} from {SCHEMA}."{t}" where version_id = {int(version)} '
                          f"order by {order}) to stdout with (format csv, header true, null '\\N')") as cp:
                for chunk in cp:
                    buf.write(chunk)
            total += buf.tell()
            buf.seek(0)
            frames[t] = _restore_dtypes(_read_csv(buf, spec), dtypes.get(t, {}))
    return Loaded(frames, meta, f"db v{version}", time.time() - t0, total)


def _restore_dtypes(df: pd.DataFrame, want: dict[str, str]) -> pd.DataFrame:
    """적재 때 기록한 pandas 자료형으로 맞춘다(예: 결측 허용 불리언 'boolean')."""
    for c, dt in want.items():
        if c in df.columns and str(df[c].dtype) != dt:
            df[c] = df[c].astype(dt)
    return df


def _read_csv(buf: io.BytesIO, spec: list[tuple[str, str]]) -> pd.DataFrame:
    """COPY 로 받은 CSV → parquet 와 같은 pandas 자료형."""
    kinds = {c: _PG_TO_PANDAS.get(dt, "str") for c, dt in spec}
    df = pd.read_csv(buf, na_values=["\\N"], keep_default_na=False, encoding="utf-8", float_precision="round_trip",
                     dtype={c: ("str" if k in ("str", "bool", "datetime") else k) for c, k in kinds.items()
                            if k != "int64"})
    for c, k in kinds.items():
        if k == "bool":
            df[c] = df[c].map({"t": True, "f": False})
            if df[c].notna().all():
                df[c] = df[c].astype(bool)
        elif k == "datetime":
            df[c] = pd.to_datetime(df[c], format="%Y-%m-%d %H:%M:%S", errors="raise")
        elif k == "int64" and df[c].isna().any():
            df[c] = df[c].astype("float64")
    return df


def load(processed_dir: Path) -> Loaded:
    """환경변수에 따라 DB 또는 parquet 에서 읽는다. auto 모드에서 DB 가 실패하면 parquet 로 대체한다."""
    mode = os.environ.get("APP_DATA_SOURCE", "auto").strip().lower()
    url = os.environ.get("APP_DATABASE_URL", "").strip()
    version = os.environ.get("APP_DATA_VERSION", "").strip()
    if mode == "parquet" or (mode == "auto" and not url):
        return load_parquet(processed_dir)
    if not url:
        raise RuntimeError("APP_DATA_SOURCE=db 인데 APP_DATABASE_URL 이 없습니다.")
    try:
        return load_db(url, int(version) if version else None)
    except Exception as e:  # noqa: BLE001 — auto 모드는 어떤 실패든 parquet 로 대체해 서비스를 유지한다
        if mode == "db":
            raise
        msg = f"DB 읽기 실패로 parquet 사용: {type(e).__name__}"  # 접속 문자열이 섞일 수 있어 메시지 본문은 남기지 않는다
        log.warning(msg)
        loaded = load_parquet(processed_dir)
        loaded.notes.append(msg)
        return loaded
