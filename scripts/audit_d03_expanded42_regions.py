"""42-industry snapshot: fixed pooled LR/RF comparison, permit-level landmark target."""
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
 prior=json.loads((OUT/'expanded42_experiment.json').read_text(encoding='utf-8'))
 assert prior['hashes']['stores']==snapshot_sha256(path)
 selected=[x['industry'] for x in prior['summary'] if x['evaluated_windows']==4 and x['small_sample_windows']==0 and max(x['pooled_both_improved'],x['rf_both_improved'])==4]
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
   baseline[ix]=tr.y.mean() if len(tr) else a.y.mean();fallback=tr.empty
   scores={n:metrics(g.y.to_numpy(),p[ix]) for n,p in [('baseline',baseline),('pooled',pooled),('pooled_rf',separate)]}
   groups.append({'industry':name,'train_n':len(tr),'train_events':int(tr.y.sum()),'constant_fallback':fallback,'small_sample':len(g)<200 or int(g.y.sum())<20,'scores':scores})
  assert sum(g['scores']['baseline']['n'] for g in groups)==len(b)
  assert sum(g['scores']['baseline']['events'] for g in groups)==int(b.y.sum())
  overall={n:metrics(b.y.to_numpy(),p) for n,p in [('baseline',baseline),('pooled',pooled),('pooled_rf',separate)]}
  for n in overall:
   assert abs(sum(g['scores'][n]['brier']*g['scores'][n]['n'] for g in groups)/len(b)-overall[n]['brier'])<1e-12
  regions=[]
  for (industry,gu),g in b[b.industry.isin(selected)].groupby(['industry','gu'],dropna=False):
   ix=g.index.to_numpy()
   scores={n:metrics(g.y.to_numpy(),p[ix]) for n,p in [('baseline',baseline),('pooled',pooled),('pooled_rf',separate)]}
   regions.append({'industry':industry,'gu':str(gu),'small_sample':len(g)<200 or int(g.y.sum())<20,'scores':scores})
  for industry in selected:
   cells=[x for x in regions if x['industry']==industry]
   group=next(g for g in groups if g['industry']==industry)
   for model in ['baseline','pooled','pooled_rf']:
    total=group['scores'][model]
    assert sum(x['scores'][model]['n'] for x in cells)==total['n']
    assert abs(sum(x['scores'][model]['brier']*x['scores'][model]['n'] for x in cells)/total['n']-total['brier'])<1e-12
  previous=next(w for w in prior['windows'] if w['test']==test)
  for model in overall:
   assert abs(overall[model]['brier']-previous['overall'][model]['brier'])<1e-10
  windows.append({'train':train,'test':test,'train_n':len(a),'overall':overall,'groups':groups,'regions':regions})
  print('evaluated',train,test,'groups',len(groups),'n',len(b),flush=True)
 out={'selected_industries':selected,'windows':windows,'hashes':{'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__)),'parent_result':snapshot_sha256(OUT/'expanded42_experiment.json')},'limitations':['Selected using same evaluation years: diagnostic only, not independent validation.','Current gu, permit-level labels and short events retained; same limitations as parent experiment.','Small sample: n<200 or events<20; no inference from sparse cells.']}
 (OUT/'expanded42_regions.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 改善候補8業種の地域別診断'.replace('改善候補8業種の地域別診断','개선 후보 8업종의 지역별 오차 점검'),'','기존 4개 평가기간에서 고른 업종의 사후 진단이며 독립 검증이 아닙니다. 모델 재선택·보정은 하지 않았습니다. 소표본은 n<200 또는 신고<20. 지역별 합계 및 원 실험 점수 일치 검증을 통과했습니다.','','|업종|모델|2023 충분표본 지역|두 오차 개선 지역|최대 절대 평균오차 지역|예측−실제(%p)|','|---|---|---:|---:|---|---:|']
 latest=windows[-1]
 for industry in selected:
  cells=[x for x in latest['regions'] if x['industry']==industry and not x['small_sample']]
  for model in ['pooled','pooled_rf']:
   better=sum(x['scores'][model]['brier']<x['scores']['baseline']['brier'] and x['scores'][model]['log_loss']<x['scores']['baseline']['log_loss'] for x in cells)
   worst=max(cells,key=lambda x:abs(x['scores'][model]['predicted_pct']-x['scores'][model]['actual_pct'])) if cells else None
   gap=worst['scores'][model]['predicted_pct']-worst['scores'][model]['actual_pct'] if worst else 0
   gap_text=f"{gap:.2f}" if worst else "—"
   lines.append(f"|{industry}|{model}|{len(cells)}|{better}|{worst['gu'] if worst else '판단 보류'}|{gap_text}|")
 lines+=['','음수는 과소예측입니다. 두 오차 개선은 업종 학습평균 대비 Brier·log loss 모두 감소한 경우입니다. 지역별 평균 오차와 개별 위험 구분 성능은 다릅니다. 지역 순위는 통계적 유의성이나 지역 위험 순위가 아닙니다. 과거 행정구역과 현재 구군 표기의 차이도 검증되지 않았습니다. 4기간 상세 지역 점수는 JSON에 보관하며 서비스·DB 반영은 없습니다.']
 (OUT/'expanded42_regions.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('\n'.join(lines),flush=True)
if __name__=='__main__':main()
