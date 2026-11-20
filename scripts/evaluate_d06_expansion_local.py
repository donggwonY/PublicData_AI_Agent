from pathlib import Path
import json
import pandas as pd,numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score,brier_score_loss,roc_auc_score
P=Path('docs/d06/expansion');O=P/'local_features';O.mkdir(exist_ok=True)
e=pd.read_csv(P/'entry_quality_cells.csv');e=e[e.brand_present_elsewhere.eq(True)].copy();e['label']=e.entry_candidate.astype(int)
x=pd.read_csv(P/'expanded_brand_gu_year.csv');city=x.groupby(['brand_id','year']).agg(city_total=('observed_active_buildings','sum'),districts_present=('observed_active_buildings',lambda s:int((s>0).sum()))).reset_index();city['year']+=1
e=e.merge(city,on=['brand_id','year'],validate='many_to_one');older=city[['brand_id','year','city_total']].copy();older['year']+=1;older=older.rename(columns={'city_total':'older_total'});e=e.merge(older,on=['brand_id','year'],how='left',validate='many_to_one')
j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');meta=j[['brandMnno','acntgYr','indutyMlsfcNm']].rename(columns={'brandMnno':'brand_id','acntgYr':'year','indutyMlsfcNm':'industry'});meta['year']=pd.to_numeric(meta.year)+1;e=e.merge(meta,on=['brand_id','year'],validate='many_to_one');e=e[e.older_total.notna()&e.industry.notna()].copy();e['log_total']=np.log1p(e.city_total);e['growth']=np.log1p(e.city_total)-np.log1p(e.older_total)

s=pd.read_parquet('service/data/processed/stores.parquet',columns=['gu','service','ld','cd','is_primary']);s=s[s.is_primary.eq(True)].copy();s['ld']=pd.to_datetime(s.ld,errors='coerce');s['cd']=pd.to_datetime(s.cd,errors='coerce');s=s[s.ld.notna()];local=[]
services={'restaurant':'일반음식점','cafe':'휴게음식점','beauty':'미용업','retail':'담배소매업','bakery':'제과점영업'}
for y in sorted(e.year.unique()):
 end=pd.Timestamp(int(y)-1,12,31);start=pd.Timestamp(int(y)-1,1,1);oldend=pd.Timestamp(int(y)-2,12,31)
 for gu in sorted(e.gu.unique()):
  g=s[s.gu==gu];active=g[(g.ld<=end)&(g.cd.isna()|(g.cd>end))];prior=g[(g.ld<=oldend)&(g.cd.isna()|(g.cd>oldend))];opened=g[g.ld.between(start,end)];closed=g[(g.ld<=end)&g.cd.between(start,end)];n=len(active)
  row=dict(year=int(y),gu=gu,local_log_active=np.log1p(n),local_open_rate=len(opened)/max(len(prior),1),local_close_rate=len(closed)/max(len(prior),1),local_growth=np.log1p(n)-np.log1p(len(prior)))
  for name,service in services.items():row[name+'_share']=float(active.service.eq(service).sum()/max(n,1));row[name+'_open_rate']=float(opened.service.eq(service).sum()/max(len(prior),1))
  local.append(row)
l=pd.DataFrame(local);l.to_csv(O/'local_features.csv',index=False);e=e.merge(l,on=['year','gu'],validate='many_to_one');e['industry_gu']=e.industry+'|'+e.gu
nums=['log_total','growth','districts_present']+[c for c in l if c not in ['year','gu']];cats=['gu','industry','industry_gu'];features=nums+cats
protocol=dict(scope='exploratory reused source years and same sample as initial experiment',target='new observed permit presence; not confirmed franchise entry',development=[2021,2022],evaluation=[2023,2024],provisional=[2025],selection='brandwise top1 hit on development entrants with >=2 absent districts',features=features,feature_time='permit dates <= December31 target-1; no target-year flows',model='fixed logistic C1 or HGB100 leaf7 min30 l2=10 lr=.05',definition='local permit records, five service shares, prior-year opening/closure rates; not complete retail census',limits=['later revisions in snapshot','unverified brand-name links','publication timing unknown'])
(O/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def ranking(g):
 hits=[]
 for _,h in g.groupby(['brand_id','year']):
  if len(h)>=2 and h.label.any():hits.append(float(h.loc[h.probability==h.probability.max(),'label'].mean()))
 return dict(entrant_brands=len(hits),top1=float(np.mean(hits)))
def run(years):
 out=[]
 for y in years:
  tr=e[e.year<y];te=e[e.year==y]
  for name,m in [('local_logistic',LogisticRegression(C=1,max_iter=1000)),('local_hgb',HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261120))]:
   pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cats),('num',StandardScaler(),nums)]);model=make_pipeline(pre,m);model.fit(tr[features],tr.label)
   z=te[['brand_id','year','gu','label']].copy();z['model']=name;z['probability']=model.predict_proba(te[features])[:,1];out.append(z)
 return pd.concat(out,ignore_index=True)
dev=run([2021,2022]);ds={m:ranking(g) for m,g in dev.groupby('model')};chosen=max(ds,key=lambda m:ds[m]['top1']);(O/'selection.json').write_text(json.dumps(dict(selected=chosen,development=ds),indent=2),encoding='utf-8')
r=pd.concat([dev,run([2023,2024,2025])]);r.to_csv(O/'predictions.csv',index=False)
old=pd.read_csv(P/'experiment/predictions.csv');allp=pd.concat([old[old.model.isin(['district_rate','logistic','hgb'])],r]);rows=[]
for (y,m),g in allp.groupby(['year','model']):rows.append(dict(year=int(y),model=m,n=len(g),ap=float(average_precision_score(g.label,g.probability)),brier=float(brier_score_loss(g.label,g.probability)),**ranking(g)))
result=dict(selected=chosen,annual=rows);(O/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');assert not r.duplicated(['brand_id','gu','year','model']).any();print('selected',chosen,ds);print(pd.DataFrame(rows).query('year>=2023').to_string(index=False))
