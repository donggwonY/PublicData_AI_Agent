"""Probability error audit and training-count-selected category experiment."""
import json,platform
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn
from fit_d03 import ROOT,metrics,snapshot_sha256,verify_snapshot_hash
from fit_d03_expanded import make_features,target,pipeline,fit

OUT=ROOT/'docs/d03'

def main():
 old=json.loads((OUT/'expanded_experiments.json').read_text(encoding='utf-8'))
 verify_snapshot_hash(ROOT/'service/data/processed/stores.parquet',old['hashes']['stores'])
 f=make_features(pd.read_parquet(ROOT/'service/data/processed/stores.parquet'))
 early=f[f.ld.dt.year.between(2010,2013)].copy();early['event']=target(early)
 counts=early.groupby('category').event.agg(['count','sum']).reset_index().sort_values(['count','category'],ascending=[False,True])
 eligible=counts[(counts['count']>=1000)&(counts['sum']>=50)]
 assert len(eligible)>0
 chosen=str(eligible.iloc[0].category);print('Selected from training counts:',chosen,flush=True)
 audits=[];results=[]
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)].copy()
  assert not set(tr.index)&set(va.index)
  assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min()
  y,yv=target(tr),target(va);constant=np.full(len(va),y.mean())
  pooled={}
  for kind in ['logistic','forest']:
   pooled[kind]=fit(pipeline(kind,extra=True),tr,y).predict_proba(va)[:,1]
  reference=next(w for w in old['windows'] if w['window']==f'{start}-{stop}')['scores']['forest_context']
  total=metrics(yv,pooled['forest'])
  for k in ['n','events','brier','log_loss','predicted_pct']:assert np.isclose(total[k],reference[k],atol=1e-5,rtol=1e-4)
  va['open_year']=va.ld.dt.year.astype(str)
  for field in ['category','gu','open_year']:
   groups=[]
   for value in sorted(va[field].unique()):
    mask=va[field].eq(value).to_numpy();m=metrics(yv[mask],pooled['forest'][mask]);base=metrics(yv[mask],constant[mask])
    groups.append({'window':f'{start}-{stop}','field':field,'value':value,**m,'gap_pp':m['predicted_pct']-m['actual_pct'],'constant_brier':base['brier'],'excess_brier':m['brier']-base['brier'],'small_sample':m['n']<200 or m['events']<20})
   assert sum(g['n'] for g in groups)==total['n'] and sum(g['events'] for g in groups)==total['events']
   assert np.isclose(sum(g['n']*g['brier'] for g in groups)/total['n'],total['brier'])
   audits.extend(groups)
  ct=tr[tr.category.eq(chosen)];mask=va.category.eq(chosen).to_numpy();cv=va[mask];cy=target(ct);cyv=yv[mask]
  assert len(np.unique(cy))==2 and len(cv)>0
  preds={'global_constant':np.full(len(cv),y.mean()),'category_constant':np.full(len(cv),cy.mean())}
  for kind in ['logistic','forest']:
   preds['pooled_'+kind]=pooled[kind][mask]
   preds['specialized_'+kind]=fit(pipeline(kind,extra=True),ct,cy).predict_proba(cv)[:,1]
  scores={}
  for name,p in preds.items():
   assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all();scores[name]=metrics(cyv,p)
  results.append({'window':f'{start}-{stop}','train_n':len(ct),'train_events':int(cy.sum()),'scores':scores})
  print('Window done',start,flush=True)
 passed=[kind for kind in ['logistic','forest'] if all(w['scores']['specialized_'+kind][m]<w['scores'][b][m] for w in results for m in ['brier','log_loss'] for b in ['category_constant','pooled_'+kind])]
 report={'selected_category':chosen,'selection_training_counts':counts.to_dict('records'),'windows':results,'audit':audits,'passed':passed,'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(OUT/'error_analysis_plan.md'),'stores':old['hashes']['stores'],'features':snapshot_sha256(ROOT/'scripts/fit_d03_expanded.py'),'spatial':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'metrics':snapshot_sha256(ROOT/'scripts/fit_d03.py')},'versions':{'python':platform.python_version(),'pandas':pd.__version__,'sklearn':sklearn.__version__}}
 (OUT/'error_analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# D-03 오차 분석과 업태 전용 모델','',f'첫 학습기간의 표본 수 기준으로 {chosen} 선택. 검증 성능을 보고 업태를 선택/교체하지 않았다. 기존 검증을 반복 활용한 탐색이며 2023~2024 재채점 없음.','','## 업태 전용 모델 비교','','| 기간 | 모델 | n | 실제% | 예측% | Brier | log loss | AUC |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
 for w in results:
  for name,m in w['scores'].items():lines.append(f"| {w['window']} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
 lines+=['','pooled=전체 업태 학습 후 선택 업태 평가, specialized=선택 업태만 학습. category_constant=선택 업태 학습 사건 비율. 모든 모델은 같은 업태 검증 표본에서 비교.','',f'세 기간 모두 업태 평균 및 같은 알고리즘 pooled보다 두 오차 개선: {passed or "없음"}.','','## 기존 주변 RF의 오차 진단','', '각 기간·분류에서 n>=200·사건>=20 그룹 중 상수 대비 Brier 증가가 가장 큰 3개를 제시한다. 양수는 상수보다 나쁨, 음수는 개선. 표본/사건 차이로 Brier 원값만 비교하면 안 된다. 작은 표본을 포함한 모든 그룹은 JSON에 보존.','','| 기간 | 구분 | 그룹 | n | 실제% | 예측% | 상수 대비 Brier 차이 |','| --- | --- | --- | ---: | ---: | ---: | ---: |']
 for window in [w['window'] for w in results]:
  for field in ['category','gu','open_year']:
   subset=sorted([g for g in audits if g['window']==window and g['field']==field and not g['small_sample']],key=lambda g:g['excess_brier'],reverse=True)[:3]
   for g in subset:lines.append(f"| {window} | {field} | {g['value']} | {g['n']} | {g['actual_pct']:.2f} | {g['predicted_pct']:.2f} | {g['excess_brier']:+.6f} |")
 lines+=['','## 검증과 한계','','기존 RF 점수 재현, 시간 간격/표본 분리, 하위집단 표본·사건·가중 Brier 합계, 수렴·확률 범위 통과. 인허가 상태/현재 주소의 과거 정확성·신고 지연 미검증. 업태별 오차는 원인 규명이 아니며 작은 차이의 통계적 유의성을 주장하지 않는다. 전용 모델의 입력/설정 변경이나 검증 결과에 따른 업태 교체를 수행하지 않았다.','','다음 독립 평가 기간은 이번에 선정하지 않았다. 원본 면적 등의 개업 당시 가용성도 별도 확인이 필요하다. 운영 서비스·DB·푸시 변경 없음. [계획](error_analysis_plan.md), [전체 결과](error_analysis.json). 재현: 기존 분석 환경에서 `python scripts/analyze_d03_errors.py`.']
 (OUT/'error_analysis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'selected':chosen,'passed':passed,'windows':results},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
