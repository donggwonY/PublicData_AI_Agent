"""Retrospective Daegu franchise store-count direction experiment."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import balanced_accuracy_score,accuracy_score,confusion_matrix
P=Path('docs/d06/store_counts');P.mkdir(exist_ok=True)
protocol=dict(target='sign(count[t]-count[t-2]); latest available count to target, NOT one-year t-1 to t change',population='positive count at t-2; t-3 observed; missing target excluded, observed zero retained',training='target labels <= evaluation year-2',development=[2021,2022],evaluation=[2023,2024],provisional=[2025],primary='balanced accuracy over decrease/unchanged/increase',selection='choose baseline and model on development only',gate='at least 0.03 balanced accuracy gain pooled and positive gain in both evaluation years',limitations=['historical release dates/vintages unknown','missing target rows selection bias','brand count growth is not profit or recommendation'],models={'logistic':{'C':1,'max_iter':1000,'class_weight':'balanced'},'hgb':{'max_iter':100,'max_leaf_nodes':7,'min_samples_leaf':30,'l2_regularization':10,'learning_rate':.05}})
(P/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
f=Path('data/raw/franchise/daegu_panel.parquet');d=pd.read_parquet(f)
assert not d.duplicated(['brandMnno','year']).any()
d=d[d.stores.notna() & (d.stores>=0) & (d.stores%1==0)]
lookup={(str(z.brandMnno),int(z.year)):z for z in d.itertuples()};rows=[]
for z in d.itertuples():
 t=int(z.year);a=lookup.get((str(z.brandMnno),t-2));b=lookup.get((str(z.brandMnno),t-3))
 if a is None or b is None or a.stores<=0:continue
 rows.append(dict(brand=str(z.brandMnno),year=t,last=float(a.stores),previous=float(b.stores),actual=float(z.stores),industry=str(a.indutyMlsfcNm),log_count=np.log1p(a.stores),growth=np.log1p(a.stores)-np.log1p(b.stores),past_delta=float(a.stores-b.stores),label=int(np.sign(z.stores-a.stores))))
x=pd.DataFrame(rows);x.to_csv(P/'eligible_cells.csv',index=False)
features=['log_count','growth','past_delta','industry']
def prep():return ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num',StandardScaler(),features[:3])])
def score(g):return dict(cells=len(g),brands=g.brand.nunique(),accuracy=float(accuracy_score(g.label,g.prediction)),balanced_accuracy=float(balanced_accuracy_score(g.label,g.prediction)),confusion_decrease_same_increase=confusion_matrix(g.label,g.prediction,labels=[-1,0,1]).tolist())
def evaluate(years):
 out=[]
 for y in years:
  tr=x[x.year<=y-2];te=x[x.year==y];assert len(tr)>0 and tr.year.max()<=y-2
  vals={'unchanged':np.zeros(len(te),dtype=int),'past_direction':np.sign(te.past_delta).astype(int).to_numpy(),'training_majority':np.full(len(te),tr.label.mode().iloc[0])}
  models={'logistic':make_pipeline(prep(),LogisticRegression(C=1,max_iter=1000,class_weight='balanced')),'hgb':make_pipeline(prep(),HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,random_state=20261119))}
  for name,m in models.items():m.fit(tr[features],tr.label);vals[name]=m.predict(te[features])
  for name,v in vals.items():
   z=te.copy();z['model']=name;z['prediction']=v;z['train_max_year']=int(tr.year.max());out.append(z)
 return pd.concat(out,ignore_index=True)
dev=evaluate([2021,2022]);scores={m:score(g) for m,g in dev.groupby('model')}
base=max(['unchanged','past_direction','training_majority'],key=lambda m:scores[m]['balanced_accuracy']);model=max(['logistic','hgb'],key=lambda m:scores[m]['balanced_accuracy'])
(P/'selection.json').write_text(json.dumps(dict(baseline=base,model=model,development=scores),indent=2),encoding='utf-8')
ev=evaluate([2023,2024]);late=evaluate([2025]);allpred=pd.concat([dev,ev,late]);allpred.to_csv(P/'predictions.csv',index=False)
metrics={m:score(g) for m,g in ev.groupby('model')};annual=[dict(year=int(y),model=m,**score(g)) for (y,m),g in allpred.groupby(['year','model'])]
by={y:{m:score(g)['balanced_accuracy'] for m,g in z.groupby('model')} for y,z in ev.groupby('year')}
gain=metrics[model]['balanced_accuracy']-metrics[base]['balanced_accuracy']
result=dict(baseline=base,model=model,evaluation=metrics,annual=annual,gain=gain,gate_passed=bool(gain>=.03 and all(v[model]>v[base] for v in by.values())),source_sha256=hashlib.sha256(f.read_bytes()).hexdigest())
(P/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(dict(baseline=base,model=model,evaluation=metrics,by_year=by,gain=gain,gate_passed=result['gate_passed']),indent=2))
