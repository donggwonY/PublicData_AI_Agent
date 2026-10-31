"""Frozen exploratory group calibration on historical windows only."""
import json,platform
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from fit_d03_historical_context import counts,check_boundaries
from sklearn.preprocessing import OneHotEncoder
from fit_d03 import ROOT,metrics,snapshot_sha256,verify_snapshot_hash
from fit_d03_expanded import make_features,target,fit,logit
from fit_d03_area_complete import model,parse_area

def main():
 out=ROOT/'docs/d03';prior=json.loads((out/'area_complete.json').read_text(encoding='utf-8'))
 paths={'stores':ROOT/'service/data/processed/stores.parquet','raw':ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv','script':ROOT/'scripts/fit_d03_area_complete.py','parser':ROOT/'service/pipeline/numeric.py','feature_helper':ROOT/'scripts/fit_d03_expanded.py','spatial_helper':ROOT/'scripts/fit_d03_historical_context.py','metrics':ROOT/'scripts/fit_d03.py'}
 for k,p in paths.items():verify_snapshot_hash(p,prior['hashes'][k])
 sp=paths['stores']
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

 assert len(f)==prior['n']
 check_boundaries()
 source=pd.read_parquet(sp)
 source=source[source.service.eq('일반음식점') & source.ld.lt('2022-01-01') & source.lat.between(-90,90) & source.lon.between(-180,180)].copy()
 source['bk']=source.building_key.astype('string').fillna('').str.strip()
 histories={key:(g.ld.to_numpy(dtype='datetime64[D]'),g.cd.to_numpy(dtype='datetime64[D]')) for key,g in source[source.bk.ne('')].groupby('bk')}
 vals=[];missing=[]
 for i,(_,row) in enumerate(f.iterrows()):
  key='' if pd.isna(row.building_key) else str(row.building_key).strip()
  cutoff=np.datetime64(row.ld.date(),'D')-np.timedelta64(60,'D')
  v=counts(*histories[key],cutoff) if key in histories else [0,0,0]
  vals.append(v);missing.append(int(not key))
  if i in [0,len(f)//2,len(f)-1] and key:
   g=source[source.bk.eq(key)];before=g.ld.lt(pd.Timestamp(cutoff));closed=g.cd.notna()&g.cd.lt(pd.Timestamp(cutoff));lower=pd.Timestamp(cutoff)-pd.Timedelta(days=365)
   assert v==[int((before&~closed).sum()),int((before&g.ld.ge(lower)).sum()),int((before&closed&g.cd.ge(lower)).sum())]
 f[['building_active','building_openings','building_closures']]=np.log1p(np.array(vals));f['building_key_missing']=missing
 print('Building history ready',len(f),'missing',sum(missing),flush=True)
 windows=[];subs=[]
 for end,calyear,start,stop in [(2011,2013,2015,2016),(2013,2015,2017,2018),(2016,2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];cal=f[f.ld.dt.year.eq(calyear)];va=f[f.ld.dt.year.between(start,stop)]
  assert (tr.ld+pd.Timedelta(days=365)).max()<cal.ld.min()
  assert (cal.ld+pd.Timedelta(days=365)).max()<va.ld.min()
  assert not set(tr.index)&set(cal.index) and not set(cal.index)&set(va.index)
  y,yc,yv=target(tr),target(cal),target(va)
  old=next(w for w in prior['windows'] if w['window']==f'{start}-{stop}')
  assert len(va)==old['scores']['constant']['n'] and int(yv.sum())==old['scores']['constant']['events']
  base=fit(model('forest',True),tr,y);pc=base.predict_proba(cal)[:,1];pv=base.predict_proba(va)[:,1]
  predictions={'uncalibrated':pv};coefficients={}
  for name,c in [('global',1e6),('global_regularized',1)]:
   m=fit(LogisticRegression(C=c,max_iter=2000,random_state=0),logit(pc),yc)
   predictions[name]=m.predict_proba(logit(pv))[:,1]
  predictions['constant']=np.full(len(va),y.mean())
  candidate=model('forest',True)
  features=candidate.named_steps['features']
  features.transformers=[(name,trans,cols+['building_active','building_openings','building_closures','building_key_missing'] if name=='nums' else cols) for name,trans,cols in features.transformers]
  candidate=fit(candidate,tr,y)
  cp=candidate.predict_proba(cal)[:,1];vp=candidate.predict_proba(va)[:,1]
  predictions['building_rf']=vp
  calibrator=fit(LogisticRegression(C=1,max_iter=2000,random_state=0),logit(cp),yc)
  predictions['building_calibrated']=calibrator.predict_proba(logit(vp))[:,1]
  previous=json.loads((out/'group_calibration.json').read_text(encoding='utf-8'))
  previous=next(w for w in previous['windows'] if w['window']==f'{start}-{stop}')
  for name in ['uncalibrated','global','global_regularized']:
   for metric in ['brier','log_loss','predicted_pct']:
    assert np.isclose(metrics(yv,predictions[name])[metric],previous['scores'][name][metric],rtol=1e-7,atol=1e-9)
  scores={}
  for name,p in predictions.items():
   assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all();scores[name]=metrics(yv,p)
   for field in ['gu','category']:
    group_rows=[]
    for group in sorted(va[field].unique()):
     mask=va[field].eq(group).to_numpy();m=metrics(yv[mask],p[mask]);group_rows.append(m);subs.append({'window':f'{start}-{stop}','model':name,'field':field,'group':group,**m})
    assert sum(m['n'] for m in group_rows)==len(va) and sum(m['events'] for m in group_rows)==int(yv.sum())
    for key in ['brier','log_loss','actual_pct','predicted_pct']:assert np.isclose(sum(m[key]*m['n'] for m in group_rows)/len(va),scores[name][key])
  windows.append({'window':f'{start}-{stop}','train_end':end,'calibration_year':calyear,'train_n':len(tr),'calibration_n':len(cal),'calibration_events':int(yc.sum()),'scores':scores,'coefficients':coefficients})
  print('Completed',start,flush=True)
 passed=[name for name,baseline in [('building_rf','uncalibrated'),('building_calibrated','global_regularized')] if all(w['scores'][name][metric]<w['scores'][baseline][metric] for w in windows for metric in ['brier','log_loss'])]
 for k,p in paths.items():verify_snapshot_hash(p,prior['hashes'][k])
 result={'scope':'reused historical windows exploratory comparison, not independent validation','windows':windows,'subgroups':subs,'passed':passed,'hashes':{k:snapshot_sha256(p) for k,p in paths.items()},'plan_hash':snapshot_sha256(out/'building_history_plan.md'),'script_hash':snapshot_sha256(Path(__file__)),'python':platform.python_version()}
 (out/'building_history.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 같은 건물 과거 이력 추가 결과','','동일 과거 기간 재사용 탐색. 신규 독립 검증·서비스 채택 아님.','','| 기간 | 후보 | Brier | log loss | 평균예측% | 실제% |','| --- | --- | ---: | ---: | ---: | ---: |']
 for w in windows:
  for name,m in w['scores'].items():lines.append(f"| {w['window']} | {name} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['predicted_pct']:.2f} | {m['actual_pct']:.2f} |")
 lines+=['',f'세 기간 모두 대응 RF 대조보다 두 오차 개선: {passed or "없음"}.','', '구군/업태별 표본과 점수는 JSON에 기록. 전체 평균 개선만으로 개별 예측을 채택하지 않는다. 현재 면적 시점·표본 선택·행사 혼입 한계 유지. 입력 해시·기존 RF 점수·분할·확률·집단 가중지표 검사 통과. 2025 재평가·운영 변경 없음.','', '[계획](building_history_plan.md), [결과](building_history.json).']
 (out/'building_history.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'passed':passed,'windows':windows},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
