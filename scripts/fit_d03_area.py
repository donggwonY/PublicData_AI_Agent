"""Exploratory area feature under an unverified historical constancy assumption."""
import sys,json,platform
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler,OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from fit_d03 import ROOT,metrics,snapshot_sha256,verify_snapshot_hash
from fit_d03_expanded import make_features,target,fit,CATS,NUMS
sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area

def model(kind,area):
 nums=NUMS+(['area_missing'] if area=='missing' else (['log_area','area_missing'] if area else []))
 tf=ColumnTransformer([('cats',OneHotEncoder(handle_unknown='ignore',sparse_output=False),CATS),('nums',Pipeline([('fill',SimpleImputer(strategy='median',keep_empty_features=True)),('scale',StandardScaler())]),nums)])
 est=RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=2) if kind=='forest' else LogisticRegression(C=1,max_iter=2000,random_state=0)
 return Pipeline([('features',tf),('model',est)])

def main():
 out=ROOT/'docs/d03';old=json.loads((out/'expanded_experiments.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';verify_snapshot_hash(sp,old['hashes']['stores'])
 f=make_features(pd.read_parquet(sp)).reset_index(drop=True)
 rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적'])
 r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 keys=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 raw=keys.map(r.set_index('key')['소재지면적']);parsed=parse_area(raw)
 recover=f.area_m2.isna()&raw.str.contains(',',regex=False,na=False)&parsed.notna()
 area=f.area_m2.copy();area.loc[recover]=parsed[recover].astype(float)
 assert np.allclose(area[~recover],f.area_m2[~recover],equal_nan=True)
 valid=np.isfinite(area)&area.gt(0);f['area_missing']=(~valid).astype(int);f['log_area']=np.log1p(area.where(valid))
 windows=[];subs=[]
 print('Features',len(f),'recovered',int(recover.sum()),flush=True)
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)]
  assert not set(tr.index)&set(va.index);assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min()
  y,yv=target(tr),target(va);pred={'constant':np.full(len(va),y.mean())}
  for kind in ['logistic','forest']:
   for extra in [False,True,'missing']:
    name=kind+('_missing' if extra=='missing' else ('_area' if extra else '_context'));m=fit(model(kind,extra),tr,y)
    if extra is True:assert np.isclose(m.named_steps['features'].named_transformers_['nums'].named_steps['fill'].statistics_[-2],tr.log_area.median())
    pred[name]=m.predict_proba(va)[:,1]
  scores={}
  for name,p in pred.items():
   assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all();scores[name]=metrics(yv,p)
   for field in ['category','gu','area_missing']:
    for val in sorted(va[field].unique()):
     ix=va[field].eq(val).to_numpy();subs.append({'window':f'{start}-{stop}','model':name,'field':field,'value':str(val),**metrics(yv[ix],p[ix])})
  ref=next(w for w in old['windows'] if w['window']==f'{start}-{stop}')
  for name,prev in [('constant','constant'),('logistic_context','context'),('forest_context','forest_context')]:
   for k in ['n','events','brier','log_loss']:assert np.isclose(scores[name][k],ref['scores'][prev][k],atol=1e-5,rtol=1e-4)
  windows.append({'window':f'{start}-{stop}','train_n':len(tr),'validation_missing_area':int(va.area_missing.sum()),'scores':scores});print('Window done',start,flush=True)
 passed=[kind for kind in ['logistic','forest'] if all(w['scores'][kind+'_area'][metric]<w['scores'][b][metric] for w in windows for metric in ['brier','log_loss'] for b in ['constant',kind+'_context'])]
 report={'assumption':'current area equals opening-time area; unverified, not prospective evidence','n':len(f),'comma_recovered':int(recover.sum()),'missing_or_nonpositive_area':int((~valid).sum()),'windows':windows,'subgroups':subs,'passed_exploratory_criterion':passed,'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'area_experiment_plan.md'),'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'parser':snapshot_sha256(ROOT/'service/pipeline/numeric.py'),'feature_helper':snapshot_sha256(ROOT/'scripts/fit_d03_expanded.py'),'spatial_helper':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'metrics':snapshot_sha256(ROOT/'scripts/fit_d03.py')},'python':platform.python_version()}
 (out/'area_experiment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 면적 추가 가정 기반 탐색','','**현재 면적이 개업 당시와 같다는 미검증 가정이다. 개선 여부와 무관하게 실제 서비스 예측 성능 입증으로 해석할 수 없다.** 기존 최종시험 재평가 없음.','',f'동일표본 {len(f):,}건, 쉼표 복구 {int(recover.sum())}건, 결측/0이하 면적 {int((~valid).sum())}건. 기존16건 불일치 값 덮어쓰기 없음.','','| 기간 | 모델 | n | 실제% | 예측% | Brier | log loss | AUC |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
 for w in windows:
  for name,m in w['scores'].items():lines.append(f"| {w['window']} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
 lines+=['',f'세 기간 모두 상수/동일알고리즘 기존모델보다 Brier/log loss 감소: {passed or "없음"}.','','추가한 _missing 후보는 면적 누락 여부만 입력한 결과다. 최초 결과 확인 후 추가한 해석용 비교이며 원래 사전5후보와 구분한다.','', '## 검증/한계','','같은 표본, 학습365일 관측 간격, 기존지표 재현, 학습표본 중앙값 대체, 복구 이외 원본 면적 불변, 수렴·확률범위 검사 통과. 반복 활용 검증기간 탐색이며 수정된 면적이 폐업 후 정보일 가능성을 배제할 수 없다. 단기행사 혼입도 유지한 비교다. 결과에 따라 추가 파라미터 탐색하지 않았다. 원본/운영가공본/DB/서비스 변경 없음.','','[사전 계획](area_experiment_plan.md), [전체 결과](area_experiment.json). 재현: 기존 분석 환경에서 `python scripts/fit_d03_area.py`.']
 (out/'area_experiment.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'passed':passed,'windows':windows},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
