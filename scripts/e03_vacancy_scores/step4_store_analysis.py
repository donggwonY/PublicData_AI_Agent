"""E-03 공실 점수 4단계: 고정 점수표를 공유 DB 분석용 표에 보관(1년 뒤 미래 검증용).

- 대상: 공유 DB(uoiamnbkzlvlskngataq), 스키마 analysis, 표 analysis.e03_vacancy_scores. 운영 app 스키마·current_version 은 건드리지 않음.
- 접속: 환경변수 APP_DATABASE_URL > 저장소 루트 .env 의 같은 키(관리자 계정). 접속 정보는 출력하지 않음.
- 적재 전 파일 SHA-256 을 문서 기록값과 대조, 같은 batch_id 가 이미 있으면 내용이 같을 때만 통과(덮어쓰지 않음).
- 적재 후 재조회로 행 수·수준별 행 수·확률 합계를 로컬 파일과 대조.
실행: service/.venv 파이썬(psycopg). python scripts/e03_vacancy_scores/step4_store_analysis.py <점수표 parquet> <기대 SHA-256>
"""
import hashlib, io, json, os, sys, urllib.parse
import pandas as pd
import psycopg

PROJECT = 'uoiamnbkzlvlskngataq'
path, expected = sys.argv[1], sys.argv[2]
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()
if sha != expected:
    sys.exit(f'파일 해시 불일치: {sha}')

url = os.environ.get('APP_DATABASE_URL', '')
if not url:
    for line in open(os.path.join(ROOT, '.env'), encoding='utf-8'):
        k, sep, v = line.strip().partition('=')
        if sep and k.strip() == 'APP_DATABASE_URL':
            url = v.strip().strip('"').strip("'")
p = urllib.parse.urlsplit(url)
user = p.username or ''
if PROJECT not in (user + (p.hostname or '')):
    sys.exit('접속 대상이 공유 DB 프로젝트가 아님 — 중단')

s = pd.read_parquet(path)
batch = f"{s.generated.iloc[0]}|{s.model_version.iloc[0]}"
s = s.assign(batch_id=batch, file_sha256=sha)
cols = ['batch_id', 'uid', 'occupant_id', 'addr', 'gu', 'dong', 'prev_group', 'vacant_days', 'vacant_band', 'p_fill_6m',
        'p_fill_1y', 'p_fill_2y', 'p_fill_1y_modelA', 'level_all', 'level_in_band', 'thin_evidence',
        'data_reference_date', 'generated', 'model_version', 'file_sha256']
for c in ('uid', 'occupant_id'):
    s[c] = s[c].astype(str)

DDL = """
create schema if not exists analysis;
revoke all on schema analysis from public;
do $$ begin
  if exists (select 1 from pg_roles where rolname='anon') then execute 'revoke all on schema analysis from anon'; end if;
  if exists (select 1 from pg_roles where rolname='authenticated') then execute 'revoke all on schema analysis from authenticated'; end if;
  if exists (select 1 from pg_roles where rolname='app_reader') then execute 'revoke all on schema analysis from app_reader'; end if;
end $$;
comment on schema analysis is '분석·검증용 결과 보관(운영 앱은 읽지 않음). 표마다 출처 문서를 comment 로 기록';
create table if not exists analysis.e03_vacancy_scores (
  batch_id text not null, uid text not null, occupant_id text not null, addr text, gu text, dong text, prev_group text,
  vacant_days integer not null, vacant_band text, p_fill_6m double precision, p_fill_1y double precision not null,
  p_fill_2y double precision, p_fill_1y_modela double precision, level_all smallint, level_in_band smallint,
  thin_evidence boolean, data_reference_date date not null, generated date not null, model_version text not null,
  file_sha256 text not null, loaded_at timestamptz not null default now(),
  primary key (batch_id, uid));
comment on table analysis.e03_vacancy_scores is
  'E-03 공실 해소 점수 고정 배치(현재 공백 후보, 조건부 1년 확률). 1년 뒤 실제 재입점으로 미래 검증. 문서 docs/e03/vacancy_scores_step3.md, step4.';
"""
with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
    cur.execute('select current_user, current_database()')
    who = cur.fetchone()
    cur.execute(DDL)
    cur.execute('select count(*), min(file_sha256), max(file_sha256) from analysis.e03_vacancy_scores where batch_id=%s', (batch,))
    n0, h1, h2 = cur.fetchone()
    if n0 and not (n0 == len(s) and h1 == h2 == sha):
        conn.rollback(); sys.exit(f'같은 batch_id 가 다른 내용으로 이미 있음({n0}행) — 덮어쓰지 않고 중단')
    if not n0:
        buf = io.StringIO(); s[cols].to_csv(buf, index=False, header=False); buf.seek(0)
        with cur.copy(f"copy analysis.e03_vacancy_scores ({','.join(c.lower() for c in cols)}) from stdin with (format csv)") as cp:
            cp.write(buf.read())
    conn.commit()
    cur.execute("""select count(*), round(sum(p_fill_1y)::numeric, 6), round(sum(p_fill_2y)::numeric, 6),
                          min(data_reference_date)::text, count(distinct uid)
                   from analysis.e03_vacancy_scores where batch_id=%s""", (batch,))
    n, s1, s2, refd, nu = cur.fetchone()
    cur.execute('select level_in_band, count(*) from analysis.e03_vacancy_scores where batch_id=%s group by 1 order by 1', (batch,))
    lv_db = {int(k): int(v) for k, v in cur.fetchall()}
    cur.execute("select pg_size_pretty(pg_total_relation_size('analysis.e03_vacancy_scores'))")
    size = cur.fetchone()[0]
    cur.execute("""select grantee, privilege_type from information_schema.role_table_grants
                   where table_schema='analysis' and table_name='e03_vacancy_scores' order by 1, 2""")
    grants = sorted({g for g, _ in cur.fetchall()})

lv_local = {int(k): int(v) for k, v in s.level_in_band.value_counts().sort_index().items()}
res = {'target': {'project': PROJECT, 'host': p.hostname, 'role': user.split('.')[0], 'db_user': who[0]},
       'table': 'analysis.e03_vacancy_scores', 'batch_id': batch, 'file_sha256': sha, 'already_present': bool(n0),
       'rows': {'db': n, 'local': len(s), 'distinct_uid_db': nu},
       'sum_p_fill_1y': {'db': float(s1), 'local': round(float(s.p_fill_1y.sum()), 6)},
       'sum_p_fill_2y': {'db': float(s2), 'local': round(float(s.p_fill_2y.sum()), 6)},
       'level_in_band_counts_equal': lv_db == lv_local, 'data_reference_date': refd, 'table_size': size,
       'table_grantees': grants}
res['verified'] = (n == len(s) == nu and abs(float(s1) - res['sum_p_fill_1y']['local']) < 1e-5
                   and abs(float(s2) - res['sum_p_fill_2y']['local']) < 1e-5 and res['level_in_band_counts_equal'])
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
sys.exit(0 if res['verified'] else 1)
