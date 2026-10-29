"""Frozen exploratory group calibration on historical windows only."""
import json,platform
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
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
  for name,fields,c in [('global',[],1e6),('global_regularized',[],1),('gu',['gu'],1),('category',['category'],1),('gu_category',['gu','category'],1)]:
   xc,xv=logit(pc),logit(pv);names=['base_logit']
   if fields:
    enc=OneHotEncoder(handle_unknown='ignore',sparse_output=False)
    ec=enc.fit_transform(cal[fields]);ev=enc.transform(va[fields]);xc=np.column_stack([xc,ec]);xv=np.column_stack([xv,ev]);names+=list(enc.get_feature_names_out())
    unseen=cal[fields].iloc[:1].copy()
    for field in fields:unseen[field]='__AUDIT_UNSEEN__'
    assert not enc.transform(unseen).any()
   m=fit(LogisticRegression(C=c,max_iter=2000,random_state=0),xc,yc)
   predictions[name]=m.predict_proba(xv)[:,1]
   coefficients[name]={'intercept':float(m.intercept_[0]),'weights':dict(zip(names,m.coef_[0].tolist()))}
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
 passed=[name for name in ['gu','category','gu_category'] if all(w['scores'][name][metric]<w['scores'][baseline][metric] for w in windows for metric in ['brier','log_loss'] for baseline in ['global','global_regularized'])]
 for k,p in paths.items():verify_snapshot_hash(p,prior['hashes'][k])
 result={'scope':'reused historical windows exploratory comparison, not independent validation','windows':windows,'subgroups':subs,'passed':passed,'hashes':{k:snapshot_sha256(p) for k,p in paths.items()},'plan_hash':snapshot_sha256(out/'group_calibration_plan.md'),'script_hash':snapshot_sha256(Path(__file__)),'python':platform.python_version()}
 (out/'group_calibration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 지역·업태 차이를 반영한 확률 보정 비교','','현재면적/과거주소 미확인·행사혼입을 유지한 후속탐색.2025/기존최종시험은이번에재평가하지않았다.','','| 기간 | 모델 | n | 실제% | 예측% | Brier | log loss |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
 for w in windows:
  for name,m in w['scores'].items():lines.append(f"| {w['window']} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} |")
 lines+=['',f'세기간 모두 두전체보정보다 두오차가 작은 집단보정 후보: {passed or "없음"}.','','무보정RF는각분할의과거학습만사용해이전전체학습RF와다르다. 후보들은같은기초RF/보정표본을공유한다. C=1 정규화전체를함께비교해정규화효과와집단추가를구분했다. 각집단별수치와계수는JSON에남겼다. 작은집단의L2수축은성능보장이아니며새기간검증이필요하다.','','입력해시·날짜365일간격·기존평가표본수/사건수·확률/수렴·미관측범주·집단합계/가중지표검사통과. 결과후조건/기간/C재탐색없음. 서비스/DB/원본변경없음.','','[계획](group_calibration_plan.md),[전체결과](group_calibration.json). 재현:`python scripts/fit_d03_group_calibration.py`.']
 (out/'group_calibration.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'passed':passed,'windows':[{k:v for k,v in w.items() if k!='coefficients'} for w in windows]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
