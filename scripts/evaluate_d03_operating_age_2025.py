"""Fixed age-only model, prior-year intercept calibration; exploratory reused years."""
import json,warnings
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import expit,logit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 warnings.simplefilter('error',ConvergenceWarning)
 sp=ROOT/'service/data/processed/stores.parquet';f=pd.read_parquet(sp);f=f[f.service.eq('일반음식점')].copy()
 assert f.ld.notna().all() and not (f.closed&f.cd.isna()).any() and not (f.cd<f.ld).any()
 ref=pd.Timestamp(json.loads((sp.parent/'meta.json').read_text(encoding='utf-8'))['reference_date'])
 def cohort(y):
  t=pd.Timestamp(y,1,1);assert t+pd.Timedelta(days=365)<=ref
  a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy();age=(t-a.ld).dt.days
  a['age_band']=pd.cut(age,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['target']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int);return a
 rows=[]
 for train,cal,test in [(2021,2023,2025)]:
  assert pd.Timestamp(train,1,1)+pd.Timedelta(days=365)<pd.Timestamp(cal,1,1)
  assert pd.Timestamp(cal,1,1)+pd.Timedelta(days=365)<pd.Timestamp(test,1,1)
  a,b,c=map(cohort,[train,cal,test]);m=make_pipeline(OneHotEncoder(handle_unknown='ignore'),LogisticRegression(C=1,max_iter=2000,random_state=0))
  m.fit(a[['age_band']],a.target);pb=m.predict_proba(b[['age_band']])[:,1];pc=m.predict_proba(c[['age_band']])[:,1]
  z=logit(np.clip(pb,1e-6,1-1e-6));y=b.target.to_numpy()
  fit=minimize_scalar(lambda bias:float(np.mean(np.logaddexp(0,z+bias)-y*(z+bias))),bounds=(-5,5),method='bounded');assert fit.success and abs(fit.x)<4.99
  adjusted=expit(logit(np.clip(pc,1e-6,1-1e-6))+fit.x)
  pred={'train_mean':np.full(len(c),a.target.mean()),'calibration_year_mean':np.full(len(c),b.target.mean()),'age_raw':pc,'age_calibrated':adjusted}
  scores={n:metrics(c.target.to_numpy(),p) for n,p in pred.items()}
  codes,uni=pd.factorize(c.building_key.fillna(c.uid.astype(str)));counts=np.bincount(codes);delta=(adjusted-c.target.to_numpy())**2-(pc-c.target.to_numpy())**2;sums=np.bincount(codes,weights=delta);rng=np.random.default_rng(7);boot=[]
  for _ in range(1000):
   ix=rng.integers(0,len(uni),len(uni));boot.append(float(sums[ix].sum()/counts[ix].sum()))
  groups=[]
  for g,ix in c.groupby('age_band').groups.items():
   mask=c.index.isin(ix);groups.append({'band':g,'raw':metrics(c.target.to_numpy()[mask],pc[mask]),'calibrated':metrics(c.target.to_numpy()[mask],adjusted[mask])})
  assert sum(g['raw']['n'] for g in groups)==len(c)
  rows.append({'train':train,'cal':cal,'test':test,'bias':float(fit.x),'scores':scores,'groups':groups,'brier_difference_ci95_fixed_model':np.quantile(boot,[.025,.975]).tolist()})
 report={'windows':rows,'hashes':{'stores':snapshot_sha256(sp),'script':snapshot_sha256(Path(__file__))},'limitations':['Reused historical evaluation periods; exploratory, not independent final test.','Same permit may occur across years; no identity predictors.','Latest snapshot reconstruction, not verified historical availability.','Bootstrap conditional on trained/calibrated model; no refit/multiplicity correction.']}
 (OUT/'operating_age_2025.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 운영기간 모델 2025 후속 시간 평가','','운영기간만 LR C1을 고정하고 이후 과거연도에서 절편1개만 보정. 평가연도 사용해 재보정하지 않음. 기존 후보와 학습연도가 다르므로 같은 행의 보정 전후 비교만 보정효과로 해석.','','|학습/보정/평가|후보|실제%|예측%|Brier|log loss|','|---|---|---:|---:|---:|---:|']
 for w in rows:
  for name,s in w['scores'].items():lines.append(f"|{w['train']}/{w['cal']}/{w['test']}|{name}|{s['actual_pct']:.2f}|{s['predicted_pct']:.2f}|{s['brier']:.6f}|{s['log_loss']:.6f}|")
 lines+=['','2025 기존영업점 운영기간 모델 첫 평가지만, 기존 D-03에서 같은 연도의 다른 표본 결과를 확인한 상태이므로 완전한 블라인드 독립시험으로 주장하지 않음. 최신기록 재구성·같은 인허가 연도간 반복 한계 유지. 그룹합계·날짜간격·수렴 검사 통과. DB/서비스 변경 없음.']
 (OUT/'operating_age_2025.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines))
if __name__=='__main__':main()
