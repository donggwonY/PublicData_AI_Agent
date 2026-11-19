from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.metrics import precision_score,recall_score
P=Path('docs/d06/decline/additional');d=pd.read_csv(P/'predictions.csv');dev=d[(d.model=='additional')&d.year.isin([2022,2023])]
# Fixed exploratory policy: maximize development recall subject to precision >=60%, at least50 alerts.
protocol=dict(scope='exploratory reused evaluation, not independent validation',development=[2022,2023],evaluation=[2024],provisional=[2025],rule='maximize recall subject to development precision>=0.60 and >=50 alerts; threshold grid0.10..0.90 step0.01; ties prefer higher precision then higher threshold',meaning='60% is a trial warning policy, not team-approved service cutoff',fallback='no eligible threshold -> no candidate',reference_threshold=.5)
(P/'warning_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def metrics(g,t):
 a=g.probability>=t;tp=int((a&(g.label==1)).sum());n=int(a.sum());return dict(n=len(g),threshold=float(t),alerts=n,true_alerts=tp,false_alerts=n-tp,missed_declines=int(((~a)&(g.label==1)).sum()),precision=float(precision_score(g.label,a,zero_division=0)),recall=float(recall_score(g.label,a,zero_division=0)))
rows=[metrics(dev,t) for t in np.round(np.arange(.10,.901,.01),2)];ok=[r for r in rows if r['precision']>=.6 and r['alerts']>=50];choice=max(ok,key=lambda r:(r['recall'],r['precision'],r['threshold'])) if ok else None
pd.DataFrame(rows).to_csv(P/'warning_development.csv',index=False);(P/'warning_selection.json').write_text(json.dumps(choice,indent=2),encoding='utf-8')
res=[]
for y,g in d[d.model=='additional'].groupby('year'):
 for name,t in [('fixed_05',.5)]+([] if choice is None else [('development_selected',choice['threshold'])]):res.append(dict(year=int(y),policy=name,**metrics(g,t)))
# Paired Brier improvement CI, cluster by brand across2024/2025; provisional included explicitly.
e=d[d.year.isin([2024,2025])].copy();e['loss']=(e.probability-e.label)**2
w=e.pivot(index=['brand','year'],columns='model',values='loss');w['delta']=w.additional-w.basic;a=w.groupby('brand').delta.agg(['sum','count']).to_numpy();rng=np.random.default_rng(20261119);boot=[]
for _ in range(2000):
 z=a[rng.integers(len(a),size=len(a))].sum(axis=0);boot.append(z[0]/z[1])
result=dict(selection=choice,annual=res,pooled_2024_2025_includes_provisional=dict(brier_difference=float(w.delta.mean()),brand_bootstrap_ci=np.quantile(boot,[.025,.975]).tolist(),brands=len(a),rows=len(w)))
(P/'warning_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
