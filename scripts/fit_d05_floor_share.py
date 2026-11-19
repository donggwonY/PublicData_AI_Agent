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
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingRegressor
OUT=ROOT/'docs/d05'
CACHE=ROOT/'data/raw/d05';CACHE.mkdir(parents=True,exist_ok=True)
cache=CACHE/'floor_db_v6_2010_2025.parquet'
if cache.exists():
 d=pd.read_parquet(cache);v=6
else:
 with psycopg.connect(url,sslmode='require',connect_timeout=15) as conn:
  conn.read_only=True
  with conn.cursor() as c:
   c.execute('show transaction_read_only');assert c.fetchone()[0]=='on'
   c.execute("set local statement_timeout='90s'")
   c.execute('select version_id from app.current_version where singleton');v=c.fetchone()[0];assert v==6
   c.execute("""select extract(year from ld)::int,service,gu,floor,road_addr_raw,jibun_addr_raw
    from app.stores where version_id=%s and is_primary=true and short_event=false
    and ld >=date '2010-01-01' and ld <date '2026-01-01'""",(v,))
   d=pd.DataFrame(c.fetchall(),columns=['year','service','gu','floor','road','jibun'])
 d.to_parquet(cache,index=False)
# Reuse the reviewed address-flag functions without running its DB queries.
source=(ROOT/'scripts/audit_d05_floor_addresses.py').read_text(encoding='utf-8')
exec(source[source.index('def tokens'):source.index("d[['multi_flag'")])
flags=[inspect(row) for row in d.itertuples()]
d['ambiguous']=[a or b for a,b in flags]
d['known']=d.floor.notna()&~d.ambiguous
d['upper']=d.floor.fillna('').str.fullmatch(r'(?:[2-9]|[1-9][0-9]+)층')&d.known
missing_gu=int(d.gu.isna().sum());d=d.dropna(subset=['gu','service'])
g=d.groupby(['year','gu','service']).agg(n=('known','size'),k=('known','sum'),u=('upper','sum')).reset_index()
g.to_csv(OUT/'floor_panel.csv',index=False,encoding='utf-8-sig')
lookup={(int(r.year),r.gu,r.service):(int(r.n),int(r.k),int(r.u)) for r in g.itertuples()}
pairs=list(g[['gu','service']].drop_duplicates().itertuples(index=False,name=None))
rows=[]
for year in range(2013,2026):
 hist=g[g.year.between(year-3,year-1)]
 city=hist.groupby('service')[['k','u']].sum();region=hist.groupby('gu')[['k','u']].sum()
 for gu,service in pairs:
  past=[lookup.get((year-i,gu,service),(0,0,0)) for i in (1,2,3)]
  n,k,u=np.array(past).sum(axis=0);eligible=k>=60 and n>0 and k/n>=.8
  if not eligible:continue
  cn,cu=city.loc[service,['k','u']];gn,guu=region.loc[gu,['k','u']]
  current=lookup.get((year,gu,service),(0,0,0))
  rates=[p[2]/p[1] if p[1] else np.nan for p in past]
  rows.append(dict(year=year,gu=gu,service=service,n=current[0],k=current[1],u=current[2],lag1=rates[0],lag2=rates[1],lag3=rates[2],past_rate=u/k,past_logk=np.log1p(k),past_coverage=k/n,city_rate=cu/cn,gu_rate=guu/gn,shrink=(u+30*cu/cn)/(k+30)))
