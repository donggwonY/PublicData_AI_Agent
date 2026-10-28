"""Frozen retrospective 2025 temporal assessment, not deployment validation."""
import json,platform
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
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
 y,yv=target(tr),target(va);pred={'constant':np.full(len(va),y.mean())}
 print('Frozen train/test prepared',len(tr),len(va),flush=True)
 for extra in [False,True]:
  name='forest_area' if extra else 'forest_context';m=fit(model('forest',extra),tr,y);pred[name]=m.predict_proba(va)[:,1]
  assert 'area_missing' not in m.named_steps['features'].transformers_[1][2]
 scores={n:metrics(yv,p) for n,p in pred.items()}
 for p in pred.values():assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
 key=va.building_key.astype('string');known=tr.building_key.dropna().astype(str);known=known[known.str.strip().ne('')]
 available=key.notna()&key.fillna('').str.strip().ne('');groups=key.copy();groups.loc[available]='building:'+groups.loc[available]
 for idx in va.index[~available]:groups.loc[idx]='missing:'+str(idx)
 uncertainty={b:bootstrap(losses(yv,pred['forest_area'])-losses(yv,pred[b]),groups.to_numpy()) for b in ['constant','forest_context']}
 subs=[]
 for field in ['gu','building_seen']:
  vals=va.gu if field=='gu' else pd.Series(np.where(~available,'missing',np.where(key.isin(known),'seen','new')),index=va.index)
  for group in sorted(vals.unique()):
   mask=vals.eq(group).to_numpy()
   for name,p in pred.items():subs.append({'field':field,'group':group,'model':name,**metrics(yv[mask],p[mask])})
 calibration=[]
 for lo,hi in [(0,.05),(.05,.1),(.1,.2),(.2,1.0000001)]:
  mask=(pred['forest_area']>=lo)&(pred['forest_area']<hi)
  if mask.any():calibration.append({'lower':lo,'upper':min(hi,1),'n':int(mask.sum()),'events':int(yv[mask].sum()),'predicted_pct':float(pred['forest_area'][mask].mean()*100),'actual_pct':float(yv[mask].mean()*100)})
 assert sum(c['n'] for c in calibration)==len(va)
 for field in ['gu','building_seen']:
  for name in pred:
   g=[x for x in subs if x['field']==field and x['model']==name]
   assert sum(x['n'] for x in g)==len(va) and sum(x['events'] for x in g)==int(yv.sum())
 passed=all(scores['forest_area'][m]<scores[b][m] for b in ['constant','forest_context'] for m in ['brier','log_loss'])
 result={'scope':'2025 Jan-Sep fixed additional temporal assessment; retrospective area assumption; not external validation','reference_date':str(ref.date()),'train_n':len(tr),'train_events':int(y.sum()),'test_original_n':test_initial,'test_coord_excluded':coord_excluded,'test_area_excluded':test_area_excluded,'scores':scores,'bootstrap':uncertainty,'subgroups':subs,'calibration':calibration,'criterion_passed':passed,'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(OUT/'area_2025_plan.md'),'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'model_helper':snapshot_sha256(ROOT/'scripts/fit_d03_area_complete.py'),'bootstrap_helper':snapshot_sha256(ROOT/'scripts/audit_d03_area_stability.py'),'spatial_helper':snapshot_sha256(ROOT/'scripts/fit_d03_historical_context.py'),'parser':snapshot_sha256(ROOT/'service/pipeline/numeric.py')},'python':platform.python_version()}
 assert test_initial-coord_excluded-test_area_excluded==len(va)
 (OUT/'area_2025.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 고정 면적RF의2025 추가 시간 평가','','현재면적=개업당시면적이라는 미확인 가정의 과거 재구성이다. 새 기간에 대한 고정 설정 비교지만 외부독립/완전맹검/실서비스 입증은 아니다. 2023~2024 기존최종시험은 재채점하지 않았다.','',f'학습2010~2023 {len(tr):,}건.2024목표학습 제외.평가2025년1~9월 원래{test_initial:,}건 중좌표{coord_excluded}건·면적{test_area_excluded}건 제외하여{len(va):,}건. 기준{ref.date()}으로365일 전원관측.','','| 모델 | n | 실제% | 평균예측% | Brier | log loss | AUC |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
 for name,m in scores.items():lines.append(f"| {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['roc_auc']:.4f} |")
 lines+=['',f'두기준선 대비 두오차 개선 기준: {passed}.','','## 고정 예측구간 점검','','| 예측구간 | n | 평균예측% | 실제% |','| --- | ---: | ---: | ---: |']
 for c in calibration:lines.append(f"| {c['lower']*100:g}~{c['upper']*100:g}% | {c['n']} | {c['predicted_pct']:.2f} | {c['actual_pct']:.2f} |")
 lines+=['','## 검증과 한계','','계획/입력해시 고정,과거맥락 직접거리3건대조·자기제외·날짜경계검사,학습365일간격/평가365일기회,동일표본,누락입력제외,확률범위/수렴,구군·건물별표본/사건 합계검사 통과. 건물paired bootstrap2000회 및 하위집단 점수는 JSON에 보존. 평가결과로 재튜닝/보정하지 않았다.','','현재면적/주소/공개일이 당시와 같다는 보증은 없고 양수면적만의 선택편향·한시영업 혼입 가능성이 남는다. 2025년1~9월만의 결과를 연간전체로 일반화하지 않는다. 모델설정 고정 상태에서 새기간을 평가했지만 동일스냅샷/이전탐색과의 연관을 없앤 외부검증은 아니다. 운영/DB/가공본/배포 변경 없음.','','[사전계획](area_2025_plan.md),[전체결과](area_2025.json). 재현:`python scripts/evaluate_d03_area_2025.py`.']
 (OUT/'area_2025.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'train_n':len(tr),'excluded':test_area_excluded,'scores':scores,'passed':passed,'calibration':calibration},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
