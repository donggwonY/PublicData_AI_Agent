"""All available industries: pooled versus separate landmark models."""
import json,warnings
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from scipy.optimize import minimize_scalar
from scipy.special import expit,logit
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
 for train,cal,test in [(2011,2013,2015),(2013,2015,2017),(2016,2018,2020),(2018,2021,2023)]:
  a,b=cohort(train),cohort(test);assert pd.Timestamp(train,1,1)+pd.Timedelta(days=365)<pd.Timestamp(test,1,1)
  c=cohort(cal)
  assert pd.Timestamp(train,1,1)+pd.Timedelta(days=365)<pd.Timestamp(cal,1,1)
  assert pd.Timestamp(cal,1,1)+pd.Timedelta(days=365)<pd.Timestamp(test,1,1)
  combined=pd.concat([c,b],ignore_index=True)
  pred,_=predict(a,combined,['industry','gu','age_band'])
  pc=pred[:len(c)];pooled=pred[len(c):]
  logits=logit(np.clip(pc,1e-6,1-1e-6));y=c.y.to_numpy()
  fit=minimize_scalar(lambda delta:float(np.mean(np.logaddexp(0,logits+delta)-y*(logits+delta))),bounds=(-5,5),method='bounded')
  assert fit.success
  shift=float(fit.x)
  global_cal=expit(logit(np.clip(pooled,1e-6,1-1e-6))+shift)
  cal_global=expit(logits+shift)
  baseline=np.zeros(len(b));group_cal=global_cal.copy();groups=[]
  for name,g in b.groupby('industry'):
   tr=a[a.industry.eq(name)];cg=c[c.industry.eq(name)];ix=g.index.to_numpy();ci=cg.index.to_numpy()
   baseline[ix]=cg.y.mean() if len(cg) else (tr.y.mean() if len(tr) else a.y.mean())
   delta=0.0
   if len(cg):
    target=(float(cg.y.sum())+500*float(cal_global[ci].mean()))/(len(cg)+500)
    gl=logits[ci]+shift
    opt=minimize_scalar(lambda d:float((expit(gl+d).mean()-target)**2),bounds=(-5,5),method='bounded')
    assert opt.success
    delta=float(opt.x)
    group_cal[ix]=expit(logit(np.clip(global_cal[ix],1e-6,1-1e-6))+delta)
   scores={n:metrics(g.y.to_numpy(),p[ix]) for n,p in [('baseline',baseline),('pooled',pooled),('global_cal',global_cal),('group_cal',group_cal)]}
   groups.append({'industry':name,'train_n':len(tr),'train_events':int(tr.y.sum()),'cal_n':len(cg),'cal_events':int(cg.y.sum()),'group_shift':delta,'small_sample':len(g)<200 or int(g.y.sum())<20,'scores':scores})
  assert sum(g['scores']['baseline']['n'] for g in groups)==len(b)
  assert sum(g['scores']['baseline']['events'] for g in groups)==int(b.y.sum())
  overall={n:metrics(b.y.to_numpy(),p) for n,p in [('baseline',baseline),('pooled',pooled),('global_cal',global_cal),('group_cal',group_cal)]}
  for n in overall:
   assert abs(sum(g['scores'][n]['brier']*g['scores'][n]['n'] for g in groups)/len(b)-overall[n]['brier'])<1e-12
  regional=group_cal.copy();regions=[]
  for (industry,gu),g in b.groupby(['industry','gu'],dropna=False):
   ix=g.index.to_numpy()
   cg=c[c.industry.eq(industry)&(c.gu.eq(gu) if pd.notna(gu) else c.gu.isna())];ci=cg.index.to_numpy()
   group_shift=next(x['group_shift'] for x in groups if x['industry']==industry)
   delta=0.0
   if len(cg):
    gl=logits[ci]+shift+group_shift
    target=(float(cg.y.sum())+500*float(expit(gl).mean()))/(len(cg)+500)
    opt=minimize_scalar(lambda d:float((expit(gl+d).mean()-target)**2),bounds=(-5,5),method='bounded')
    assert opt.success
    delta=float(opt.x)
   regional[ix]=expit(logit(np.clip(group_cal[ix],1e-6,1-1e-6))+delta)
   regions.append({'industry':industry,'gu':str(gu),'cal_n':len(cg),'region_shift':delta,'small_sample':len(g)<200 or int(g.y.sum())<20,'scores':{n:metrics(g.y.to_numpy(),p[ix]) for n,p in [('baseline',baseline),('pooled',pooled),('global_cal',global_cal),('group_cal',group_cal),('region_cal',regional)]}})
  overall['region_cal']=metrics(b.y.to_numpy(),regional)
  for group in groups:
   ix=b.index[b.industry.eq(group['industry'])].to_numpy()
   group['scores']['region_cal']=metrics(b.y.to_numpy()[ix],regional[ix])
  for model in overall:
   assert sum(x['scores'][model]['n'] for x in regions)==len(b)
   assert abs(sum(x['scores'][model]['brier']*x['scores'][model]['n'] for x in regions)/len(b)-overall[model]['brier'])<1e-12
  windows.append({'train':train,'cal':cal,'test':test,'global_shift':shift,'train_n':len(a),'overall':overall,'groups':groups,'regions':regions})
  print('evaluated',train,test,'groups',len(groups),'n',len(b),flush=True)
 summary=[]
 for name in sorted(f.industry.unique()):
  gs=[g for w in windows for g in w['groups'] if g['industry']==name]
  record={'industry':name,'evaluated_windows':len(gs),'small_sample_windows':sum(g['small_sample'] for g in gs)}
  for candidate in ['global_cal','group_cal','region_cal']:
   record[candidate+'_wins_vs_raw']=sum(g['scores'][candidate]['brier']<g['scores']['pooled']['brier'] and g['scores'][candidate]['log_loss']<g['scores']['pooled']['log_loss'] for g in gs)
  summary.append(record)
 out={'reference_date':str(ref.date()),'quality':quality,'windows':windows,'summary':summary,'hashes':{'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__))},'limitations':['Exploratory reused years, latest-snapshot cohorts, current gu, repeated permits.','500 pseudocount fixed before evaluation; no post-result tuning.','Industry closure report meanings differ. No deployment or 2025 evaluation.','Permit-level target, short events retained; no future-derived short_event or occupant flags used.','Region calibration shrinks toward industry calibration with fixed pseudocount 500. No new hyperparameter search.']}
 (OUT/'expanded42_calibration.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 42업종 확률 보정 및 지역별 오차 비교','','통합 LR 동일 모델의 미보정/전체 절편보정/업종별 축소보정500/업종·구군 축소보정500 비교. 이전 연도에서만 보정. 별도 기준선은 보정연도 업종별 신고평균. 이전 실험과 학습연도가 달라 점수 직접 비교 금지.','','|업종|평가 기간|전체보정 개선|업종보정 개선|지역보정 개선|소표본 기간|','|---|---:|---:|---:|---:|---:|']
 for r in summary:lines.append(f"|{r['industry']}|{r['evaluated_windows']}|{r['global_cal_wins_vs_raw']}|{r['group_cal_wins_vs_raw']}|{r['region_cal_wins_vs_raw']}|{r['small_sample_windows']}|")
 lines+=['','개선은 동일 모델 미보정 대비 Brier/log loss 모두 감소. 통계적 유의성·채택 확정 아님.','','|학습/보정/평가|모델|n|실제%|예측%|Brier|log loss|','|---|---|---:|---:|---:|---:|---:|']
 for w in windows:
  for name,r in w['overall'].items():lines.append(f"|{w['train']}/{w['cal']}/{w['test']}|{name}|{r['n']}|{r['actual_pct']:.2f}|{r['predicted_pct']:.2f}|{r['brier']:.6f}|{r['log_loss']:.6f}|")
 lines+=['','']
 lines[-1]='최신 자료에서 과거 영업점 재구성, 현재 구군·업종별 신고 정의·동일 인허가 반복 한계. 기존 평가연도 재사용 탐색. 소표본은 평가200 미만 또는 신고20 미만. 서비스 반영 없음.'
 (OUT/'expanded42_calibration.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('Calibration completed; regional metrics saved.')
if __name__=='__main__':main()
