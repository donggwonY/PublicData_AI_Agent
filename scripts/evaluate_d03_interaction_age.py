"""Fixed industry-specific age interactions, paired with continuous-age model across all96 quarters."""
import json,warnings
from pathlib import Path
import numpy as np,pandas as pd
from scipy.special import expit,logit
from scipy.optimize import minimize_scalar
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, SplineTransformer
from sklearn.compose import ColumnTransformer
from sklearn.base import BaseEstimator, TransformerMixin
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'

class IndustryAgeFeatures(BaseEstimator, TransformerMixin):
 """Shared age curve plus regularized per-industry deviations."""
 def fit(self, X, y=None):
  self.categories_=OneHotEncoder(handle_unknown='ignore').fit(X[['industry','gu','age_band']])
  self.industries_=OneHotEncoder(handle_unknown='ignore').fit(X[['industry']])
  self.spline_=SplineTransformer(knots=np.log1p(np.array([0,1,3,5,10,20,40])).reshape(-1,1),degree=2,include_bias=False,extrapolation='constant').fit(X[['age_log']])
  return self
 def transform(self, X):
  categories=self.categories_.transform(X[['industry','gu','age_band']])
  age=self.spline_.transform(X[['age_log']])
  industry=self.industries_.transform(X[['industry']])
  blocks=[industry.multiply(age[:,j:j+1]) for j in range(age.shape[1])]
  return sparse.hstack([categories,sparse.csr_matrix(age),*blocks],format='csr')