panel=pd.DataFrame(rows);panel.to_csv(OUT/'prediction_cells.csv',index=False,encoding='utf-8-sig')
num=['lag1','lag2','lag3','past_rate','past_logk','past_coverage','city_rate','gu_rate'];cat=['gu','service']
results=[];counts=[]
for year in range(2020,2026):
 tr=panel[(panel.year>=2015)&(panel.year<year)&(panel.k>0)].copy()
 te=panel[panel.year==year].copy();counts.append({'year':year,'eligible_cells':len(te),'zero_known_excluded':int((te.k==0).sum()),'train_cells':len(tr)})
 te=te[te.k>0].copy();assert tr.year.max()<year
 prep=ColumnTransformer([('num',make_pipeline(SimpleImputer(strategy='median'),StandardScaler()),num),('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cat)])
 X=prep.fit_transform(tr);T=prep.transform(te)
 # Two weighted classes per cell implement grouped binomial likelihood.
 X2=np.repeat(X,2,axis=0);yy=np.tile([0,1],len(tr));ww=np.column_stack([tr.k-tr.u,tr.u]).ravel();mask=ww>0
 lr=LogisticRegression(C=1,max_iter=2000,solver='lbfgs');lr.fit(X2[mask],yy[mask],sample_weight=ww[mask])
 gb=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,min_samples_leaf=15,l2_regularization=10,learning_rate=.05,random_state=17,early_stopping=False)
 gb.fit(X,tr.u/tr.k,sample_weight=tr.k)
 pred={'last_year':te.lag1.fillna(te.past_rate).to_numpy(),'three_year':te.past_rate.to_numpy(),'smoothed':te.shrink.to_numpy(),'logistic':lr.predict_proba(T)[:,1],'boosting':np.clip(gb.predict(T),0,1)}
 for name,p in pred.items():
  assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
  for r,value in zip(te.itertuples(),p):results.append({'year':year,'gu':r.gu,'service':r.service,'n':r.n,'k':r.k,'u':r.u,'actual':r.u/r.k,'model':name,'pred':float(value)})
 print('Evaluated',year,'cells',len(te),flush=True)
r=pd.DataFrame(results);r['ae']=abs(r.pred-r.actual)*100
r['brier']=(r.u*(1-r.pred)**2+(r.k-r.u)*r.pred**2)/r.k
r.to_csv(OUT/'model_predictions.csv',index=False,encoding='utf-8-sig')
def metrics(t):
 return {'cells':len(t),'known':int(t.k.sum()),'mae_pp':float(t.ae.mean()),'weighted_mae_pp':float(np.average(t.ae,weights=t.k)),'brier':float(np.average(t.brier,weights=t.k))}
overall={name:metrics(t) for name,t in r.groupby('model')}
annual=[dict(year=int(y),model=name,**metrics(t)) for (y,name),t in r.groupby(['year','model'])]
service=[dict(service=s,model=name,**metrics(t)) for (s,name),t in r.groupby(['service','model'])]
pd.DataFrame(annual).to_csv(OUT/'model_annual.csv',index=False,encoding='utf-8-sig');pd.DataFrame(service).to_csv(OUT/'model_services.csv',index=False,encoding='utf-8-sig')
wide=r.pivot(index=['year','gu','service'],columns='model',values='ae');unc={};rng=np.random.default_rng(17)
for model in ['last_year','smoothed','logistic','boosting']:
 delta=(wide[model]-wide.three_year).rename('delta').reset_index();cl=delta.groupby(['gu','service']).delta.agg(['sum','count']);ix=rng.integers(len(cl),size=(2000,len(cl)));draw=cl['sum'].to_numpy()[ix].sum(axis=1)/cl['count'].to_numpy()[ix].sum(axis=1)
 unc[model]={'delta_mae_pp':float(delta.delta.mean()),'cluster_pairs':len(cl),'ci95':np.quantile(draw,[.025,.975]).tolist()}
report={'source_version':v,'source_rows':len(d),'missing_gu_excluded':missing_gu,'snapshot_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'counts':counts,'overall':overall,'annual':annual,'paired_vs_three_year':unc,'note':'Exploratory rolling evaluation, known/unambiguous floors only, no untouched test. Bootstrap clusters gu/service; common-year shocks not fully represented. No causal or site-success interpretation.'}
(OUT/'model_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'overall':overall,'uncertainty':unc},ensure_ascii=False,indent=2))
