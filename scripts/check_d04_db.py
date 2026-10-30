"""Read-only aggregate verification of shared app data. Never log connection errors."""
import json, os, re, sys
from pathlib import Path
from urllib.parse import urlsplit, unquote
from datetime import datetime, timezone
import psycopg
from snapshot_hashes import verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/d04'
def main():
    vals={}
    for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*(?:export\s+)?(\w+)\s*=\s*(.*)$',line)
        if m: vals[m[1]]=m[2].strip().strip('"').strip("'")
    url=os.environ.get('APP_READER_DATABASE_URL') or vals.get('APP_READER_DATABASE_URL','')
    u=urlsplit(url); user=unquote(u.username or ''); host=u.hostname or ''
    assert user.split('.')[0]=='app_reader'
    assert host=='db.uoiamnbkzlvlskngataq.supabase.co' or (host.endswith('.pooler.supabase.com') and user.endswith('.uoiamnbkzlvlskngataq'))
    local=json.loads((OUT/'links.json').read_text(encoding='utf-8'))
    dates=json.loads((OUT/'date_quality.json').read_text(encoding='utf-8'))
    meta=json.loads((ROOT/'service/data/processed/meta.json').read_text(encoding='utf-8'))
    for n,h in local['hashes'].items(): verify_snapshot_hash(ROOT/f'service/data/processed/{n}.parquet',h)
    with psycopg.connect(url,sslmode='require',connect_timeout=15,autocommit=True) as conn:
        with conn.cursor() as c:
            c.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            c.execute('SET LOCAL statement_timeout=60000')
            c.execute('SHOW transaction_read_only'); readonly=c.fetchone()[0]=='on'; assert readonly
            c.execute('SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user'); role,superuser,bypass=c.fetchone()
            assert role=='app_reader' and not superuser and not bypass
            c.execute("SELECT has_table_privilege(current_user,'app.stores','SELECT'),has_table_privilege(current_user,'app.stores','INSERT,UPDATE,DELETE,TRUNCATE')")
            select_ok,write_ok=c.fetchone(); assert select_ok and not write_ok
            c.execute('SELECT v.version_id,v.status,v.reference_date FROM app.current_version x JOIN app.dataset_versions v USING(version_id) WHERE x.singleton')
            version,status,ref=c.fetchone(); assert status=='current' and str(ref)==meta['reference_date']
            c.execute('SELECT count(*),count(*) FILTER (WHERE closed),count(*) FILTER (WHERE org_code IS NULL OR service IS NULL OR mgmt_no IS NULL),count(*)-count(DISTINCT (org_code,service,mgmt_no)) FROM app.stores WHERE version_id=%s',(version,))
            n,closed,nullkeys,dups=c.fetchone()
            for table,keys in [('legal_admin_map','gu,legal_dong'),('area_context','gu,admin_dong')]:
                c.execute(f'SELECT count(*)-count(DISTINCT ({keys})) FROM app.{table} WHERE version_id=%s',(version,)); assert c.fetchone()[0]==0
            c.execute("""SELECT CASE WHEN s.service IN ('의원','병원') THEN '의원+병원' ELSE s.service END,count(*),count(*) FILTER (WHERE a.admin_dong IS NULL)
                FROM app.stores s LEFT JOIN app.legal_admin_map m ON m.version_id=s.version_id AND s.gu=m.gu AND s.dong=m.legal_dong
                LEFT JOIN app.area_context a ON a.version_id=s.version_id AND a.gu=s.gu AND a.admin_dong=m.admin_dong
                WHERE s.version_id=%s GROUP BY 1 ORDER BY 1""",(version,))
            groups=[{'group':g,'n':int(cnt),'failed':int(f)} for g,cnt,f in c.fetchall()]
            c.execute('ROLLBACK')
    expected={x['group']:(x['n'],x['failed']) for x in local['groups'] if x['field']=='analysis_service'}
    checks={'row_count':n==local['n'],'closed_count':closed==sum(x['closed'] for x in dates['rows']),'composite_key_no_nulls':nullkeys==0,'composite_key_unique':dups==0,'join_rows_preserved':sum(x['n'] for x in groups)==n,'failed_count':sum(x['failed'] for x in groups)==local['failed'],'all_service_groups':{x['group']:(x['n'],x['failed']) for x in groups}==expected}
    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'project':'uoiamnbkzlvlskngataq','role':role,'transaction_read_only':readonly,'stores_select_privilege':select_ok,'stores_write_privilege':write_ok,'version':version,'status':status,'reference_date':str(ref),'rows':n,'closed':closed,'missing_keys':nullkeys,'duplicate_keys':dups,'groups':groups,'checks':checks,'local_hashes':local['hashes'],'scope':'Aggregate comparison, not all-row value equality. Privilege check covers stores; no write attempts.','database_written':False}
    (OUT/'db_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert all(checks.values())
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('FAILED',type(exc).__name__,'sqlstate',getattr(exc,'sqlstate',None));sys.exit(1)