def main():
 warnings.simplefilter('error',ConvergenceWarning)
 p=ROOT/'service/data/processed/stores.parquet';f=pd.read_parquet(p)
 previous=json.loads((OUT/'continuous_age_result.json').read_text(encoding='utf-8'))
 assert snapshot_sha256(p)==previous['hashes']['stores']
 ref=pd.Timestamp(json.loads((p.parent/'meta.json').read_text(encoding='utf-8'))['reference_date'])
 f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna();f=f[~bad].copy()
 def cohort(t):
  a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy().reset_index(drop=True)
  a['age_band']=pd.cut((t-a.ld).dt.days,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['age_log']=np.log1p((t-a.ld).dt.days/365.25)
  a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
  return a
 cols=['industry','gu','age_band']
 def x(a):
  z=a[cols].astype('string').fillna('__MISSING__').astype(str).copy()
  z['age_log']=a['age_log'].to_numpy()
  return z
 def shift_fit(gl,target):
  result=minimize_scalar(lambda d:float((expit(gl+d).mean()-target)**2),bounds=(-5,5),method='bounded');assert result.success
  return float(result.x)
 def enough(a):return len(a)>=200 and int(a.y.sum())>=20 and int((1-a.y).sum())>=20
 coverage=[];results=[]
 for year in range(2002,2026):
  train=pd.Timestamp(year-4,1,1);cal=pd.Timestamp(year-2,1,1)
  a=cohort(train);c=cohort(cal);model=None
  for month in [1,4,7,10]:
   t=pd.Timestamp(year,month,1)
   if t>ref:continue
   b=cohort(t);end=t+pd.Timedelta(days=365)
   reasons=[]
   if end>ref:reasons.append('365일 추적 미완료')
   if not len(b):reasons.append('평가 기록 없음')
   if not enough(a):reasons.append('학습 표본/양성/음성 최소 기준 미충족')
   if not enough(c):reasons.append('보정 표본/양성/음성 최소 기준 미충족')
   info={'landmark':str(t.date()),'train':str(train.date()),'cal':str(cal.date()),'n':len(b),'events':int(b.y.sum()) if end<=ref else None,'industry_groups':int(b.industry.nunique()),'train_n':len(a),'train_events':int(a.y.sum()),'cal_n':len(c),'cal_events':int(c.y.sum()),'skip_reasons':reasons}
   coverage.append(info)
   if reasons:continue
   assert train+pd.Timedelta(days=365)<cal and cal+pd.Timedelta(days=365)<t
   if model is None:
    features=IndustryAgeFeatures()
    model=make_pipeline(features,LogisticRegression(C=1,max_iter=2000,random_state=7))
    model.fit(x(a),a.y);pc=model.predict_proba(x(c))[:,1];lc=logit(np.clip(pc,1e-6,1-1e-6));yc=c.y.to_numpy()
    opt=minimize_scalar(lambda d:float(np.mean(np.logaddexp(0,lc+d)-yc*(lc+d))),bounds=(-5,5),method='bounded');assert opt.success
    global_shift=float(opt.x);cg=expit(lc+global_shift)
    industry_shift={}
    for name,g in c.groupby('industry'):
     ix=g.index.to_numpy();target=(g.y.sum()+500*cg[ix].mean())/(len(g)+500)
     industry_shift[name]=shift_fit(lc[ix]+global_shift,target)
    region_shift={}
    for (name,gu),g in c.groupby(['industry','gu'],dropna=False):
     ix=g.index.to_numpy();gl=lc[ix]+global_shift+industry_shift[name]
     target=(g.y.sum()+500*expit(gl).mean())/(len(g)+500)
     region_shift[(name,str(gu))]=shift_fit(gl,target)
    train_rates=a.groupby('industry').y.mean().to_dict();cal_rates=c.groupby('industry').y.mean().to_dict()
   raw=model.predict_proba(x(b))[:,1]
   pred=expit(logit(np.clip(raw,1e-6,1-1e-6))+global_shift)
   pred=expit(logit(np.clip(pred,1e-6,1-1e-6))+b.industry.map(industry_shift).fillna(0).to_numpy())
   pred=expit(logit(np.clip(pred,1e-6,1-1e-6))+np.array([region_shift.get((name,str(gu)),0) for name,gu in zip(b.industry,b.gu)]))
   train_mean=float(a.y.mean())
   baseline=np.array([cal_rates.get(name,train_rates.get(name,train_mean)) for name in b.industry])
   yy=b.y.to_numpy();scores={name:metrics(yy,pp) for name,pp in [('baseline',baseline),('raw',raw),('candidate',pred)]}
   groups=[]
   for name,g in b.groupby('industry'):
    ix=g.index.to_numpy();groups.append({'industry':name,'small_sample':bool(len(g)<200 or g.y.sum()<20),'scores':{n:metrics(yy[ix],pp[ix]) for n,pp in [('baseline',baseline),('raw',raw),('candidate',pred)]}})
   regions=[]
   saved=next(w for w in previous['results'] if w['landmark']==info['landmark'])
   assert saved['n']==len(b) and saved['events']==int(b.y.sum())
   results.append({**info,'scores':scores,'groups':groups,'regions':regions})
  if any(r['landmark'].startswith(str(year)) for r in results):print('completed year',year,'evaluated quarters',sum(r['landmark'].startswith(str(year)) for r in results),flush=True)
 out={'reference_date':str(ref.date()),'protocol':{'candidate':'LR C1 seed7 + global/industry/region shifts, shrink500','calendar':'all quarterly starts from earliest license year to snapshot','training':'Jan1 of year-4','calibration':'Jan1 of year-2','minimum_fit':'n>=200, events>=20, non-events>=20 in both training and calibration','minimum_note':'Computational screening only, not proof historical records are complete. Earlier periods retained in coverage, not silently discarded.','scope':'Every eligible active permit at each landmark; no random subsampling.'},'coverage':coverage,'results':results,'hashes':{'stores':snapshot_sha256(p),'script':snapshot_sha256(Path(__file__))},'limitations':['Historical completeness unverified; unusually sparse early closures must not be interpreted as real low risk.','Quarterly outcomes overlap, repeated permits; not independent trials.','Current snapshot/gu reconstructs history.','Early or poorly represented industries can use baseline fallback; no declaration of service eligibility.','Post-hoc expanded evaluation; no threshold tuning, no service update.']}
 out['protocol']=json.loads((OUT/'interaction_age_protocol.json').read_text(encoding='utf-8'))
 out['hashes']['comparison']=snapshot_sha256(OUT/'continuous_age_result.json')
 (OUT/'interaction_age_result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 pd.DataFrame(coverage).assign(skip_reasons=lambda z:z.skip_reasons.apply(' / '.join)).to_csv(OUT/'interaction_age_coverage.csv',index=False,encoding='utf-8-sig')
 print('DONE',len(coverage),'quarterly starts checked;',len(results),'evaluated',flush=True)
if __name__=='__main__':main()
