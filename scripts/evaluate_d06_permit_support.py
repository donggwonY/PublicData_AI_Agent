from pathlib import Path
import json,gzip
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.metrics import brier_score_loss,precision_score,recall_score,roc_auc_score
P=Path('docs/d06/delivery/revised/permit_support');P.mkdir(exist_ok=True)
x=pd.read_csv('docs/d06/decline/eligible_cells.csv');j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet')
# Metadata same report year as feature accounting year+1; national statistics one more report year lag.
meta=j[['source_report_year','brandMnno','jngBizStrtDate','dmsCnt']].rename(columns={'source_report_year':'year','brandMnno':'brand'})
x=x.merge(meta,on=['year','brand'],how='left',validate='many_to_one')
cols=[c for c in j if c.startswith('national_')];n=j[['source_report_year','brandMnno']+cols].rename(columns={'source_report_year':'year','brandMnno':'brand'});n['year']=n.year+1
x=x.merge(n,on=['year','brand'],how='left',validate='many_to_one')
x['brand_age']=x.year-1-pd.to_numeric(x.jngBizStrtDate.astype(str).str[:4],errors='coerce');x.loc[x.brand_age<0,'brand_age']=np.nan
for c in cols+['dmsCnt']:x[c]=pd.to_numeric(x[c],errors='coerce')
for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']:x[c+'_rate']=x['national_'+c]/x.national_frcsCnt.where(x.national_frcsCnt>0)
x['log_national_count']=np.log1p(x.national_frcsCnt);x['log_direct']=np.log1p(x.dmsCnt)
extra=['brand_age','log_direct','log_national_count']+[c+'_rate' for c in ['newFrcsRgsCnt','ctrtEndCnt','ctrtCncltnCnt','nmChgCnt']]

# Reconstruct observed permit activity before each target year. Never replace FTC labels.
import re,unicodedata
s=pd.read_parquet('service/data/processed/stores.parquet',columns=['name','ld','cd','is_primary','building_key'])
s=s[s.is_primary.eq(True)].copy()
def norm(v): return re.sub(r'[^0-9a-z가-힣]','',unicodedata.normalize('NFKC',str(v)).lower())
a=j[['brandMnno','brandNm']].dropna().drop_duplicates();a['alias']=a.brandNm.map(norm)
owner=a.groupby('alias').brandMnno.nunique();a=a[(a.alias.str.len()>=4)&a.alias.map(owner).eq(1)].drop_duplicates(['alias'])
mp=dict(zip(a.alias,a.brandMnno));pat=re.compile('^(?:'+'|'.join(re.escape(v) for v in sorted(mp,key=len,reverse=True))+')')
s['alias']=s.name.fillna('').map(norm).map(lambda v:m.group() if (m:=pat.match(v)) else None);s['brand']=s.alias.map(mp);s=s[s.brand.notna()].copy()
s['ld']=pd.to_datetime(s.ld,errors='coerce');s['cd']=pd.to_datetime(s.cd,errors='coerce')
linked_brands=set(s.brand);features=[]
for y in sorted(x.year.unique()):
 cutoff=pd.Timestamp(int(y)-1,12,31);g=s[s.ld.notna()&(s.ld<=cutoff)]
 active=g[g.cd.isna()|(g.cd>cutoff)].groupby('brand').building_key.nunique()
 opened=g[g.ld.dt.year.eq(int(y)-1)].groupby('brand').size()
 closed=g[g.cd.dt.year.eq(int(y)-1)].groupby('brand').size()
 for b in x.loc[x.year.eq(y),'brand'].unique():
  features.append(dict(brand=b,year=y,permit_active=float(active.get(b,0)),permit_open=float(opened.get(b,0)),permit_closed=float(closed.get(b,0)),permit_name_linked=int(b in linked_brands)))
f=pd.DataFrame(features);f.to_csv(P/'permit_features.csv',index=False);x=x.merge(f,on=['brand','year'],validate='one_to_one')
for c in ['permit_active','permit_open','permit_closed']: x[c]=np.log1p(x[c])
permit_cols=['permit_active','permit_open','permit_closed','permit_name_linked']

protocol=dict(scope='exploratory permit auxiliary features on same fixed FTC-label sample; current name snapshot, exact historical name availability unverified; zero linked permits is not zero franchises',models='fixed HGB100 leaves7 min30 l2=10 lr=.05; basic versus additional',national_time='report year one earlier than feature report year; exact historical availability still unverified',features=extra,missing='median imputation trained on training only plus indicators, no row removal',threshold=.5)
(P/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8');out=[]
for y in [2022,2023,2024,2025]:
 tr=x[x.year<y];te=x[x.year==y]
 for name,nums in [('basic',['log_count','growth']),('additional',['log_count','growth']+extra),('permit_support',['log_count','growth']+extra+permit_cols)]:
  pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),nums)])
  model=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));model.fit(tr,tr.label)
  z=te[['brand','year','label']].copy();z['model']=name;z['probability']=model.predict_proba(te)[:,1];out.append(z)
r=pd.concat(out);r.to_csv(P/'predictions.csv',index=False)
metrics=[]
for (y,m),g in r.groupby(['year','model']):metrics.append(dict(year=int(y),model=m,n=len(g),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability)),precision=float(precision_score(g.label,g.probability>=.5,zero_division=0)),recall=float(recall_score(g.label,g.probability>=.5,zero_division=0))))
result=dict(annual=metrics,national_count_available_by_year=x.groupby('year').national_frcsCnt.apply(lambda s:float(s.notna().mean())).to_dict());(P/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(pd.DataFrame(metrics).to_string(index=False))

