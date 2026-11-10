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
 protocol=json.loads((OUT/'final2025_protocol.json').read_text(encoding='utf-8'))
 assert (protocol['train'],protocol['calibration'],protocol['evaluation'])==(2021,2023,2025)
 windows=[]
 for train,cal,test in [(2021,2023,2025)]:
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
 w=windows[0]
 # Intermediate corrections are diagnostics only; candidate was frozen before scoring.
 frozen={k:w['overall'][k] for k in ['baseline','pooled','region_cal']}
 regions=w['regions']; eligible=[r for r in regions if not r['small_sample']]
 high_gap=[r for r in eligible if abs(r['scores']['region_cal']['predicted_pct']-r['scores']['region_cal']['actual_pct'])>5]
 beat=all(frozen['region_cal'][m]<frozen['baseline'][m] for m in ['brier','log_loss'])
 out={'protocol':protocol,'reference_date':str(ref.date()),'candidate':'region_cal','beats_baseline_both':beat,'window':w,'eligible_region_cells':len(eligible),'high_gap_region_cells':len(high_gap),'hashes':{'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__)),'protocol':snapshot_sha256(OUT/'final2025_protocol.json')},'quality':quality}
 (OUT/'final2025_result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 2025년 고정 모델 마무리 평가','','2021 학습 → 2023 보정 → 2025 평가. 사전 고정 후보는 지역 축소보정 LR이며 다른 후보로 바꾸지 않습니다. 2025는 과거 프로젝트 실험에서 본 적이 있어 완전 미사용 시험으로 주장하지 않습니다.','','|모델|표본|실제%|평균예측%|Brier|log loss|AUC|','|---|---:|---:|---:|---:|---:|---:|']
 for name,m in frozen.items():lines.append(f"|{name}|{m['n']}|{m['actual_pct']:.3f}|{m['predicted_pct']:.3f}|{m['brier']:.6f}|{m['log_loss']:.6f}|{m['roc_auc']:.4f}|")
 lines+=['',f'기준선 대비 두 오차 모두 개선: {beat}. 충분표본 지역·업종 조합 {len(eligible)}개 중 평균확률 오차 5%p 초과 {len(high_gap)}개. 5%p는 진단용 표시이며 통계적 유의성 기준이 아닙니다.','','|업종·지역|표본|실제%|평균예측%|예측−실제(%p)|','|---|---:|---:|---:|---:|']
 for r in sorted(eligible,key=lambda x:abs(x['scores']['region_cal']['predicted_pct']-x['scores']['region_cal']['actual_pct']),reverse=True)[:10]:
  m=r['scores']['region_cal'];lines.append(f"|{r['industry']} · {r['gu']}|{m['n']}|{m['actual_pct']:.2f}|{m['predicted_pct']:.2f}|{m['predicted_pct']-m['actual_pct']:.2f}|")
 lines+=['','전체 업종·지역 점수와 표본은 JSON에 보관합니다. 신규 창업 실패 확률이 아닌 영업 중 인허가 기록의 향후 365일 폐업 신고 예측입니다. 단기 행사 유지·현재 구군·반복 인허가·사후 수정된 스냅샷 한계가 있습니다. 결과에 맞춘 추가 튜닝 및 자동 서비스 반영은 하지 않습니다.']
 (OUT/'final2025_result.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('\n'.join(lines),flush=True)
if __name__=='__main__':main()
