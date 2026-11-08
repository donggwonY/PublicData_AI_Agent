"""All available industries: pooled versus separate landmark models."""
import json,warnings
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from sklearn.ensemble import RandomForestClassifier
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 warnings.simplefilter('error',ConvergenceWarning)
 path=ROOT/'service/data/processed/stores.parquet';f=pd.read_parquet(path)
 ref=pd.Timestamp(json.loads((path.parent/'meta.json').read_text(encoding='utf-8'))['reference_date'])
 f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna()
 quality=[{'service':str(n),'rows':len(g),'excluded_date_rows':int(bad.loc[g.index].sum())} for n,g in f.groupby('service',dropna=False)]
 f=f[~bad].copy()
 def cohort(y):
  t=pd.Timestamp(y,1,1);assert t+pd.Timedelta(days=365)<=ref
  a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy().reset_index(drop=True)
  age=(t-a.ld).dt.days
  a['age_band']=pd.cut(age,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
  return a
 def predict(a,b,cols):
  if a.y.nunique()<2:return np.full(len(b),a.y.mean()),True
  m=make_pipeline(OneHotEncoder(handle_unknown='ignore'),LogisticRegression(C=1,max_iter=2000,random_state=7))
  m.fit(a[cols].astype('string').fillna('__MISSING__').astype(str),a.y)
  return m.predict_proba(b[cols].astype('string').fillna('__MISSING__').astype(str))[:,1],False
 windows=[]
 for train,test in [(2013,2015),(2015,2017),(2018,2020),(2021,2023)]:
  a,b=cohort(train),cohort(test);assert pd.Timestamp(train,1,1)+pd.Timedelta(days=365)<pd.Timestamp(test,1,1)
  pooled,_=predict(a,b,['industry','gu','age_band'])
  cols=['industry','gu','age_band']
  rf=make_pipeline(OneHotEncoder(handle_unknown='ignore'),RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=7,n_jobs=2))
  rf.fit(a[cols].astype('string').fillna('__MISSING__').astype(str),a.y)
  separate=rf.predict_proba(b[cols].astype('string').fillna('__MISSING__').astype(str))[:,1]
  baseline=np.zeros(len(b));groups=[]
  for name,g in b.groupby('industry'):
   tr=a[a.industry.eq(name)];ix=g.index.to_numpy()
   if tr.empty:raise ValueError('Industry absent from training')
   baseline[ix]=tr.y.mean();fallback=False
   scores={n:metrics(g.y.to_numpy(),p[ix]) for n,p in [('baseline',baseline),('pooled',pooled),('pooled_rf',separate)]}
   groups.append({'industry':name,'train_n':len(tr),'train_events':int(tr.y.sum()),'constant_fallback':fallback,'small_sample':len(g)<200 or int(g.y.sum())<20,'scores':scores})
  assert sum(g['scores']['baseline']['n'] for g in groups)==len(b)
  assert sum(g['scores']['baseline']['events'] for g in groups)==int(b.y.sum())
  overall={n:metrics(b.y.to_numpy(),p) for n,p in [('baseline',baseline),('pooled',pooled),('pooled_rf',separate)]}
  for n in overall:
   assert abs(sum(g['scores'][n]['brier']*g['scores'][n]['n'] for g in groups)/len(b)-overall[n]['brier'])<1e-12
  windows.append({'train':train,'test':test,'train_n':len(a),'overall':overall,'groups':groups})
  print('evaluated',train,test,'groups',len(groups),'n',len(b),flush=True)
 summary=[]
 for name in sorted(f.industry.unique()):
  gs=[next(g for g in w['groups'] if g['industry']==name) for w in windows]
  summary.append({'industry':name,'pooled_both_improved':sum(g['scores']['pooled']['brier']<g['scores']['baseline']['brier'] and g['scores']['pooled']['log_loss']<g['scores']['baseline']['log_loss'] for g in gs),'rf_both_improved':sum(g['scores']['pooled_rf']['brier']<g['scores']['baseline']['brier'] and g['scores']['pooled_rf']['log_loss']<g['scores']['baseline']['log_loss'] for g in gs),'small_sample_windows':sum(g['small_sample'] for g in gs)})
 out={'reference_date':str(ref.date()),'raw_services':len(quality),'analysis_groups':int(f.industry.nunique()),'quality':quality,'windows':windows,'summary':summary,'hashes':{'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__))},'limitations':['Retrospective current snapshot, not verified historical availability.','Different industry reporting practices; closure report is not business failure.','Same permits may repeat over years; not independent new-store evaluation.','Reused evaluation years, exploratory; 2025 not used.','No service adoption or DB writes.']}
 (OUT/'all_industry_nonlinear.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 전체 업종 비선형 모델 비교','','16원천업종→15분석그룹(의원·병원 통합). 기준일 영업점의 다음365일 신고. 42업종 확보·분석 완료가 아님. 업종별 학습평균·통합 LR·통합 RF150/깊이8/잎30/sqrt/seed7 사전고정, 2025 미사용.','','|업종|통합모델 개선기간/4|통합 RF 개선기간/4|소표본 기간/4|','|---|---:|---:|---:|']
 for s in summary:lines.append(f"|{s['industry']}|{s['pooled_both_improved']}|{s['rf_both_improved']}|{s['small_sample_windows']}|")
 lines+=['','개선: 업종별 학습평균 대비 Brier와 log loss 모두 감소. 통계적 유의성 검정이나 최종 채택 기준이 아님. 소표본: 평가200건 미만 또는 신고20건 미만.','','|평가연도|모델|n|실제%|예측%|Brier|log loss|','|---|---|---:|---:|---:|---:|---:|']
 for w in windows:
  for n,s in w['overall'].items():lines.append(f"|{w['test']}|{n}|{s['n']}|{s['actual_pct']:.2f}|{s['predicted_pct']:.2f}|{s['brier']:.6f}|{s['log_loss']:.6f}|")
 lines+=['','업종별 상세 점수와 날짜제외는 JSON에 보관. 전체 평균은 큰 업종의 영향을 받음. 최신 스냅샷·현재구군·신고정의·반복인허가·기존평가연도 재사용 한계. 서비스 적용 아님.']
 (OUT/'all_industry_nonlinear.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
