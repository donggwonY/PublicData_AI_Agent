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
P=Path('docs/d06/decline/additional');P.mkdir(exist_ok=True)
x=pd.read_csv(P.parent/'eligible_cells.csv');j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet')
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
protocol=dict(scope='exploratory reuse of prior evaluated years; same fixed sample',models='fixed HGB100 leaves7 min30 l2=10 lr=.05; basic versus additional',national_time='report year one earlier than feature report year; exact historical availability still unverified',features=extra,missing='median imputation trained on training only plus indicators, no row removal',threshold=.5)
(P/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8');out=[]
for y in [2022,2023,2024,2025]:
 tr=x[x.year<y];te=x[x.year==y]
 for name,nums in [('basic',['log_count','growth']),('additional',['log_count','growth']+extra)]:
  pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',SimpleImputer(strategy='median',add_indicator=True),nums)])
  model=make_pipeline(pre,HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119));model.fit(tr,tr.label)
  z=te[['brand','year','label']].copy();z['model']=name;z['probability']=model.predict_proba(te)[:,1];out.append(z)
r=pd.concat(out);r.to_csv(P/'predictions.csv',index=False)
metrics=[]
for (y,m),g in r.groupby(['year','model']):metrics.append(dict(year=int(y),model=m,n=len(g),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability)),precision=float(precision_score(g.label,g.probability>=.5,zero_division=0)),recall=float(recall_score(g.label,g.probability>=.5,zero_division=0))))
result=dict(annual=metrics,national_count_available_by_year=x.groupby('year').national_frcsCnt.apply(lambda s:float(s.notna().mean())).to_dict());(P/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(pd.DataFrame(metrics).to_string(index=False))
