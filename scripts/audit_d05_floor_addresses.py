"""Read-only shared DB floor-data feasibility audit; no model fitting."""
import os,re,json,hashlib
from pathlib import Path
from urllib.parse import urlsplit,unquote
import pandas as pd
import psycopg
ROOT=Path(__file__).resolve().parents[1]
vals={}
for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
 m=re.match(r'^\s*(?:export\s+)?(\w+)\s*=\s*(.*)$',line)
 if m: vals[m[1]]=m[2].strip().strip('"').strip("'")
url=os.environ.get('APP_READER_DATABASE_URL') or vals.get('APP_READER_DATABASE_URL','')
u=urlsplit(url); user=unquote(u.username or '')
assert user.split('.')[0]=='app_reader'
assert u.hostname=='db.uoiamnbkzlvlskngataq.supabase.co' or (u.hostname.endswith('.pooler.supabase.com') and user.endswith('.uoiamnbkzlvlskngataq'))

with psycopg.connect(url,sslmode='require',connect_timeout=15) as conn:
 conn.read_only=True
 with conn.cursor() as c:
  c.execute('show transaction_read_only');assert c.fetchone()[0]=='on'
  c.execute("set local statement_timeout='60s'")
  c.execute('select version_id from app.current_version where singleton');v=c.fetchone()[0]
  c.execute("""select extract(year from ld)::int,service,gu,floor,road_addr_raw,jibun_addr_raw
  from app.stores where version_id=%s and is_primary=true and short_event=false
  and ld >=date '2020-01-01' and ld <date '2026-01-01'""",(v,));rows=c.fetchall()
d=pd.DataFrame(rows,columns=['year','service','gu','floor','road','jibun'])
def tokens(x):
 if pd.isna(x):return set()
 return {re.sub(r'\s+','',m) for m in re.findall(r'(?:지하\s*)?\d+\s*층',str(x))}
def inspect(row):
 a,b=tokens(row.road),tokens(row.jibun)
 text=str(row.road)+' '+str(row.jibun)
 multi=len(a)>1 or len(b)>1 or bool(re.search(r'(?<!\d)\d{1,2}\s*(?:~|∼|～|·|및|부터)\s*\d{1,2}\s*층',text))
 conflict=bool(a and b and a!=b)
 return multi,conflict
assert not inspect(type('R',(),{'road':'도로 123, 1층','jibun':None})())[0]
assert inspect(type('R',(),{'road':'도로 123, 1~2층','jibun':None})())[0]
d[['multi_flag','conflict_flag']]=pd.DataFrame([inspect(r) for r in d.itertuples()],index=d.index)
d['known']=d.floor.notna()
d['upper']=d.floor.fillna('').str.fullmatch(r'(?:[2-9]|[1-9][0-9]+)층')
d['ambiguous']=d.multi_flag|d.conflict_flag
d['strict_known']=d.known&~d.ambiguous;d['strict_upper']=d.upper&~d.ambiguous
out=ROOT/'docs/d05';out.mkdir(exist_ok=True)
def tab(keys):
 g=d.groupby(keys,dropna=False).agg(n=('known','size'),known=('known','sum'),upper=('upper','sum'),multi=('multi_flag','sum'),conflict=('conflict_flag','sum'),strict_known=('strict_known','sum'),strict_upper=('strict_upper','sum')).reset_index()
 g['known_upper_pct']=100*g.upper/g.known.replace(0,float('nan'))
 g['strict_upper_pct']=100*g.strict_upper/g.strict_known.replace(0,float('nan'))
 g['all_records_lower_pct']=100*g.strict_upper/g.n
 g['all_records_upper_pct']=100*(g.strict_upper+g.n-g.strict_known)/g.n
 return g.round(3)
a=tab(['year']);s=tab(['service']);a.to_csv(out/'address_quality_annual.csv',index=False,encoding='utf-8-sig');s.to_csv(out/'address_quality_services.csv',index=False,encoding='utf-8-sig')
r={'version':v,'years':'2020-2025','n':len(d),'multi_flags':int(d.multi_flag.sum()),'road_jibun_conflicts':int(d.conflict_flag.sum()),'ambiguous_union':int(d.ambiguous.sum()),'known':int(d.known.sum()),'strict_known':int(d.strict_known.sum()),'strict_upper':int(d.strict_upper.sum()),'annual':a.to_dict('records'),'main_services':s[s.service.isin(['일반음식점','휴게음식점','미용업'])].to_dict('records'),'interpretation':'Heuristic flags, not confirmed errors. Bounds treat every unknown or flagged row as upper vs nonupper. Latest addresses do not verify opening-time floor. No future model evaluation.'}
assert (a.strict_upper<=a.strict_known).all() and (a.strict_known<=a.n).all()
assert int(a.n.sum())==len(d)
(out/'address_quality.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(r,ensure_ascii=False,indent=2))
