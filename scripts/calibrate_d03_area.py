"""Past-only sigmoid calibration, reusing seen 2025 for exploration."""
import json,platform
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from sklearn.linear_model import LogisticRegression
from fit_d03_expanded import logit
from fit_d03 import ROOT,metrics,snapshot_sha256,verify_snapshot_hash
from fit_d03_expanded import target,fit,CATS,NUMS
from fit_d03_historical_context import counts,check_boundaries,RADIUS
from fit_d03_area_complete import model,parse_area
from audit_d03_area_stability import bootstrap,losses
OUT=ROOT/'docs/d03'

def main():
 check_boundaries();prior=json.loads((OUT/'area_complete.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';verify_snapshot_hash(sp,prior['hashes']['stores'])
 rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv';verify_snapshot_hash(rp,prior['hashes']['raw'])
 for k,p in [('script',ROOT/'scripts/fit_d03_area_complete.py'),('parser',ROOT/'service/pipeline/numeric.py')]:verify_snapshot_hash(p,prior['hashes'][k])
 meta=json.loads((ROOT/'service/data/processed/meta.json').read_text(encoding='utf-8'));ref=pd.Timestamp(meta['reference_date'])
 assert ref>=pd.Timestamp('2025-09-30')+pd.Timedelta(days=365)
 stores=pd.read_parquet(sp);source=stores[stores.service.eq('일반음식점')&stores.ld.lt('2025-10-01')].copy()
 coord=source.lat.between(-90,90)&source.lon.between(-180,180)
 test_period=source.ld.between('2025-01-01','2025-09-30');test_initial=int(test_period.sum());coord_excluded=int((test_period&~coord).sum())
 source=source[coord].reset_index(drop=True);coords=np.radians(source[['lat','lon']].to_numpy());tree=BallTree(coords,metric='haversine')
 opened=source.ld.to_numpy(dtype='datetime64[D]');closed=source.cd.to_numpy(dtype='datetime64[D]')
 ids=np.flatnonzero((source.ld.dt.year.between(2010,2023)|source.ld.between('2025-01-01','2025-09-30')).to_numpy())
 f=source.iloc[ids].copy().reset_index(drop=True);values=[]
 for n,idx in enumerate(ids):
  cutoff=opened[idx]-np.timedelta64(60,'D');near=tree.query_radius(coords[idx:idx+1],r=RADIUS)[0]
  assert idx not in near[opened[near]<cutoff]
  values.append(counts(opened[near],closed[near],cutoff))
  if n in [0,len(ids)//2,len(ids)-1]:
   delta=coords-coords[idx];a=np.sin(delta[:,0]/2)**2+np.cos(coords[:,0])*np.cos(coords[idx,0])*np.sin(delta[:,1]/2)**2
   direct=2*np.arcsin(np.sqrt(np.clip(a,0,1)))<=RADIUS
   assert values[-1]==counts(opened[direct],closed[direct],cutoff)
 f[NUMS]=np.log1p(np.array(values));f['open_month']=f.ld.dt.month.astype(str)
 for c in CATS:f[c]=f[c].astype('string').fillna('__MISSING__').astype(str)
 raw=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적']);raw['key']=raw['개방자치단체코드']+'|'+raw['관리번호'];assert raw.key.is_unique
 key=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 text=key.map(raw.set_index('key')['소재지면적']);parsed=parse_area(text)
 recover=f.area_m2.isna()&text.str.contains(',',regex=False,na=False)&parsed.notna();area=f.area_m2.copy();area.loc[recover]=parsed[recover].astype(float)
 valid=np.isfinite(area)&area.gt(0);test_area_excluded=int((f.ld.dt.year.eq(2025)&~valid).sum())
 f['log_area']=np.log1p(area.where(valid));f=f[valid].copy()
 tr=f[f.ld.dt.year.between(2010,2023)];va=f[f.ld.dt.year.eq(2025)].copy()
 assert len(va)>0 and (va.ld+pd.Timedelta(days=365)).le(ref).all()
 assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min();assert not set(tr.index)&set(va.index)
 assert not tr.ld.dt.year.eq(2024).any()
 early=tr[tr.ld.dt.year.le(2021)];cal=tr[tr.ld.dt.year.eq(2023)]
 assert not set(early.index)&set(cal.index) and not set(cal.index)&set(va.index)
 assert (early.ld+pd.Timedelta(days=365)).max()<cal.ld.min()
 assert (cal.ld+pd.Timedelta(days=365)).max()<va.ld.min()
 ye,yc,yv=target(early),target(cal),target(va)
 print('Prepared RF/calibration/evaluation',len(early),len(cal),len(va),flush=True)
 full=fit(model('forest',True),tr,target(tr));base=fit(model('forest',True),early,ye)
 pc=base.predict_proba(cal)[:,1];pv=base.predict_proba(va)[:,1]
 calibrator=fit(LogisticRegression(C=1e6,max_iter=2000,random_state=0),logit(pc),yc)
 pred={'full_training_constant':np.full(len(va),target(tr).mean()),'full_training_rf':full.predict_proba(va)[:,1],'calibration_base_rf':pv,'sigmoid_rf':calibrator.predict_proba(logit(pv))[:,1]}
 scores={name:metrics(yv,p) for name,p in pred.items()}
 old=json.loads((OUT/'area_2025.json').read_text(encoding='utf-8'))
 for name,previous in [('full_training_constant','constant'),('full_training_rf','forest_area')]:
  for metric in ['n','events','brier','log_loss','roc_auc','predicted_pct']:assert np.isclose(scores[name][metric],old['scores'][previous][metric],atol=1e-10,rtol=1e-8)
 for p in pred.values():assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
 # Positive sigmoid slope preserves ranking; calibrating should not be sold as improved discrimination.
 slope=float(calibrator.coef_[0,0]);intercept=float(calibrator.intercept_[0])
 if slope>0:assert np.isclose(scores['calibration_base_rf']['roc_auc'],scores['sigmoid_rf']['roc_auc'])
 key=va.building_key.astype('string');available=key.notna()&key.fillna('').str.strip().ne('');groups=key.copy();groups.loc[available]='building:'+groups.loc[available]
 for idx in va.index[~available]:groups.loc[idx]='missing:'+str(idx)
 ci=bootstrap(losses(yv,pred['sigmoid_rf'])-losses(yv,pv),groups.to_numpy())
 bins=[]
 for name in ['calibration_base_rf','sigmoid_rf']:
  for lo,hi in [(0,.05),(.05,.1),(.1,.2),(.2,1.0000001)]:
   mask=(pred[name]>=lo)&(pred[name]<hi)
   if mask.any():bins.append({'model':name,'lower':lo,'upper':min(hi,1),'n':int(mask.sum()),'events':int(yv[mask].sum()),'predicted_pct':float(pred[name][mask].mean()*100),'actual_pct':float(yv[mask].mean()*100)})
  assert sum(b['n'] for b in bins if b['model']==name)==len(va)
 high=pv>=.2
 high_same={name:metrics(yv[high],pred[name][high]) for name in ['calibration_base_rf','sigmoid_rf']} if high.any() else {}
 improves=all(scores['sigmoid_rf'][m]<scores['calibration_base_rf'][m] for m in ['brier','log_loss'])
 result={'scope':'post-2025-observation exploratory calibration; coefficients fit on2023 only','base_train_n':len(early),'calibration_n':len(cal),'calibration_events':int(yc.sum()),'calibration_actual_pct':float(yc.mean()*100),'calibration_before':metrics(yc,pc),'calibration_after_in_sample':metrics(yc,calibrator.predict_proba(logit(pc))[:,1]),'evaluation_n':len(va),'sigmoid_slope':slope,'sigmoid_intercept':intercept,'scores':scores,'bootstrap_vs_same_base':ci,'bins':bins,'same_base_high_group':high_same,'improves_vs_same_base_both_errors':improves,'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(OUT/'area_calibration_plan.md'),'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'previous_results':snapshot_sha256(OUT/'area_2025.json'),'model_helper':snapshot_sha256(ROOT/'scripts/fit_d03_area_complete.py'),'spatial_helper':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'logit_helper':snapshot_sha256(ROOT/'scripts/fit_d03_expanded.py'),'bootstrap_helper':snapshot_sha256(ROOT/'scripts/audit_d03_area_stability.py'),'parser':snapshot_sha256(ROOT/'service/pipeline/numeric.py')},'python':platform.python_version()}
 (OUT/'area_calibration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 過去年 확률 보정 탐색'.replace('過去年','과거연도'),'','2025결과를 본 뒤 정한 후속 탐색이다. 보정계수는2023자료만으로 학습했지만2025를 다시 독립시험이라고 부를 수 없다.', '',f'기초RF 학습2010~2021 {len(early):,}건,보정2023 {len(cal):,}건,비교2025년1~9월{len(va):,}건. 각 단계365일 관측간격 확인.2022/2024는 목표학습 제외.','','| 모델 | n | 실제% | 예측% | Brier | log loss | AUC |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
 for name,m in scores.items():lines.append(f"| {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
 lines+=['','full_training_rf는2010~2023전체학습,calibration_base_rf는2010~2021학습이다. 보정효과는 후자와sigmoid_rf를 비교한다.',f'보정전 같은 기초RF보다 두오차 개선: {improves}.2023 sigmoid slope={slope:.6f},intercept={intercept:.6f}.','','## 고정 확률구간 점검','','| 모델 | 구간% | n | 평균예측% | 실제% |','| --- | --- | ---: | ---: | ---: |']
 for b in bins:lines.append(f"| {b['model']} | {100*b['lower']:g}~{100*b['upper']:g} | {b['n']} | {b['predicted_pct']:.2f} | {b['actual_pct']:.2f} |")
 lines+=['','보정으로 구간 소속이 바뀐다. 동일한 고위험 표본 비교는 기초RF20%이상 그룹을 고정해 JSON에 별도 기록했다.2023보정자료 내 적합지표는 학습내 수치이며 일반화성능이 아니다.','','## 검증·한계','','기존전체학습RF/상수지표 재현,학습/보정/평가표본 분리,365일 관측간격,수렴/확률범위,양의보정기울기의AUC불변,구간합계 검사. 고정모델 건물2000회재표집은 학습재추정/모델선택 불확실성을 포함하지 않는다. 현재면적/주소가 당시와 같다는 가정·양수표본 선택·한시영업혼입 미확인은 그대로다. 결과에 따라 계수/기간/방법을 재선택하지 않았다. 운영/DB/배포/원본 변경 없음.','','[계획](area_calibration_plan.md),[전체결과](area_calibration.json). 재현:`python scripts/calibrate_d03_area.py`.']
 (OUT/'area_calibration.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'scores':scores,'slope':slope,'intercept':intercept,'improves':improves,'ci':ci,'same_high':high_same},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
