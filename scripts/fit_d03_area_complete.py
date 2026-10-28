"""Complete-case area exploration; no missingness feature."""
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
 nums=NUMS+(['log_area'] if area else [])
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
 excluded=f[~valid].copy();f=f[valid].copy();assert f.log_area.notna().all()
 windows=[];subs=[]
 print('Features',len(f),'recovered',int(recover.sum()),flush=True)
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)]
  assert not set(tr.index)&set(va.index);assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min()
  y,yv=target(tr),target(va);pred={'constant':np.full(len(va),y.mean())}
  for kind in ['logistic','forest']:
   for extra in [False,True]:
    name=kind+('_missing' if extra=='missing' else ('_area' if extra else '_context'));m=fit(model(kind,extra),tr,y)
    if extra is True:assert np.isclose(m.named_steps['features'].named_transformers_['nums'].named_steps['fill'].statistics_[-1],tr.log_area.median())
    pred[name]=m.predict_proba(va)[:,1]
  scores={}
  for name,p in pred.items():
   assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all();scores[name]=metrics(yv,p)
   for field in ['category','gu']:
    for val in sorted(va[field].unique()):
     ix=va[field].eq(val).to_numpy();subs.append({'window':f'{start}-{stop}','model':name,'field':field,'value':str(val),**metrics(yv[ix],p[ix])})
  prior=json.loads((out/'area_experiment.json').read_text(encoding='utf-8'))
  ref=next(g for g in prior['subgroups'] if g['window']==f'{start}-{stop}' and g['model']=='constant' and g['field']=='area_missing' and g['value']=='0')
  assert len(va)==ref['n'] and int(yv.sum())==ref['events']
  windows.append({'window':f'{start}-{stop}','train_n':len(tr),'validation_excluded_n':int(excluded.ld.dt.year.between(start,stop).sum()),'validation_excluded_events':int(target(excluded[excluded.ld.dt.year.between(start,stop)]).sum()),'scores':scores});print('Window done',start,flush=True)
 passed=[kind for kind in ['logistic','forest'] if all(w['scores'][kind+'_area'][metric]<w['scores'][b][metric] for w in windows for metric in ['brier','log_loss'] for b in ['constant',kind+'_context'])]
 report={'assumption':'current area equals opening-time area; unverified, not prospective evidence','n':len(f),'excluded_n':len(excluded),'comma_recovered':int(recover.sum()),'missing_or_nonpositive_area':int((~valid).sum()),'windows':windows,'subgroups':subs,'passed_exploratory_criterion':passed,'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'area_complete_plan.md'),'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'parser':snapshot_sha256(ROOT/'service/pipeline/numeric.py'),'feature_helper':snapshot_sha256(ROOT/'scripts/fit_d03_expanded.py'),'spatial_helper':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'metrics':snapshot_sha256(ROOT/'scripts/fit_d03.py')},'python':platform.python_version()}
 (out/'area_complete.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 양수 면적 표본 추가 비교','','**현재 면적이 개업 당시와 같다는 미검증 가정이다. 개선 여부와 무관하게 실제 서비스 예측 성능 입증으로 해석할 수 없다.** 기존 최종시험 재평가 없음.','',f'양수 면적 동일표본 {len(f):,}건. 원래 표본 중 결측/0이하 {len(excluded):,}건 제외. 면적 누락 지표 입력 없음. 기존16건 값 덮어쓰기 없음.','','| 기간 | 모델 | n | 실제% | 예측% | Brier | log loss | AUC |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
 for w in windows:
  for name,m in w['scores'].items():lines.append(f"| {w['window']} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
 lines+=['',f'세 기간 모두 상수/동일알고리즘 기존모델보다 Brier/log loss 감소: {passed or "없음"}.','','이번에는 학습/검증 모두 양수 면적 표본으로 제한해 5후보를 다시 학습했다. 이전 전체표본 오차와 직접 비교할 수 없다.','', '## 검증/한계','','같은 표본, 학습365일 관측 간격, 이전 면적 유효 하위집단의 표본/사건 수 일치, 학습표본 중앙값 대체, 복구 이외 원본 면적 불변, 수렴·확률범위 검사 통과. 반복 활용 검증기간 탐색이며 수정된 면적이 폐업 후 정보일 가능성을 배제할 수 없다. 단기행사 혼입도 유지한 비교다. 결과에 따라 추가 파라미터 탐색하지 않았다. 원본/운영가공본/DB/서비스 변경 없음.','','[사전 계획](area_complete_plan.md), [전체 결과](area_complete.json). 재현: 기존 분석 환경에서 `python scripts/fit_d03_area_complete.py`.']
 (out/'area_complete.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'passed':passed,'windows':windows},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
