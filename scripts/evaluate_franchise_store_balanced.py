from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.metrics import balanced_accuracy_score,accuracy_score,confusion_matrix
P=Path('docs/d06/store_counts/balanced');P.mkdir(exist_ok=True)
f=P.parent/'eligible_cells.csv';x=pd.read_csv(f);x['size']=pd.cut(x['last'],[0,2,5,10,np.inf],labels=['1-2','3-5','6-10','11+']).astype(str)
protocol=dict(scope='exploratory follow-up on reused evaluation years; no independent confirmation',target='sign(count[t]-count[t-2]) unchanged',training='labels <= t-2',development=[2021,2022],evaluation=[2023,2024],provisional=[2025],selection='best baseline and model on development balanced accuracy before evaluation',baselines=['past_direction','size_majority','size_balanced'],models=['weighted_hgb'],size_rule='last observed count bins 1-2,3-5,6-10,11+; no future inputs',size_balanced_rule='training within-bin class frequencies divided by global training class frequencies; fallback global if bin n<30',hgb=dict(max_iter=100,max_leaf_nodes=7,min_samples_leaf=30,l2_regularization=10,learning_rate=.05),gate='gain >=0.03 versus selected baseline and positive in both evaluation years')
(P/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def score(g):return dict(n=len(g),accuracy=float(accuracy_score(g.label,g.prediction)),balanced_accuracy=float(balanced_accuracy_score(g.label,g.prediction)),confusion=confusion_matrix(g.label,g.prediction,labels=[-1,0,1]).tolist())
def run(years):
 out=[]
 for y in years:
  tr=x[x.year<=y-2];te=x[x.year==y];assert tr.year.max()<=y-2
  prior=tr.label.value_counts(normalize=True).reindex([-1,0,1],fill_value=0);assert (prior>0).all()
  maj={};bal={}
  for size in ['1-2','3-5','6-10','11+']:
   g=tr[tr['size']==size];freq=(g if len(g)>=30 else tr).label.value_counts(normalize=True).reindex([-1,0,1],fill_value=0)
   maj[size]=int(freq.idxmax());bal[size]=int((freq/prior).idxmax())
  values=dict(past_direction=np.sign(te.past_delta).astype(int).to_numpy(),size_majority=te['size'].map(maj).to_numpy(),size_balanced=te['size'].map(bal).to_numpy())
  pre=ColumnTransformer([('industry',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['industry']),('num','passthrough',['log_count','growth','past_delta'])]);a=pre.fit_transform(tr);b=pre.transform(te)
  m=HistGradientBoostingClassifier(**protocol['hgb'],random_state=20261119);m.fit(a,tr.label,sample_weight=compute_sample_weight('balanced',tr.label));values['weighted_hgb']=m.predict(b)
  for name,v in values.items():
   z=te.copy();z['model']=name;z['prediction']=v;z['train_max_year']=int(tr.year.max());out.append(z)
 return pd.concat(out,ignore_index=True)
dev=run([2021,2022]);ds={m:score(g) for m,g in dev.groupby('model')};base=max(protocol['baselines'],key=lambda m:ds[m]['balanced_accuracy'])
(P/'selection.json').write_text(json.dumps(dict(baseline=base,model='weighted_hgb',development=ds),indent=2),encoding='utf-8')
ev=run([2023,2024]);late=run([2025]);allp=pd.concat([dev,ev,late]);allp.to_csv(P/'predictions.csv',index=False)
metrics={m:score(g) for m,g in ev.groupby('model')};annual=[dict(year=int(y),model=m,**score(g)) for (y,m),g in allp.groupby(['year','model'])];sizes=[dict(size=s,model=m,**score(g)) for (s,m),g in ev.groupby(['size','model'])]
# Brand-cluster bootstrap keeps repeated years together.
w=ev.pivot(index=['brand','year','label'],columns='model',values='prediction').reset_index();parts=[]
for brand,g in w.groupby('brand'):
 parts.append([[int((g.label==c).sum()),int(((g.label==c)&(g.weighted_hgb==c)).sum()),int(((g.label==c)&(g[base]==c)).sum())] for c in [-1,0,1]])
a=np.asarray(parts);rng=np.random.default_rng(20261119);boot=[]
for _ in range(1000):
 z=a[rng.integers(len(a),size=len(a))].sum(axis=0);boot.append(float(((z[:,1]-z[:,2])/z[:,0]).mean()))
gain=metrics['weighted_hgb']['balanced_accuracy']-metrics[base]['balanced_accuracy'];each=[g[g.model=='weighted_hgb'].pipe(score)['balanced_accuracy']>g[g.model==base].pipe(score)['balanced_accuracy'] for _,g in ev.groupby('year')]
result=dict(baseline=base,evaluation=metrics,annual=annual,size_metrics=sizes,gain=gain,brand_bootstrap_gain_ci=np.quantile(boot,[.025,.975]).tolist(),gate_passed=bool(gain>=.03 and all(each)),input_sha256=hashlib.sha256(f.read_bytes()).hexdigest())
assert not allp.duplicated(['brand','year','model']).any();assert (allp.train_max_year<=allp.year-2).all()
(P/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k not in ['annual','size_metrics']},indent=2));print(pd.DataFrame(sizes)[['size','model','balanced_accuracy']].to_string(index=False))
