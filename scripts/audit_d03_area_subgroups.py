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
 saved=json.loads((OUT/'area_calibration.json').read_text(encoding='utf-8'))
 paths={'script':ROOT/'scripts/calibrate_d03_area.py','stores':ROOT/'service/data/processed/stores.parquet','raw':ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv','model_helper':ROOT/'scripts/fit_d03_area_complete.py','spatial_helper':ROOT/'scripts/fit_d03_historical_context.py','logit_helper':ROOT/'scripts/fit_d03_expanded.py','parser':ROOT/'service/pipeline/numeric.py'}
 for k,p in paths.items():verify_snapshot_hash(p,saved['hashes'][k])
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
 for name,m in scores.items():
  for k in ['n','events','predicted_pct','actual_pct','brier','log_loss','roc_auc']:
   assert np.isclose(m[k],saved['scores'][name][k],atol=1e-10,rtol=1e-8),(name,k)
 assert np.isclose(calibrator.coef_[0,0],saved['sigmoid_slope'])
 assert np.isclose(calibrator.intercept_[0],saved['sigmoid_intercept'])
 labels=['0~30','30~60','60~100','100~200','200 이상']
 edges=[0,30,60,100,200,np.inf]
 assert list(pd.cut([29.99,30,60,100,200],edges,labels=labels,right=False).astype(str))==labels
 fields={'업태':va.category.astype(str),'구군':va.gu.astype(str),'면적㎡':pd.cut(np.expm1(va.log_area).round(6),edges,labels=labels,right=False).astype(str)}
 rows=[]
 for field,values in fields.items():
  for group in sorted(values.unique()):
   mask=values.eq(group).to_numpy();yy=yv[mask];pp=pred['sigmoid_rf'][mask]
   before=metrics(yy,pred['calibration_base_rf'][mask]);after=metrics(yy,pp)
   keys=va.loc[mask,'building_key'].astype('string');groups=keys.fillna('').astype(str).to_numpy()
   groups=np.array([g if g.strip() else 'missing:'+str(i) for i,g in zip(va.index[mask],groups)],dtype=object)
   codes,uniq=pd.factorize(groups,sort=True);sizes=np.bincount(codes);sums=np.bincount(codes,weights=pp-yy)
   rng=np.random.default_rng(42);draws=[]
   for i in range(40):
    picks=rng.integers(0,len(uniq),(50,len(uniq)));draws.extend(sums[picks].sum(axis=1)/sizes[picks].sum(axis=1)*100)
   ci=np.quantile(draws,[.025,.975])
   rows.append({'field':field,'group':group,'before':before,'after':after,'gap_pp':after['predicted_pct']-after['actual_pct'],'gap_lower95_pp':float(ci[0]),'gap_upper95_pp':float(ci[1]),'building_blocks':len(uniq),'small_sample':len(yy)<100 or int(yy.sum())<10 or int((1-yy).sum())<10})
  subset=[r for r in rows if r['field']==field]
  assert sum(r['after']['n'] for r in subset)==len(va)
  assert sum(r['after']['events'] for r in subset)==int(yv.sum())
  for stage,name in [('before','calibration_base_rf'),('after','sigmoid_rf')]:
   for metric in ['brier','log_loss','predicted_pct','actual_pct']:
    assert np.isclose(sum(r[stage][metric]*r[stage]['n'] for r in subset)/len(va),scores[name][metric])
 for k,p in paths.items():verify_snapshot_hash(p,saved['hashes'][k])
 result={'scope':'post-hoc subgroup diagnostics; no tuning or deployment eligibility selection','scores':scores,'subgroups':rows,'hashes':{k:snapshot_sha256(p) for k,p in paths.items()},'diagnostic_script_sha256':snapshot_sha256(Path(__file__)),'plan_sha256':snapshot_sha256(OUT/'area_subgroups_plan.md'),'calibration_results_sha256':snapshot_sha256(OUT/'area_calibration.json'),'bootstrap_repetitions':2000,'seed':42}
 (OUT/'area_subgroups.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 面積 보정 모델 하위집단 진단'.replace('面積','면적'),'','2026-10-29. 기존 2025년1~9월 1,608건·신고168건을 다시 살펴본 사후 진단이다. 모델/보정/대상 변경 없이 기존 전체 지표를 재현했다. 개업 당시 면적은 미확인이다.','', '차이는 평균예측-실제(%p): 음수는 과소예측, 양수는 과대예측이다. 소표본은 n<100 또는 신고/비신고 각각10건 미만. 신뢰구간은 건물 단위 고정모델 재표집으로 다중 비교를 보정하지 않았다.']
 for field in fields:
  lines+=['','## '+field,'','| 집단 | n | 신고 | 보정전% | 보정후% | 실제% | 차이%p [95%구간] | Brier 전→후 | 소표본 |','| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |']
  for r in rows:
   if r['field']!=field:continue
   a=r['after'];b=r['before']
   lines.append(f"| {r['group']} | {a['n']} | {a['events']} | {b['predicted_pct']:.2f} | {a['predicted_pct']:.2f} | {a['actual_pct']:.2f} | {r['gap_pp']:+.2f} [{r['gap_lower95_pp']:+.2f}, {r['gap_upper95_pp']:+.2f}] | {b['brier']:.5f} → {a['brier']:.5f} | {r['small_sample']} |")
 lines+=['','## 해석 범위','','평균이 가깝거나 구간에 0이 들어가는 집단을 서비스 사용 가능 집단으로 선정하지 않는다. 개별 정확성·새 시기 성능의 증명이 아니며, 같은 가게가 업태·구군·면적 표에 반복된다. 제외됐던 면적 누락/좌표 누락 가게에는 일반화하지 않는다. 표본/사건 합계·가중 지표·기존 점수·입력 해시·구간 경계 검증 통과. 기존 결과 파일은 수정하지 않았다.','','재현: `python scripts/audit_d03_area_subgroups.py`. [계획](area_subgroups_plan.md), [전체 지표](area_subgroups.json).']
 (OUT/'area_subgroups.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps(rows,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
