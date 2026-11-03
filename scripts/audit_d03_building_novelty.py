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
 original=json.loads((out/'building_history.json').read_text(encoding='utf-8'))
 windows=[];subs=[];novelty=[]
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
  reference=next(w for w in original['windows'] if w['window']==f'{start}-{stop}')
  for name in predictions:
   for metric in ['n','events','brier','log_loss','predicted_pct']:
    assert np.isclose(scores[name][metric],reference['scores'][name][metric],rtol=1e-7,atol=1e-9)
  normalize=lambda v:v.astype('string').fillna('').str.strip()
  tk=normalize(tr.building_key);ck=normalize(cal.building_key);vk=normalize(va.building_key)
  assert vk.ne('').all()
  seen=vk.isin(set(tk[tk.ne('')])).to_numpy();cal_seen=vk.isin(set(ck[ck.ne('')])).to_numpy()
  masks={'seen_training':seen,'calibration_only':~seen&cal_seen,'unseen_both':~seen&~cal_seen}
  assert np.all(sum(masks.values())==1)
  for name in ['uncalibrated','global_regularized','building_rf','building_calibrated']:
   local=[]
   for group,mask in masks.items():
    if not mask.any():continue
    m=metrics(yv[mask],predictions[name][mask]);local.append(m)
    novelty.append({'window':f'{start}-{stop}','model':name,'group':group,'small':bool(m['n']<100 or min(m['events'],m['n']-m['events'])<10),**m})
   assert sum(m['n'] for m in local)==len(va) and sum(m['events'] for m in local)==int(yv.sum())
   for metric in ['brier','log_loss','predicted_pct','actual_pct']:
    assert np.isclose(sum(m[metric]*m['n'] for m in local)/len(va),scores[name][metric])
  windows.append({'window':f'{start}-{stop}','train_end':end,'calibration_year':calyear,'train_n':len(tr),'calibration_n':len(cal),'calibration_events':int(yc.sum()),'scores':scores,'coefficients':coefficients})
  print('Completed',start,flush=True)
 passed=[name for name,baseline in [('building_rf','uncalibrated'),('building_calibrated','global_regularized')] if all(w['scores'][name][metric]<w['scores'][baseline][metric] for w in windows for metric in ['brier','log_loss'])]
 for k,p in paths.items():verify_snapshot_hash(p,prior['hashes'][k])
 result={'scope':'reused historical windows exploratory comparison, not independent validation','windows':windows,'subgroups':subs,'novelty':novelty,'passed':passed,'hashes':{k:snapshot_sha256(p) for k,p in paths.items()},'plan_hash':snapshot_sha256(out/'building_novelty_plan.md'),'script_hash':snapshot_sha256(Path(__file__)),'python':platform.python_version()}
 (out/'building_novelty.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 학습에서 보지 못한 건물의 예측 점검','','세 그룹은 기초학습 등장 / 보정에만 등장 / 둘 다 미등장으로 나눈다. 미등장은 신규 독립 시험이나 이력 없음과 다르다.','','| 기간 | 그룹 | 후보 | 표본 | 신고 | Brier 감소 | log loss 감소 | 소표본 |','| --- | --- | --- | ---: | ---: | ---: | ---: | --- |']
 for w in windows:
  for group in ['seen_training','calibration_only','unseen_both']:
   for cand,base_name in [('building_rf','uncalibrated'),('building_calibrated','global_regularized')]:
    matches=[r for r in novelty if r['window']==w['window'] and r['group']==group]
    if not matches:continue
    c=next(r for r in matches if r['model']==cand);b=next(r for r in matches if r['model']==base_name)
    lines.append(f"| {w['window']} | {group} | {cand} | {c['n']} | {c['events']} | {b['brier']-c['brier']:+.7f} | {b['log_loss']-c['log_loss']:+.7f} | {c['small']} |")
 lines+=['','양수는 대응 대조보다 오차 감소. 이전 전체 점수 재현·그룹 합계·가중지표 검사를 통과했다. 불확실성 재표집은 이번 그룹별로 수행하지 않았다. 현재주소/면적 시점 및 반복 사용한 검증기간 한계 유지. 2025 재평가 없음.','', '[계획](building_novelty_plan.md), [결과](building_novelty.json).']
 (out/'building_novelty.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('\n'.join(lines),flush=True)
if __name__=='__main__':main()
