"""E-09: 현재 빈 자리 '다음 가게 업종' 고정 점수표를 공유 DB 분석용 표에 보관(1년 뒤 미래 검증용).

- 대상: 공유 DB(uoiamnbkzlvlskngataq), 표 analysis.e09_next_tenant_scores. 운영 app 스키마·current_version 은 건드리지 않음.
- 접속: 환경변수 APP_DATABASE_URL > 저장소 루트 .env 의 같은 키(관리자 계정). 접속 정보는 출력하지 않음.
- 적재 전 점수표 SHA-256 을 docs/e09/results/serve_scores.json 기록과 대조. 같은 batch_id 가 있으면 내용이 같을 때만 통과.
- 적재 후 재조회로 행 수·묶음별 확률 합·1순위 분포를 로컬과 대조. 결과는 docs/e09/results/store_analysis.json.
실행(저장소 루트): service/.venv/Scripts/python scripts/e09_next_tenant/store_analysis.py
"""
import hashlib
import io
import json
import os
import sys
import urllib.parse
from pathlib import Path

import pandas as pd
import psycopg

PROJECT = "uoiamnbkzlvlskngataq"
ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "docs/e09/results/serve_scores.json"
SRC = Path("C:/claude_workspace/e09_data/serve")
TABLE = "analysis.e09_next_tenant_scores"
EN = {"음식점": "food", "카페_제과": "cafe", "미용_이용": "beauty", "식품판매": "food_retail",
      "담배": "tobacco", "오락": "entertainment", "기타": "other"}
KO = {"음식점": "food", "카페·제과": "cafe", "미용·이용": "beauty", "식품판매": "food_retail", "담배": "tobacco",
      "오락": "entertainment", "기타": "other"}   # top1~3 의 한글 묶음 이름 → 영문 키


def db_url() -> str:
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k.strip() == "APP_DATABASE_URL":
                url = v.strip().strip('"').strip("'")
    return url


def main():
    summ = json.loads(SUMMARY.read_text(encoding="utf-8"))
    path = next(SRC.glob("next_tenant_scores_*.parquet"))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != summ["file_sha256"]:
        sys.exit(f"점수표 해시 불일치: {sha}")
    url = db_url()
    p = urllib.parse.urlsplit(url)
    user = p.username or ""
    if PROJECT not in (user + (p.hostname or "")):
        sys.exit("접속 대상이 공유 DB 프로젝트가 아님 — 중단")

    s = pd.read_parquet(path)
    batch = s.model_version.iloc[0]
    out = pd.DataFrame({"batch_id": batch, "uid": s.uid.astype(str), "occupant_id": s.occupant_id.astype(str),
                        "vacant_days": s.vacant_days.astype(int), "prev_group": s.prev_group, "prev_group7": s.prev_group7})
    for k, e in EN.items():
        out[f"p_{e}"] = s[f"p_{k}"].astype(float)
    for k, e in EN.items():
        out[f"typical_{e}"] = s[f"typical_{k}"].astype(float)
    for r in (1, 2, 3):
        out[f"top{r}"] = s[f"top{r}"].map(KO)
        out[f"top{r}_p"] = s[f"top{r}_p"].astype(float)
    out["data_reference_date"] = s.data_reference_date
    out["generated"] = s.generated
    out["model_version"] = s.model_version
    out["file_sha256"] = sha
    assert out.top1.notna().all()
    cols = list(out.columns)
    num = [c for c in cols if c.startswith(("p_", "typical_")) or c.endswith("_p")]
    coldefs = ",\n  ".join(
        f"{c} " + ("double precision not null" if c in num else "integer not null" if c == "vacant_days"
                   else "date not null" if c in ("data_reference_date", "generated") else "text not null")
        for c in cols)
    ddl = f"""
create schema if not exists analysis;
create table if not exists {TABLE} (
  {coldefs},
  loaded_at timestamptz not null default now(),
  primary key (batch_id, uid));
comment on table {TABLE} is
  'E-09 다음 가게 업종 확률 고정 배치(현재 공백 후보, 앞으로 2년 안에 들어온다면 7묶음 확률·이동표). 1년·2년 뒤 실제 입점 업종으로 미래 검증. 문서 docs/e09/serve_design.md.';
do $$ begin
  revoke all on {TABLE} from public;
  if exists (select 1 from pg_roles where rolname='anon') then execute 'revoke all on {TABLE} from anon'; end if;
  if exists (select 1 from pg_roles where rolname='authenticated') then execute 'revoke all on {TABLE} from authenticated'; end if;
  if exists (select 1 from pg_roles where rolname='app_reader') then execute 'revoke all on {TABLE} from app_reader'; end if;
end $$;
"""
    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("select current_user, current_database()")
        who = cur.fetchone()
        cur.execute(ddl)
        cur.execute(f"select count(*), min(file_sha256), max(file_sha256) from {TABLE} where batch_id=%s", (batch,))
        n0, h1, h2 = cur.fetchone()
        if n0 and not (n0 == len(out) and h1 == h2 == sha):
            conn.rollback()
            sys.exit(f"같은 batch_id 가 다른 내용으로 이미 있음({n0}행) — 덮어쓰지 않고 중단")
        if not n0:
            buf = io.StringIO()
            out[cols].to_csv(buf, index=False, header=False)
            buf.seek(0)
            with cur.copy(f"copy {TABLE} ({','.join(cols)}) from stdin with (format csv)") as cp:
                cp.write(buf.read())
        conn.commit()
        sums = ", ".join(f"round(sum(p_{e})::numeric, 6)" for e in EN.values())
        cur.execute(f"select count(*), count(distinct uid), min(data_reference_date)::text, {sums} from {TABLE} where batch_id=%s",
                    (batch,))
        row = cur.fetchone()
        cur.execute(f"select top1, count(*) from {TABLE} where batch_id=%s group by 1", (batch,))
        top_db = {k: int(v) for k, v in cur.fetchall()}
        cur.execute(f"select pg_size_pretty(pg_total_relation_size('{TABLE}'))")
        size = cur.fetchone()[0]
        cur.execute("""select distinct grantee from information_schema.role_table_grants
                       where table_schema='analysis' and table_name='e09_next_tenant_scores' order by 1""")
        grants = [g for (g,) in cur.fetchall()]
        cur.execute("select version_id from app.current_version")
        current = cur.fetchone()[0]

    n, nu, refd = row[0], row[1], row[2]
    sums_db = dict(zip(EN.values(), (float(x) for x in row[3:])))
    sums_local = {e: round(float(out[f"p_{e}"].sum()), 6) for e in EN.values()}
    top_local = {k: int(v) for k, v in out.top1.value_counts().items()}
    res = {"target": {"project": PROJECT, "host": p.hostname, "role": user.split(".")[0], "db_user": who[0]},
           "table": TABLE, "batch_id": batch, "file_sha256": sha, "already_present": bool(n0),
           "rows": {"db": n, "local": len(out), "distinct_uid_db": nu}, "data_reference_date": refd,
           "sum_p_equal": all(abs(sums_db[e] - sums_local[e]) < 1e-5 for e in EN.values()),
           "top1_counts_equal": top_db == top_local, "top1_counts": top_db,
           "table_size": size, "table_grantees": grants, "app_current_version_after": current}
    res["verified"] = n == len(out) == nu and res["sum_p_equal"] and res["top1_counts_equal"]
    (ROOT / "docs/e09/results/store_analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str),
                                                               encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    sys.exit(0 if res["verified"] else 1)


if __name__ == "__main__":
    main()
