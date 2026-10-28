"""Paired building-cluster bootstrap for fixed retrospective area models."""
import json,platform
from pathlib import Path
import numpy as np
import pandas as pd
from fit_d03 import ROOT,metrics,snapshot_sha256,verify_snapshot_hash
from fit_d03_expanded import make_features,target,fit
from fit_d03_area_complete import model,parse_area

OUT=ROOT/'docs/d03'

def losses(y,p):
 p=np.clip(p,np.finfo(float).eps,1-np.finfo(float).eps)
 return np.column_stack([(p-y)**2,-(y*np.log(p)+(1-y)*np.log1p(-p))])

def bootstrap(delta,groups,repetitions=2000):
 codes,labels=pd.factorize(np.asarray(groups),sort=True)
 assert (codes>=0).all()
 n=len(labels);sizes=np.bincount(codes,minlength=n)
 sums=np.column_stack([np.bincount(codes,weights=delta[:,i],minlength=n) for i in range(delta.shape[1])])
 assert np.allclose(sums.sum(axis=0)/sizes.sum(),delta.mean(axis=0))
 rng=np.random.default_rng(42);chunks=[]
 for i in range(0,repetitions,50):
  pick=rng.integers(0,n,size=(min(50,repetitions-i),n))
  chunks.append(sums[pick].sum(axis=1)/sizes[pick].sum(axis=1)[:,None])
 draws=np.concatenate(chunks);q=np.quantile(draws,[.025,.975],axis=0)
 return {'building_blocks':n,'repetitions':repetitions,'seed':42,'metrics':{name:{'difference':float(delta[:,i].mean()),'lower95':float(q[0,i]),'upper95':float(q[1,i])} for i,name in enumerate(['brier','log_loss'])}}

