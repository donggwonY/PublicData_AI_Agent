"""Paired building bootstrap and unseen-building checks on saved tree predictions."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03/opening_neighborhood'
report=json.loads((OUT/'nonlinear_results.json').read_text(encoding='utf-8'))
p=ROOT/'data/raw/d03/nonlinear_neighborhood_predictions.parquet';assert snapshot_sha256(p)==report['hashes']['predictions']
a=pd.read_parquet(p);features=ROOT/'data/raw/d03/building_opening_context.parquet';assert snapshot_sha256(features)==report['hashes']['features'];f=pd.read_parquet(features)
rng=np.random.default_rng(20261116);rows=[]
for (radius,year),g in a.groupby(['radius','year']):
 train=f[(f.radius==radius)&f.year.between(year-6,year-2)]
 unseen=~g.building.isin(train.building)
 for base,new in [('permit_density','permit_summary'),('building_density','building_summary')]:
  y=g.closure_365.to_numpy();b=g[base].to_numpy();n=g[new].to_numpy()
  errors=pd.DataFrame({'building':g.building.to_numpy(),'brier_delta':(n-y)**2-(b-y)**2,'loss_delta':-(y*np.log(np.clip(n,1e-15,1-1e-15))+(1-y)*np.log(np.clip(1-n,1e-15,1-1e-15)))+(y*np.log(np.clip(b,1e-15,1-1e-15))+(1-y)*np.log(np.clip(1-b,1e-15,1-1e-15)))})
  clusters=errors.groupby('building')[['brier_delta','loss_delta']].mean().to_numpy();k=len(clusters);boots=[]
  for start in range(0,1000,100):
   draws=rng.multinomial(k,np.full(k,1/k),size=100);boots.append(draws@clusters/k)
  boot=np.vstack(boots);lo,hi=np.quantile(boot,[.025,.975],axis=0)
  ix=unseen.to_numpy();weights=g.weight.to_numpy()[ix];yy=y[ix]
  bn=brier_score_loss(yy,b[ix],sample_weight=weights);nn=brier_score_loss(yy,n[ix],sample_weight=weights)
  ld=log_loss(yy,n[ix],sample_weight=weights)-log_loss(yy,b[ix],sample_weight=weights)
  rows.append(dict(radius=int(radius),year=int(year),base=base,new=new,buildings=k,brier_delta=float(clusters[:,0].mean()),brier_low=float(lo[0]),brier_high=float(hi[0]),logloss_delta=float(clusters[:,1].mean()),logloss_low=float(lo[1]),logloss_high=float(hi[1]),both_intervals_below_zero=bool(hi[0]<0 and hi[1]<0),unseen_n=int(ix.sum()),unseen_brier_gain_pct=float(100*(bn-nn)/bn),unseen_logloss_delta=float(ld)))
result=dict(method='Paired within-building mean loss difference; resample buildings1000 times, seed20261116; percentile95 pointwise intervals. Negative delta favors additional context.',limitations=['Exploratory post-hoc intervals; multiple comparisons not corrected.','Building clusters do not account for neighboring-building spatial dependence.','Unseen subset defined by prior training building key, not geographic separation.','Does not validate historical availability or causality.'],hashes={'predictions':snapshot_sha256(p),'features':snapshot_sha256(features),'script':snapshot_sha256(Path(__file__))},results=rows)
(OUT/'nonlinear_uncertainty.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print('both error intervals below zero',sum(r['both_intervals_below_zero'] for r in rows),'/',len(rows))
for base in ['permit_density','building_density']:
 z=[r for r in rows if r['base']==base];print(base,'unseen both improve',sum(r['unseen_brier_gain_pct']>0 and r['unseen_logloss_delta']<0 for r in z),'/',len(z))
for r in report['results']:
 linear=r['linear_scores']['permit_density'];tree=r['scores']['permit_density'];print('tree density vs linear density',r['radius'],r['year'],'Brier improvement%',round(100*(linear['brier']-tree['brier'])/linear['brier'],3),'lossdiff',round(tree['log_loss']-linear['log_loss'],6))
