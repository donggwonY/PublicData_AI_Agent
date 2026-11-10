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
 original=json.loads((OUT/'final2025_result.json').read_text(encoding='utf-8'))
 assert snapshot_sha256(path)==original['hashes']['stores']
 for model in overall:
  for metric in ['brier','log_loss']:
   assert abs(overall[model][metric]-original['window']['overall'][model][metric])<1e-12
 yy=b.y.to_numpy()
 predictions={'baseline':baseline,'raw':pooled,'calibrated':regional}
 losses={}
 for name,pp in predictions.items():
  pp=np.clip(pp,np.finfo(float).eps,1-np.finfo(float).eps)
  losses[name]={'brier':(pp-yy)**2,'log_loss':-(yy*np.log(pp)+(1-yy)*np.log1p(-pp))}
 uid=b['uid'].astype('string')
 assert uid.notna().all() and uid.str.len().gt(0).all(), 'Missing place IDs need explicit cluster handling'
 pairs=[('raw','baseline'),('calibrated','baseline'),('calibrated','raw')]
 data=pd.DataFrame({'uid':uid,'n':1})
 keys=[]
 for candidate,reference in pairs:
  for metric in ['brier','log_loss']:
   key=f'{candidate}_minus_{reference}:{metric}';keys.append(key)
   data[key]=losses[candidate][metric]-losses[reference][metric]
 clusters=data.groupby('uid',sort=True)[['n']+keys].sum().to_numpy(dtype=float)
 assert int(clusters[:,0].sum())==len(b)
 rng=np.random.default_rng(20261110);reps=2000;draws=np.empty((reps,len(keys)))
 for i in range(reps):
  sample=clusters[rng.integers(0,len(clusters),len(clusters))].sum(axis=0)
  draws[i]=sample[1:]/sample[0]
 point=clusters[:,1:].sum(axis=0)/clusters[:,0].sum()
 intervals=[]
 for j,key in enumerate(keys):
  low,high=np.quantile(draws[:,j],[.025,.975])
  intervals.append({'comparison':key,'difference':float(point[j]),'ci95_low':float(low),'ci95_high':float(high)})
 out={'n':len(b),'place_clusters':len(clusters),'replicates':reps,'seed':20261110,'method':'Paired percentile bootstrap sampling uid clusters with replacement; loss mean weighted by sampled permit count. Conditional on fixed fitted model; training not bootstrapped.','intervals':intervals,'hashes':{'stores':snapshot_sha256(path),'source_result':snapshot_sha256(OUT/'final2025_result.json'),'script':snapshot_sha256(Path(__file__))},'limitations':['Post-hoc assessment; repeated inspection of 2025, not independent confirmatory testing.','Clusters reflect current uid, not proven historical unique businesses.','Does not account for cross-place spatial dependence or future time shifts.','Pointwise 95% intervals, not simultaneous multiple-comparison correction.','No subgroup significance claim, model tuning, DB or service change.']}
 (OUT/'final2025_uncertainty.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 固定モデル誤差差の不確実性'.replace('固定モデル誤差差の不確実性','고정 모델 오차 차이의 불확실성'),' ',f'2025 평가 {len(b):,}건, 자리 ID {len(clusters):,}개를 단위로 동일 표본을 두 모델에 적용하여 2,000회 재추출했습니다. 음수는 비교 대상보다 오차가 작다는 뜻입니다. 모델 점수 재현과 표본 합계 검증 통과.','','|비교·지표|오차 차이|95% 구간 하한|상한|','|---|---:|---:|---:|']
 for x in intervals:lines.append(f"|{x['comparison']}|{x['difference']:.7f}|{x['ci95_low']:.7f}|{x['ci95_high']:.7f}|")
 lines+=['','학습 모델을 고정한 조건부 표본 불확실성입니다. 같은 자리 내 연관성은 반영하지만 지역 간 의존성·새 시기의 변화·학습 표본 불확실성은 포함하지 않습니다. 사후 점검이며 2025년 반복 열람과 다중 비교 한계가 있습니다. 통계적 차이가 관찰되어도 효과가 크거나 서비스에 적합하다는 뜻은 아닙니다. 업종별 유의성 검증을 했다고 해석하지 않습니다.']
 (OUT/'final2025_uncertainty.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('\n'.join(lines),flush=True)
if __name__=='__main__':main()
