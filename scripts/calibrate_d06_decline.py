from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score
P=Path('docs/d06/decline/additional');d=pd.read_csv(P/'predictions.csv');d=d[d.model=='additional'].copy()
protocol=dict(scope='exploratory calibration of frozen predictions, reused test years',fit_year=[2022],validation_year=[2023],evaluation_year=[2024],provisional_year=[2025],selection='retain raw unless sigmoid fitted on2022 improves Brier on2023; freeze mapping without refit',method='logistic C1 on clipped logit probability, unweighted',no_service_decision=True)
(P/'calibration_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
def feature(g):return np.log(np.clip(g.probability.to_numpy(),1e-6,1-1e-6)/(1-np.clip(g.probability.to_numpy(),1e-6,1-1e-6))).reshape(-1,1)
a=d[d.year==2022];v=d[d.year==2023];m=LogisticRegression(C=1,max_iter=1000).fit(feature(a),a.label)
vp=m.predict_proba(feature(v))[:,1];raw=brier_score_loss(v.label,v.probability);cal=brier_score_loss(v.label,vp);selected='sigmoid' if cal<raw else 'raw'
(P/'calibration_selection.json').write_text(json.dumps(dict(selected=selected,validation_raw=raw,validation_sigmoid=cal,coefficient=m.coef_.tolist(),intercept=m.intercept_.tolist()),indent=2),encoding='utf-8')
d['sigmoid']=m.predict_proba(feature(d))[:,1];rows=[];bins=[]
for y,g in d.groupby('year'):
 for method in ['probability','sigmoid']:
  p=g[method];rows.append(dict(year=int(y),method=method,n=len(g),mean_prediction=float(p.mean()),actual_rate=float(g.label.mean()),brier=float(brier_score_loss(g.label,p)),logloss=float(log_loss(g.label,p)),auc=float(roc_auc_score(g.label,p))))
  z=g.assign(bucket=pd.cut(p,[0,.2,.4,.6,.8,1],include_lowest=True))
  for bucket,h in z.groupby('bucket',observed=True):bins.append(dict(year=int(y),method=method,bucket=str(bucket),n=len(h),mean_prediction=float(h[method].mean()),actual_rate=float(h.label.mean())))
d.to_csv(P/'calibration_predictions.csv',index=False);pd.DataFrame(bins).to_csv(P/'calibration_bins.csv',index=False)
(P/'calibration_results.json').write_text(json.dumps(dict(selected=selected,annual=rows),indent=2),encoding='utf-8');print('selected',selected);print(pd.DataFrame(rows).to_string(index=False))
assert not d.duplicated(['brand','year']).any();assert np.isfinite(d.sigmoid).all()
