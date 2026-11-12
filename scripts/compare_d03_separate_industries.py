"""Compare separate LR models across every saved quarterly landmark, without tuning."""
import json,warnings
from pathlib import Path
import numpy as np,pandas as pd
from scipy.special import expit,logit
from scipy.optimize import minimize_scalar
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'

def main():
 warnings.simplefilter('error',ConvergenceWarning)
 source=OUT/'all_quarters_evaluation.json';old=json.loads(source.read_text(encoding='utf-8'))
 path=ROOT/'service/data/processed/stores.parquet'
 assert snapshot_sha256(path)==old['hashes']['stores']
 protocol={'scope':'All 96 saved quarters 2002-2025, all available industries, no sampling',
 'train':'Jan1 year-4','calibration':'Jan1 year-2','target':'Active permit closure report within next365 days',
 'features':['gu','age_band'],'model':'separate LR C1 max_iter2000 seed7 per industry',
 'eligibility':'training AND calibration each n>=200 events>=20 non-events>=20; no evaluation-label selection',
 'calibration_method':'industry-specific intercept by calibration logloss then region shift with shrink500',
 'comparison':'separate raw vs pooled raw isolates training; separate calibrated vs pooled candidate compares complete pipelines',
 'aggregate':'Same eligible industries per quarter; n-weighted Brier and logloss; excluded industries recorded',
 'warning':'Post-hoc experiment on reused evaluation data, not independent confirmation; no parameter search'}
 (OUT/'separate_industries_protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 f=pd.read_parquet(path);f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna();f=f[~bad].copy()
 def cohort(t):
  a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy().reset_index(drop=True)
  a['age_band']=pd.cut((t-a.ld).dt.days,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
  return a
 def x(a):return a[['gu','age_band']].astype('string').fillna('__MISSING__').astype(str)
 def enough(a):return len(a)>=200 and a.y.sum()>=20 and (1-a.y).sum()>=20
 results=[];fit_count=0
 for year in sorted({int(w['landmark'][:4]) for w in old['results']}):
  a=cohort(pd.Timestamp(year-4,1,1));c=cohort(pd.Timestamp(year-2,1,1));models={};skips={}
  for name in sorted(set(a.industry)|set(c.industry)):
   tr=a[a.industry.eq(name)];cal=c[c.industry.eq(name)].reset_index(drop=True)
   if not enough(tr) or not enough(cal):
    skips[name]={'reason':'training/calibration minimum not met','train_n':len(tr),'train_events':int(tr.y.sum()),'cal_n':len(cal),'cal_events':int(cal.y.sum())};continue
   model=make_pipeline(OneHotEncoder(handle_unknown='ignore'),LogisticRegression(C=1,max_iter=2000,random_state=7))
   model.fit(x(tr),tr.y);lc=logit(np.clip(model.predict_proba(x(cal))[:,1],1e-6,1-1e-6));y=cal.y.to_numpy()
   opt=minimize_scalar(lambda d:float(np.mean(np.logaddexp(0,lc+d)-y*(lc+d))),bounds=(-5,5),method='bounded');assert opt.success
   shift=float(opt.x);regional={}
   for gu,g in cal.groupby('gu',dropna=False):
    ix=g.index.to_numpy();gl=lc[ix]+shift;target=(g.y.sum()+500*expit(gl).mean())/(len(g)+500)
    opt=minimize_scalar(lambda d:float((expit(gl+d).mean()-target)**2),bounds=(-5,5),method='bounded');assert opt.success
    regional[str(gu)]=float(opt.x)
   models[name]=(model,shift,regional);fit_count+=1
  for w in [w for w in old['results'] if w['landmark'].startswith(str(year))]:
   b=cohort(pd.Timestamp(w['landmark']));assert len(b)==w['n'] and int(b.y.sum())==w['events']
   groups=[];excluded=[]
   for name,g in b.groupby('industry'):
    saved=next(z for z in w['groups'] if z['industry']==name)
    assert len(g)==saved['scores']['raw']['n'] and int(g.y.sum())==saved['scores']['raw']['events']
    if name not in models:
     excluded.append(dict(industry=name,n=len(g),**skips.get(name,{'reason':'not observed in training/calibration'})));continue
    model,shift,regional=models[name];raw=model.predict_proba(x(g))[:,1]
    pred=expit(logit(np.clip(raw,1e-6,1-1e-6))+shift)
    pred=expit(logit(np.clip(pred,1e-6,1-1e-6))+np.array([regional.get(str(gu),0) for gu in g.gu]))
    groups.append(dict(industry=name,scores={'pooled_raw':saved['scores']['raw'],'pooled_cal':saved['scores']['candidate'],
        'separate_raw':metrics(g.y.to_numpy(),raw),'separate_cal':metrics(g.y.to_numpy(),pred)}))
   total=sum(g['scores']['pooled_raw']['n'] for g in groups)
   aggregate={mod:{metric:sum(g['scores'][mod][metric]*g['scores'][mod]['n'] for g in groups)/total for metric in ['brier','log_loss']} for mod in ['pooled_raw','pooled_cal','separate_raw','separate_cal']} if total else {}
   assert total+sum(e['n'] for e in excluded)==len(b)
   results.append(dict(landmark=w['landmark'],n=total,total_n=len(b),groups=groups,excluded=excluded,aggregate=aggregate))
  print('completed',year,'models',len(models),flush=True)
 summary=[]
 for label,start in [('all','2002'),('since2013','2013'),('recent','2023')]:
  rows=[w for w in results if w['landmark']>=start and w['n']]
  for kind in ['raw','cal']:
   wins=sum(all(w['aggregate']['separate_'+kind][m]<w['aggregate']['pooled_'+kind][m] for m in ['brier','log_loss']) for w in rows)
   summary.append(dict(scope=label,comparison=kind,quarters=len(rows),wins=wins))
 out=dict(protocol=protocol,summary=summary,fit_count=fit_count,results=results,hashes={'source':snapshot_sha256(source),'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__))})
 (OUT/'separate_industries.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 업종별 별도 학습과 통합 모델 비교','','기존96분기 전체를 대상으로 업종별 로지스틱 회귀를 학습했다. 입력은 지역·운영기간이며, 통합 모델은 여기에 업종을 포함한다. 학습·보정 자료만으로 계산 가능 여부를 정하며 평가 결과로 업종을 고르지 않았다. 미보정 비교와 보정 후 비교를 함께 제시해 학습 방식의 영향과 전체 절차의 영향을 구분한다.','','|기간|비교|평가 분기|별도 학습 두 오차 개선 분기|','|---|---|---:|---:|']
 for s in summary:lines.append(f"|{s['scope']}|{s['comparison']}|{s['quarters']}|{s['wins']}|")
 lines+=['','## 최근 12분기 업종별 결과','','|업종|별도학습 가능 분기|미보정 개선|보정 후 개선|','|---|---:|---:|---:|']
 for name in sorted(f.industry.unique()):
  gs=[g for w in results if w['landmark']>='2023' for g in w['groups'] if g['industry']==name]
  wins={kind:sum(all(g['scores']['separate_'+kind][m]<g['scores']['pooled_'+kind][m] for m in ['brier','log_loss']) for g in gs) for kind in ['raw','cal']}
  lines.append(f"|{name}|{len(gs)}|{wins['raw']}|{wins['cal']}|")
 lines+=['','比較は'.replace('比較は','비교는')+' 동일 분기·동일 업종·동일 평가행에서 수행했다. 전체 점수는 학습 가능한 업종만 포함하며 제외 업종과 표본 수를 JSON에 남긴다. 0개 분기는 실패가 아니라 학습·보정 자료 부족이다. 분기 결과는 관찰기간이 겹치므로 독립 시행이 아니다.','','기존 평가 결과를 확인한 뒤 추가한 실험이므로 독립 최종 검증이 아니다. 업종별 결과를 보고 유리한 모델을 선택한 서비스 성능으로 주장하지 않는다. 앱·운영DB·배포는 변경하지 않았다.']
 (OUT/'separate_industries.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
