from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss,roc_auc_score,precision_score,recall_score
P=Path('docs/d06/decline');d=pd.read_parquet('data/raw/franchise/daegu_panel.parquet');assert not d.duplicated(['brandMnno','year']).any()
lookup={(str(z.brandMnno),int(z.year)):z for z in d.itertuples()};rows=[];missing={}
for a in d.itertuples():
 t=int(a.year);b=lookup.get((str(a.brandMnno),t-1));z=lookup.get((str(a.brandMnno),t+1))
 if a.stores<3 or not np.isfinite(a.stores) or b is None or not np.isfinite(b.stores):continue
 if z is None or not np.isfinite(z.stores):missing[t+1]=missing.get(t+1,0)+1;continue
 rows.append(dict(brand=str(a.brandMnno),year=t+1,last=a.stores,previous=b.stores,actual=z.stores,industry=str(a.indutyMlsfcNm),log_count=np.log1p(a.stores),growth=np.log1p(a.stores)-np.log1p(b.stores),label=int(z.stores<a.stores)))
x=pd.DataFrame(rows);x.to_csv(P/'eligible_cells.csv',index=False)
protocol=dict(target='count[t+1]<count[t], count[t]>=3',scope='retrospective next-accounting-year change, not real-time next-12-month forecast; publication dates unknown',development_target_accounting_years=[2022,2023],evaluation_target_accounting_year=[2024],provisional_target_accounting_year=[2025],training='target labels <= forecast feature accounting year',features=['prior count','prior annual growth','prior industry'],missing='missing target excluded, observed zero retained',unavailable=['national opening/termination/cancellation counts','brand name and age'],selection='development Brier score only, threshold .5 fixed',prior_use='2024 and 2025 source years already explored for other targets; not untouched holdout')
(P/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def score(g):return dict(n=len(g),brier=float(brier_score_loss(g.label,g.probability)),auc=float(roc_auc_score(g.label,g.probability)),accuracy=float((g.label==(g.probability>=.5)).mean()),precision=float(precision_score(g.label,g.probability>=.5,zero_division=0)),recall=float(recall_score(g.label,g.probability>=.5,zero_division=0)),prevalence=float(g.label.mean()),mean_prediction=float(g.probability.mean()))
def run(years):
 out=[]
 for y in years:
  tr=x[x.year<=y-1];te=x[x.year==y];assert tr.year.max()<y
  rates=tr.groupby('industry').label.agg(['sum','count']);rates['p']=(rates['sum']+20*tr.label.mean())/(rates['count']+20)
  vals={'overall_rate':np.full(len(te),tr.label.mean()),'industry_rate':te.industry.map(rates.p).fillna(tr.label.mean()).to_numpy(),'past_direction':(te['last']<te.previous).astype(float).to_numpy()}
  for name,m in [('logistic',LogisticRegression(C=1,max_iter=1000)),('hgb',HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119))]:
   pre=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',StandardScaler(),['log_count','growth'])]);model=make_pipeline(pre,m);model.fit(tr,tr.label);vals[name]=model.predict_proba(te)[:,1]
  for name,p in vals.items():
   z=te.copy();z['model']=name;z['probability']=p;z['train_max_year']=int(tr.year.max());out.append(z)
 return pd.concat(out,ignore_index=True)
dev=run([2022,2023]);scores={m:score(g) for m,g in dev.groupby('model')};base=min(['overall_rate','industry_rate','past_direction'],key=lambda m:scores[m]['brier']);model=min(['logistic','hgb'],key=lambda m:scores[m]['brier'])
(P/'selection.json').write_text(json.dumps(dict(baseline=base,model=model,development=scores),indent=2),encoding='utf-8')
ev=run([2024,2025]);r=pd.concat([dev,ev]);r.to_csv(P/'predictions.csv',index=False)
result=dict(baseline=base,model=model,annual=[dict(year=int(y),model=m,**score(g)) for (y,m),g in r.groupby(['year','model'])],missing_target_by_year=missing)
(P/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('selected',base,model);print(pd.DataFrame(result['annual']).query('year>=2024').to_string(index=False))
