"""Matched complete-case baseline; frozen existing area scores reused."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from fit_d03 import ROOT,metrics,verify_snapshot_hash,snapshot_sha256,Pipeline,OneHotEncoder,LogisticRegression
from fit_d03_expanded import fit,target
import sys
sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area

def main():
 out=ROOT/'docs/d03'; prior=json.loads((out/'area_complete.json').read_text(encoding='utf-8'))
 paths={'stores':ROOT/'service/data/processed/stores.parquet','raw':ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv','script':ROOT/'scripts/fit_d03_area_complete.py','parser':ROOT/'service/pipeline/numeric.py','feature_helper':ROOT/'scripts/fit_d03_expanded.py','spatial_helper':ROOT/'scripts/fit_d03_historical_context.py','metrics':ROOT/'scripts/fit_d03.py'}
 for k,p in paths.items():verify_snapshot_hash(p,prior['hashes'][k])
 s=pd.read_parquet(paths['stores']);f=s[s.service.eq('일반음식점') & s.ld.dt.year.between(2010,2021) & s.lat.between(-90,90) & s.lon.between(-180,180)].copy().reset_index(drop=True)
 r=pd.read_csv(paths['raw'],encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적']);r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 keys=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 assert keys.is_unique
 raw=keys.map(r.set_index('key')['소재지면적']);parsed=parse_area(raw);a=f.area_m2.copy();recover=a.isna()&raw.str.contains(',',regex=False,na=False)&parsed.notna();a.loc[recover]=parsed[recover].astype(float)
 f=f[np.isfinite(a)&a.gt(0)].copy();assert len(f)==prior['n'];assert not (f.cd.notna()&f.cd.lt(f.ld)).any()
 f['open_month']=f.ld.dt.month.astype(str)
 cols=['category','gu','open_month'];f[cols]=f[cols].astype('string').fillna('__MISSING__').astype(str)
 results=[]
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)];y=target(tr);yv=target(va)
  assert not set(tr.index)&set(va.index);assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min()
  old=next(w for w in prior['windows'] if w['window']==f'{start}-{stop}');assert len(tr)==old['train_n']
  constant=metrics(yv,np.full(len(va),y.mean()))
  for k in ['n','events','brier','log_loss','predicted_pct']:assert np.isclose(constant[k],old['scores']['constant'][k])
  m=fit(Pipeline([('onehot',OneHotEncoder(handle_unknown='ignore')),('logistic',LogisticRegression(C=1,max_iter=2000,random_state=0))]),tr[cols],y)
  scores={'basic_logistic':metrics(yv,m.predict_proba(va[cols])[:,1]),**old['scores']}
  results.append({'window':old['window'],'train_n':len(tr),'scores':scores})
 report={'scope':'same complete cases and training/evaluation years; uncalibrated comparison; exploratory, not independent test','windows':results,'hashes':{'prior':snapshot_sha256(out/'area_complete.json'),'script':snapshot_sha256(Path(__file__)),'stores':snapshot_sha256(paths['stores']),'raw':snapshot_sha256(paths['raw'])}}
 (out/'matched_baseline.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 同一標本 비교'.replace('同一標本','동일 표본'),'','기본 모델만 새로 계산하고 면적·주변 맥락 모델은 해시가 일치하는 기존 결과를 재사용했다. 학습과 평가 모두 좌표·양수 면적 표본이다. 보정 없음.','','| 기간 | 모델 | n | Brier | log loss |','| --- | --- | ---: | ---: | ---: |']
 for w in results:
  for name,m in w['scores'].items():lines.append(f"| {w['window']} | {name} | {m['n']} | {m['brier']:.6f} | {m['log_loss']:.6f} |")
 lines+=['','현재 면적의 과거 시점 유효성은 미확인이다. 누락 집단에 일반화하지 않으며 2023~2025 재평가 없음. 기본 회귀와 면적 랜덤포레스트의 차이는 알고리즘·입력 모두의 차이이므로 면적 효과만으로 해석하지 않는다. 면적 추가 효과는 같은 알고리즘의 context/area 쌍으로 판단한다.']
 (out/'matched_baseline.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print('\n'.join(lines))
if __name__=='__main__':main()
