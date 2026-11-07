"""Fixed exploratory land-price ablation, identical matched cohorts."""
import json,warnings
from pathlib import Path
import pandas as pd,numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 warnings.simplefilter('error',ConvergenceWarning)
 src=OUT/'land_prices_900.json';raw=json.loads(src.read_text(encoding='utf-8'))['results'];assert len(raw)==900
 records=[dict(x,building_key=r['building_key']) for r in raw if r['status']=='ok' for x in r['items']]
 prices=pd.DataFrame(records)
 prices['pub']=pd.to_datetime(prices.pblntfDe,errors='coerce')
 prices['year']=pd.to_numeric(prices.stdrYear,errors='coerce');prices['price']=pd.to_numeric(prices.pblntfPclnd,errors='coerce')
 valid=prices.pub.notna()&prices.year.notna()&prices.price.gt(0)&np.isfinite(prices.price)
 quality={'requested_parcels':len(raw),'ok_parcels':sum(r['status']=='ok' for r in raw),'raw_price_rows':len(prices),'invalid_price_or_date_rows':int((~valid).sum())}
 prices=prices[valid].copy()
 sp=ROOT/'service/data/processed/stores.parquet';f=pd.read_parquet(sp);f=f[f.service.eq('일반음식점')].copy()
 candidates={r['building_key'] for r in raw};f=f[f.building_key.isin(candidates)].copy()
 audit={}
 def cohort(year):
  t=pd.Timestamp(year,1,1);p=prices[prices.pub.lt(t)&prices.year.lt(year)].copy()
  p=p[p.pub.eq(p.groupby('building_key').pub.transform('max'))]
  conflict=p.groupby('building_key').price.nunique();bad=set(conflict[conflict.gt(1)].index)
  p=p[~p.building_key.isin(bad)].drop_duplicates('building_key')
  a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy();before=len(a)
  a=a.merge(p[['building_key','price','pub']],on='building_key',how='inner',validate='many_to_one')
  assert a.pub.lt(t).all()
  age=(t-a.ld).dt.days
  a['age_band']=pd.cut(age,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['log_price']=np.log(a.price)
  a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
  audit[str(year)]={'eligible_in_sample':before,'matched':len(a),'unmatched':before-len(a),'conflicting_price_parcels':len(bad),'unique_buildings':int(a.building_key.nunique())}
  return a
 windows=[]
 for train,test in [(2013,2015),(2015,2017),(2018,2020),(2021,2023)]:
  a,b=cohort(train),cohort(test)
  assert a.y.nunique()==2 and b.y.nunique()==2
  assert pd.Timestamp(train,1,1)+pd.Timedelta(days=365)<pd.Timestamp(test,1,1)
  preds={'constant':np.full(len(b),a.y.mean())}
  for name,extra in [('age',False),('age_land_price',True)]:
   transformers=[('age',OneHotEncoder(handle_unknown='ignore'),['age_band'])]
   if extra:transformers.append(('price',StandardScaler(),['log_price']))
   model=make_pipeline(ColumnTransformer(transformers),LogisticRegression(C=1,max_iter=2000,random_state=7))
   model.fit(a,a.y);preds[name]=model.predict_proba(b)[:,1]
  scores={n:metrics(b.y.to_numpy(),p) for n,p in preds.items()}
  windows.append({'train':train,'test':test,'train_n':len(a),'train_events':int(a.y.sum()),'scores':scores,'brier_delta':scores['age_land_price']['brier']-scores['age']['brier'],'log_loss_delta':scores['age_land_price']['log_loss']-scores['age']['log_loss']})
 out={'scope':'Exploratory matched parcel subset; not independent evaluation or deployment recommendation','quality':quality,'cohorts':audit,'windows':windows,'hashes':{'source':snapshot_sha256(src),'stores':snapshot_sha256(sp),'script':snapshot_sha256(Path(__file__))}}
 (OUT/'land_price_experiment.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 공시지가 추가 탐색','','동일 표본의 운영기간 LR 대비 과거 공시지가 log값 추가. 공시일<예측일, 기준연도<예측연도. 공시지가는 임대료가 아님.','',json.dumps(quality,ensure_ascii=False),'','|학습→평가|후보|평가 n|신고 건수|실제%|예측%|Brier|log loss|','|---|---|---:|---:|---:|---:|---:|---:|']
 for w in windows:
  for name,s in w['scores'].items():lines.append(f"|{w['train']}→{w['test']}|{name}|{s['n']}|{s['events']}|{s['actual_pct']:.2f}|{s['predicted_pct']:.2f}|{s['brier']:.6f}|{s['log_loss']:.6f}|")
 wins=sum(w['brier_delta']<0 and w['log_loss_delta']<0 for w in windows)
 lines+=['',f'두 오차지표 모두 개선된 기간: {wins}/4. 개선폭과 기간 일관성은 별도 해석 필요.','현재 필지의 과거가격 조회: 분할·합병·주소이전·사후수정 미검증. 최신 인허가로 과거 영업점 재구성. 동일 인허가의 연도 간 반복 가능. 구군균등900필지 중 연결표본으로 전체 대표성 없음. 이미 본 평가연도 재사용 탐색. 2025 미사용, 튜닝·DB·서비스 반영 없음.']
 (OUT/'land_price_experiment.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines))
if __name__=='__main__':main()