def main():
 zero=bootstrap(np.zeros((4,2)),['a','a','b','c'],100)
 assert all(m['lower95']==m['upper95']==0 for m in zero['metrics'].values())
 example=np.array([[.1,.2],[.3,.4],[-.1,-.2],[0,0]])
 assert bootstrap(example,['a','a','b','c'],100)==bootstrap(example,['a','a','b','c'],100)
 prior=json.loads((OUT/'area_complete.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';verify_snapshot_hash(sp,prior['hashes']['stores'])
 for k,p in [('script',ROOT/'scripts/fit_d03_area_complete.py'),('parser',ROOT/'service/pipeline/numeric.py')]:verify_snapshot_hash(p,prior['hashes'][k])
 f=make_features(pd.read_parquet(sp)).reset_index(drop=True)
 rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv';verify_snapshot_hash(rp,prior['hashes']['raw'])
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적'])
 r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 keys=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 raw=keys.map(r.set_index('key')['소재지면적']);parsed=parse_area(raw)
 recover=f.area_m2.isna()&raw.str.contains(',',regex=False,na=False)&parsed.notna()
 area=f.area_m2.copy();area.loc[recover]=parsed[recover].astype(float)
 valid=np.isfinite(area)&area.gt(0);f['log_area']=np.log1p(area.where(valid));f=f[valid].copy()
 assert len(f)==prior['n'] and f.log_area.notna().all()
 windows=[]
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)].copy()
  assert not set(tr.index)&set(va.index);assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min()
  y,yv=target(tr),target(va);pred={'constant':np.full(len(va),y.mean())}
  for extra in [False,True]:
   name='forest_area' if extra else 'forest_context';m=fit(model('forest',extra),tr,y);pred[name]=m.predict_proba(va)[:,1]
   nums=m.named_steps['features'].transformers_[1][2]
   assert 'area_missing' not in nums and ('log_area' in nums)==extra
  scores={name:metrics(yv,p) for name,p in pred.items()}
  ref=next(w for w in prior['windows'] if w['window']==f'{start}-{stop}')
  for name in pred:
   for k in ['n','events','brier','log_loss','roc_auc','predicted_pct']:assert np.isclose(scores[name][k],ref['scores'][name][k],atol=1e-10,rtol=1e-8),(name,k)
  known=tr.building_key.dropna().astype(str);known=known[known.str.strip().ne('')]
  key=va.building_key.astype('string');available=key.notna()&key.fillna('').str.strip().ne('')
  seen=available&key.isin(known);unseen=available&~key.isin(known)
  groups=key.copy();groups.loc[available]='building:'+groups.loc[available]
  for idx in va.index[~available]:groups.loc[idx]='missing:'+str(idx)
  ci={}
  for baseline in ['constant','forest_context']:
   delta=losses(yv,pred['forest_area'])-losses(yv,pred[baseline]);ci[baseline]=bootstrap(delta,groups.to_numpy())
   for j,k in enumerate(['brier','log_loss']):assert np.isclose(delta[:,j].mean(),scores['forest_area'][k]-scores[baseline][k])
  sub={}
  for label,mask in [('seen_building',seen),('new_building',unseen),('missing_key',~available)]:
   ix=mask.to_numpy(dtype=bool)
   if ix.any():sub[label]={name:metrics(yv[ix],p[ix]) for name,p in pred.items()}
  for name in pred:
   assert sum(g[name]['n'] for g in sub.values())==len(va)
   assert np.isclose(sum(g[name]['n']*g[name]['brier'] for g in sub.values())/len(va),scores[name]['brier'])
  windows.append({'window':f'{start}-{stop}','train_n':len(tr),'scores':scores,'missing_building_keys':int((~available).sum()),'bootstrap':ci,'subgroups':sub});print('Complete',start,flush=True)
 report={'scope':'post-selection retrospective diagnostic, fixed-model paired cluster bootstrap; not independent validation','windows':windows,'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(OUT/'area_stability_plan.md'),'reference_results':snapshot_sha256(OUT/'area_complete.json'),'model_helper':snapshot_sha256(ROOT/'scripts/fit_d03_area_complete.py'),'feature_helper':snapshot_sha256(ROOT/'scripts/fit_d03_expanded.py'),'spatial_helper':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'metrics_helper':snapshot_sha256(ROOT/'scripts/fit_d03.py'),'parser':snapshot_sha256(ROOT/'service/pipeline/numeric.py')},'versions':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__}}
 (OUT/'area_stability.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 면적 RF 개선 안정성 진단','','기존 양수 면적 모델의 동일 세 검증기간을 재현했다. 학습에 쓰지 않은 건물 점검과 건물 단위 재표집으로 고정 모델 평가의 불확실성을 살폈다. 이미 본 결과에 대한 사후 진단이며 독립 시험이 아니다.','','## 건물 단위 paired bootstrap','','차이=면적RF-기준선. 음수면 면적RF의 오차가 작다.95% percentile 구간은 건물 묶음2000회 재표집(seed42).','','| 기간 | 비교기준 | 건물블록 | Brier 차이 | 95% 구간 | log loss 차이 | 95% 구간 |','| --- | --- | ---: | ---: | --- | ---: | --- |']
 for w in windows:
  for name,b in w['bootstrap'].items():
   x,z=b['metrics']['brier'],b['metrics']['log_loss']
   lines.append(f"| {w['window']} | {name} | {b['building_blocks']} | {x['difference']:+.6f} | [{x['lower95']:+.6f}, {x['upper95']:+.6f}] | {z['difference']:+.6f} | [{z['lower95']:+.6f}, {z['upper95']:+.6f}] |")
 lines+=['','## 학습 건물 중복별 비교','','new_building은 학습에 없는 건물키, seen_building은 학습에 등장한 건물키다. 새 건물만으로 재학습한 모델이 아니다.','','| 기간 | 그룹 | 모델 | n | 실제% | 예측% | Brier | AUC |','| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
 for w in windows:
  for group,models in w['subgroups'].items():
   for name,m in models.items():lines.append(f"| {w['window']} | {group} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['roc_auc'] if m['roc_auc'] is not None else 'NA'} |")
 lines+=['','## 검증과 해석 제한','','이전 RF/상수 지표 재현, 면적누락 입력 제외, 동일 표본과365일 관측 간격, 하위집단 합계, 건물 합계/점차이 일치, 재표집 결정성/동일예측 차이0 검사 통과. 건물키 없는 행은 개별 블록으로 처리하며 수는 JSON에 기록.','','이 구간은 모델을 다시 학습하는 불확실성이나 모델 선택 과정을 반영하지 않는다. 인접한 다른 건물 간 상관도 남는다. 따라서 구간이0을 제외하더라도 새 자료의 일반화나 통계적 확증으로 과장하지 않는다. 원천의 개업당시 면적과 양수표본 선택 편향·축제영업 혼입은 여전히 미확인이다. 최종2023~2024 재평가,원본/운영/DB 변경 없음.','','[사전 진단 계획](area_stability_plan.md), [전체 결과](area_stability.json). 재현: `python scripts/audit_d03_area_stability.py`.']
 (OUT/'area_stability.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(windows,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
