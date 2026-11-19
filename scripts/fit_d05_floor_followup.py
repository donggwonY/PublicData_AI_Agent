"""D-05 frozen-panel exploratory follow-up; no DB or service writes."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.ensemble import RandomForestRegressor
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d05'
panel=pd.read_csv(OUT/'prediction_cells.csv');g=pd.read_csv(OUT/'floor_panel.csv')
old=pd.read_csv(OUT/'model_predictions.csv');base=old[old.model=='three_year'].copy()
num=['lag1','lag2','lag3','past_rate','past_logk','past_coverage','city_rate','gu_rate'];cat=['gu','service'];res=[]
lookup={(int(r.year),r.gu,r.service):(r.k,r.u) for r in g.itertuples()}
for year in range(2020,2026):
 tr=panel[(panel.year>=2015)&(panel.year<year)&(panel.k>0)].copy();te=panel[(panel.year==year)&(panel.k>0)].copy()
 assert tr.year.max()<year
 prep=ColumnTransformer([('num',make_pipeline(SimpleImputer(strategy='median'),StandardScaler()),num),('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cat)])
 X=prep.fit_transform(tr);T=prep.transform(te);target=tr.u/tr.k
 rf=RandomForestRegressor(n_estimators=300,min_samples_leaf=10,max_depth=4,random_state=17,n_jobs=2);rf.fit(X,target,sample_weight=tr.k)
 ridge=Ridge(alpha=100);ridge.fit(X,target-tr.past_rate,sample_weight=tr.k/tr.k.mean())
 recent=tr.year>=year-3;XX=np.repeat(X[recent],2,axis=0);yy=np.tile([0,1],recent.sum());t=tr[recent];ww=np.column_stack([t.k-t.u,t.u]).ravel();keep=ww>0
 lr=LogisticRegression(C=.1,max_iter=2000);lr.fit(XX[keep],yy[keep],sample_weight=ww[keep])
 recency=[]
 for r in te.itertuples():
  hist=np.array([lookup.get((year-i,r.gu,r.service),(0,0)) for i in (1,2,3)])
  totals=(hist*np.array([.5,.3,.2])[:,None]).sum(axis=0);recency.append(totals[1]/totals[0])
 preds={'random_forest':rf.predict(T),'residual_ridge':te.past_rate.to_numpy()+ridge.predict(T),'recent_logistic':lr.predict_proba(T)[:,1],'recency_average':recency,'damped_trend':te.past_rate+.25*(te.lag1.fillna(te.past_rate)-te.lag3.fillna(te.past_rate))}
 for name,values in preds.items():
  pp=np.clip(np.asarray(values),0,1);assert np.isfinite(pp).all()
  for row,value in zip(te.itertuples(),pp):res.append(dict(year=year,gu=row.gu,service=row.service,k=row.k,u=row.u,actual=row.u/row.k,model=name,pred=value))
r=pd.DataFrame(res);r['ae']=100*abs(r.pred-r.actual);r.to_csv(OUT/'followup_predictions.csv',index=False,encoding='utf-8-sig')
keys=['year','gu','service'];expected=set(base[keys].itertuples(index=False,name=None))
for name,t in r.groupby('model'):assert set(t[keys].itertuples(index=False,name=None))==expected
allr=pd.concat([base,r],ignore_index=True)
def met(t):return {'cells':len(t),'mae_pp':float(t.ae.mean()),'weighted_mae_pp':float(np.average(t.ae,weights=t.k))}
overall={name:met(t) for name,t in allr.groupby('model')};annual=[dict(year=int(y),model=name,**met(t)) for (y,name),t in allr.groupby(['year','model'])]
pd.DataFrame(annual).to_csv(OUT/'followup_annual.csv',index=False,encoding='utf-8-sig')
unc={};rng=np.random.default_rng(17)
for name,t in r.groupby('model'):
 z=t.merge(base[keys+['ae']],on=keys,suffixes=('','_base'),validate='one_to_one');z['delta']=z.ae-z.ae_base
 cl=z.groupby(['gu','service']).delta.agg(['sum','count']);ix=rng.integers(len(cl),size=(2000,len(cl)));draw=cl['sum'].to_numpy()[ix].sum(axis=1)/cl['count'].to_numpy()[ix].sum(axis=1)
 unc[name]={'delta_mae_pp':float(z.delta.mean()),'ci95':np.quantile(draw,[.025,.975]).tolist(),'better_years':int((z.groupby('year').delta.mean()<0).sum())}
report={'overall':overall,'annual':annual,'paired':unc,'panel_sha256':hashlib.sha256((OUT/'prediction_cells.csv').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'note':'Post-evaluation exploratory comparison; common 160 targets, no new independent test; clustered CI not multiplicity adjusted.'}
(OUT/'followup_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'overall':overall,'paired':unc},ensure_ascii=False,indent=2))
