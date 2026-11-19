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


import numpy as np
OUT=ROOT/'docs/d05';cache=ROOT/'data/raw/d05/category_db_v6.parquet'
if cache.exists():d=pd.read_parquet(cache)
else:
 parts=[]
 for year in range(2010,2026):
  part=cache.with_name(f'category_v6_{year}.parquet')
  if part.exists(): t=pd.read_parquet(part)
  else:
   with psycopg.connect(url,sslmode='require',connect_timeout=15) as conn:
    conn.read_only=True
    with conn.cursor() as c:
     c.execute('show transaction_read_only');assert c.fetchone()[0]=='on'
     c.execute("set local statement_timeout='25s'")
     c.execute("select extract(year from ld)::int,service,category,gu,floor,road_addr_raw,jibun_addr_raw from app.stores where version_id=6 and is_primary=true and short_event=false and ld >= make_date(%s,1,1) and ld < make_date(%s,1,1)",(year,year+1))
     t=pd.DataFrame(c.fetchall(),columns=['year','service','category','gu','floor','road','jibun'])
   assert len(t)>0;t.to_parquet(part,index=False)
  parts.append(t);print('Loaded',year,len(t),flush=True)
 d=pd.concat(parts,ignore_index=True);d.to_parquet(cache,index=False)

source=(ROOT/'scripts/audit_d05_floor_addresses.py').read_text(encoding='utf-8');exec(source[source.index('def tokens'):source.index("d[['multi_flag'")])
flags=[inspect(row) for row in d.itertuples()];d['known']=d.floor.notna()&~np.array([a or b for a,b in flags]);d['upper']=d.floor.fillna('').str.fullmatch(r'(?:[2-9]|[1-9][0-9]+)층')&d.known
# Verify the separately acquired fixed snapshot matches earlier source aggregates.
check=d.dropna(subset=['gu','service']).groupby(['year','gu','service']).agg(n=('known','size'),k=('known','sum'),u=('upper','sum')).reset_index();old=pd.read_csv(OUT/'floor_panel.csv')
assert check.sort_values(['year','gu','service']).reset_index(drop=True)[['n','k','u']].equals(old.sort_values(['year','gu','service']).reset_index(drop=True)[['n','k','u']].astype(check[['n','k','u']].dtypes.to_dict()))
missing=int(d.category.isna().sum());d=d.dropna(subset=['gu','service','category']);d['category']=d.category.replace({'통닭(치킨)':'호프/통닭','까페':'커피숍'})
g=d.groupby(['year','gu','service','category']).agg(n=('known','size'),k=('known','sum'),u=('upper','sum')).reset_index();g.to_csv(OUT/'category_panel.csv',index=False,encoding='utf-8-sig')
parent=pd.read_csv(OUT/'prediction_cells.csv');out=[]
for year in range(2020,2026):
 h=g[g.year.between(year-3,year-1)].groupby(['gu','service','category'])[['n','k','u']].sum().reset_index()
 h=h[(h.k>=30)&(h.k/h.n>=.8)].merge(parent[parent.year==year][['gu','service','past_rate']],on=['gu','service'],validate='many_to_one')
 now=g[g.year==year][['gu','service','category','k','u']];h=h.merge(now,on=['gu','service','category'],suffixes=('_past',''),how='left').fillna({'k':0,'u':0})
 for r in h.itertuples():
  if not r.k:continue
  for model,p in [('broad',r.past_rate),('detailed',r.u_past/r.k_past),('blended',(r.u_past+30*r.past_rate)/(r.k_past+30))]:
   out.append(dict(year=year,gu=r.gu,service=r.service,category=r.category,k=int(r.k),actual=r.u/r.k,model=model,pred=p))
r=pd.DataFrame(out);r['ae']=abs(r.pred-r.actual)*100;r.to_csv(OUT/'category_predictions.csv',index=False,encoding='utf-8-sig')
def met(t):return {'cells':len(t),'known':int(t.k.sum()),'mae_pp':float(t.ae.mean()),'weighted_mae_pp':float(np.average(t.ae,weights=t.k))}
overall={m:met(t) for m,t in r.groupby('model')};annual=[dict(year=int(y),model=m,**met(t)) for (y,m),t in r.groupby(['year','model'])];pd.DataFrame(annual).to_csv(OUT/'category_annual.csv',index=False,encoding='utf-8-sig')
w=r.pivot(index=['year','gu','service','category'],columns='model',values='ae');unc={};rng=np.random.default_rng(17)
for m in ['detailed','blended']:
 z=(w[m]-w.broad).rename('delta').reset_index();cl=z.groupby(['gu','service','category']).delta.agg(['sum','count']);ix=rng.integers(len(cl),size=(2000,len(cl)));draw=cl['sum'].to_numpy()[ix].sum(axis=1)/cl['count'].to_numpy()[ix].sum(axis=1)
 unc[m]={'delta_pp':float(z.delta.mean()),'ci95':np.quantile(draw,[.025,.975]).tolist(),'better_years':int((z.groupby('year').delta.mean()<0).sum())}
rep={'overall':overall,'annual':annual,'paired_vs_broad':unc,'missing_category_rows':missing,'snapshot_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'note':'Same detailed targets for all comparisons. Different target cells from earlier broad experiments; not direct MAE comparison. No independent test or causal interpretation.'};(OUT/'category_results.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(rep,ensure_ascii=False,indent=2))
