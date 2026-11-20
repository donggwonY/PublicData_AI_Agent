from pathlib import Path
import json
import pandas as pd,numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score,brier_score_loss,roc_auc_score
P=Path('docs/d06/expansion/refined');O=P/'experiment';O.mkdir(exist_ok=True)
e=pd.read_csv(P/'entry_quality_cells.csv');e=e[e.brand_present_elsewhere.eq(True)].copy();e['label']=e.entry_candidate.astype(int)
x=pd.read_csv(P/'expanded_brand_gu_year.csv');city=x.groupby(['brand_id','year']).agg(city_total=('observed_active_buildings','sum'),districts_present=('observed_active_buildings',lambda s:int((s>0).sum()))).reset_index();city['year']+=1
e=e.merge(city,on=['brand_id','year'],validate='many_to_one');older=city[['brand_id','year','city_total']].copy();older['year']+=1;older=older.rename(columns={'city_total':'older_total'});e=e.merge(older,on=['brand_id','year'],how='left',validate='many_to_one')
j=pd.read_parquet('data/raw/d06_franchise/joined_daegu.parquet');meta=j[['brandMnno','acntgYr','indutyMlsfcNm']].rename(columns={'brandMnno':'brand_id','acntgYr':'year','indutyMlsfcNm':'industry'});meta['year']=pd.to_numeric(meta.year)+1;e=e.merge(meta,on=['brand_id','year'],validate='many_to_one');e=e[e.older_total.notna()&e.industry.notna()].copy();e['log_total']=np.log1p(e.city_total);e['growth']=np.log1p(e.city_total)-np.log1p(e.older_total)
features=['log_total','growth','districts_present','gu','industry']
protocol=dict(target='new linked active permit-building presence in an observed-zero district; not verified franchise entry',population='brand has linked activity in other Daegu districts at t-1 and available t-2 counts; fixed8 districts excludes Gunwi',features=features,training='target years < evaluation year; retrospective accounting-year origins, publication timing unavailable',development=[2021,2022],evaluation=[2023,2024],provisional=[2025],primary='average precision',data_limits=['provisional name substring matches','zero linked records not confirmed absence','source snapshots include later revisions','brand availability based on historical report year not release date'])
(O/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def score(g):return dict(n=len(g),entries=int(g.label.sum()),prevalence=float(g.label.mean()),average_precision=float(average_precision_score(g.label,g.probability)),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability)))
def run(years):
 out=[]
 for y in years:
  tr=e[e.year<y];te=e[e.year==y];assert len(tr)>100
  rates=tr.groupby('gu').label.agg(['sum','count']);rates['p']=(rates['sum']+20*tr.label.mean())/(rates['count']+20)
  vals={'global_rate':np.full(len(te),tr.label.mean()),'district_rate':te.gu.map(rates.p).to_numpy()}
  for name,m in [('logistic',LogisticRegression(C=1,max_iter=1000)),('hgb',HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261120))]:
   pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['gu','industry']),('num',StandardScaler(),features[:3])]);model=make_pipeline(pre,m);model.fit(tr[features],tr.label);vals[name]=model.predict_proba(te[features])[:,1]
  for m,v in vals.items():
   z=te[['brand_id','year','gu','label','previous_count_agrees']].copy();z['model']=m;z['probability']=v;out.append(z)
 return pd.concat(out,ignore_index=True)
dev=run([2021,2022]);ds={m:score(g) for m,g in dev.groupby('model')};base=max(['global_rate','district_rate'],key=lambda m:ds[m]['average_precision']);model=max(['logistic','hgb'],key=lambda m:ds[m]['average_precision']);(O/'selection.json').write_text(json.dumps(dict(baseline=base,model=model,development=ds),indent=2),encoding='utf-8')
r=pd.concat([dev,run([2023,2024,2025])]);r.to_csv(O/'predictions.csv',index=False);annual=[dict(year=int(y),model=m,**score(g)) for (y,m),g in r.groupby(['year','model'])];result=dict(baseline=base,model=model,annual=annual);(O/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');assert not r.duplicated(['brand_id','year','gu','model']).any();print('selected',base,model);print(pd.DataFrame(annual).query('year>=2023').to_string(index=False))
