"""D-05 detailed-category model comparison using frozen DB-derived panels."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d05'
g=pd.read_csv(OUT/'category_panel.csv');parent=pd.read_csv(OUT/'prediction_cells.csv');old=pd.read_csv(OUT/'category_predictions.csv')
lookup={(int(r.year),r.gu,r.service,r.category):(r.n,r.k,r.u) for r in g.itertuples()};rows=[]
for year in range(2015,2026):
 hist=g[g.year.between(year-3,year-1)];h=hist.groupby(['gu','service','category'])[['n','k','u']].sum().reset_index()
 city=hist.groupby(['service','category'])[['k','u']].sum()
 h=h[(h.k>=30)&(h.k/h.n>=.8)].merge(parent[parent.year==year][['gu','service','past_rate']],on=['gu','service'],validate='many_to_one')
 for r in h.itertuples():
  n,k,u=lookup.get((year,r.gu,r.service,r.category),(0,0,0))
  if k==0:continue
  past=np.array([lookup.get((year-i,r.gu,r.service,r.category),(0,0,0)) for i in (1,2,3)])
  rates=[x[2]/x[1] if x[1] else np.nan for x in past];cw=city.loc[(r.service,r.category)];cp=cw.u/cw.k;w=(past*np.array([.5,.3,.2])[:,None]).sum(axis=0)
  rows.append(dict(year=year,gu=r.gu,service=r.service,category=r.category,n=n,k=k,u=u,lag1=rates[0],lag2=rates[1],lag3=rates[2],detail=r.u/r.k,blend=(r.u+30*r.past_rate)/(r.k+30),recency=w[2]/w[1],city_shrink=(r.u+30*cp)/(r.k+30),parent=r.past_rate,city=cp,logk=np.log1p(r.k),coverage=r.k/r.n))
panel=pd.DataFrame(rows);panel.to_csv(OUT/'category_model_cells.csv',index=False,encoding='utf-8-sig')
keys=['year','gu','service','category'];assert set(panel[panel.year>=2020][keys].itertuples(index=False,name=None))==set(old[keys].itertuples(index=False,name=None))
num=['lag1','lag2','lag3','detail','parent','city','logk','coverage'];cat=['gu','service','category'];result=[]
for year in range(2020,2026):
 tr=panel[panel.year<year];te=panel[panel.year==year];assert tr.year.max()<year
 prep=ColumnTransformer([('num',make_pipeline(SimpleImputer(strategy='median'),StandardScaler()),num),('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cat)])
 X=prep.fit_transform(tr);T=prep.transform(te);target=tr.u/tr.k
 XX=np.repeat(X,2,axis=0);yy=np.tile([0,1],len(tr));ww=np.column_stack([tr.k-tr.u,tr.u]).ravel();keep=ww>0
 lr=LogisticRegression(C=.1,max_iter=2000);lr.fit(XX[keep],yy[keep],sample_weight=ww[keep])
 gb=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,min_samples_leaf=15,l2_regularization=10,learning_rate=.05,random_state=17,early_stopping=False);gb.fit(X,target,sample_weight=tr.k)
 ridge=Ridge(alpha=100);ridge.fit(X,target-tr.detail,sample_weight=tr.k/tr.k.mean())
 preds={'detail3':te.detail,'blend30':te.blend,'recency':te.recency,'city_shrink':te.city_shrink,'logistic':lr.predict_proba(T)[:,1],'boosting':gb.predict(T),'residual_ridge':te.detail.to_numpy()+ridge.predict(T)}
 for name,values in preds.items():
  pp=np.clip(np.asarray(values),0,1);assert np.isfinite(pp).all()
  for row,p in zip(te.itertuples(),pp):result.append(dict(year=year,gu=row.gu,service=row.service,category=row.category,n=row.n,k=row.k,u=row.u,actual=row.u/row.k,model=name,pred=float(p)))
r=pd.DataFrame(result);r['ae']=100*abs(r.pred-r.actual);r.to_csv(OUT/'category_model_predictions.csv',index=False,encoding='utf-8-sig')
def met(t):return {'cells':len(t),'known':int(t.k.sum()),'mae_pp':float(t.ae.mean()),'weighted_mae_pp':float(np.average(t.ae,weights=t.k))}
overall={m:met(t) for m,t in r.groupby('model')};annual=[dict(year=int(y),model=m,**met(t)) for (y,m),t in r.groupby(['year','model'])];pd.DataFrame(annual).to_csv(OUT/'category_model_annual.csv',index=False,encoding='utf-8-sig')
bycat=[dict(service=s,category=c,model=m,**met(t)) for (s,c,m),t in r.groupby(['service','category','model'])];pd.DataFrame(bycat).to_csv(OUT/'category_model_by_category.csv',index=False,encoding='utf-8-sig')
wide=r.pivot(index=keys,columns='model',values='ae');unc={};rng=np.random.default_rng(17)
for m in overall:
 if m=='detail3':continue
 z=(wide[m]-wide.detail3).rename('delta').reset_index();cl=z.groupby(['gu','service','category']).delta.agg(['sum','count']);ix=rng.integers(len(cl),size=(2000,len(cl)));draw=cl['sum'].to_numpy()[ix].sum(axis=1)/cl['count'].to_numpy()[ix].sum(axis=1)
 unc[m]={'delta_pp':float(z.delta.mean()),'ci95':np.quantile(draw,[.025,.975]).tolist(),'better_years':int((z.groupby('year').delta.mean()<0).sum())}
sub=r[(r.k>=20)&(r.k/r.n>=.8)];sens={m:met(t) for m,t in sub.groupby('model')}
rep={'overall':overall,'annual':annual,'paired_vs_detail3':unc,'posthoc_quality_subset':sens,'source_hash':hashlib.sha256((OUT/'category_panel.csv').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'limitations':'Exploratory; previously seen years; latest addresses/category may not match opening time; no multi-comparison correction; posthoc subset not an adoption criterion.'}
(OUT/'category_model_results.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'overall':overall,'paired':unc,'sensitivity':sens},ensure_ascii=False,indent=2))
