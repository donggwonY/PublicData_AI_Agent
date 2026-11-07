"""Building age pilot on identical matched cohorts; retrospective and exploratory."""
import json,re,warnings
from pathlib import Path
import pandas as pd,numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 warnings.simplefilter('error',ConvergenceWarning)
 src=OUT/'building_api_900.json';raw=json.loads(src.read_text(encoding='utf-8'));assert len(raw['results'])==900 and 'counts' in raw
 codes=json.loads((OUT/'daegu_legal_codes.json').read_text(encoding='utf-8'))['codes'];lookup={}
 for r in raw['results']:
  if r.get('status')!='ok' or r.get('total')!=1:continue
  assert len(r['items'])==1
  x=r['items'][0];m=re.fullmatch(r'(.+?) (산)?\s*(\d+)(?:-(\d+))?',r['building_key']);code=codes[m[1]]
  assert str(x['sigunguCd'])+str(x['bjdongCd'])==code and int(x['bun'])==int(m[3]) and int(x['ji'])==int(m[4] or 0)
  date=pd.to_datetime(str(x.get('useAprDay','')),format='%Y%m%d',errors='coerce')
  if pd.notna(date):lookup[r['building_key']]=date
 sp=ROOT/'service/data/processed/stores.parquet';f=pd.read_parquet(sp);f=f[f.service.eq('일반음식점')].copy();total=len(f)
 f['approval']=f.building_key.map(lookup);matched=f.approval.notna();after=f.approval.gt(f.ld)
 quality={'all_restaurants':total,'single_dated_buildings':len(lookup),'matched_permits':int(matched.sum()),'approval_after_license':int((matched&after).sum())}
 f=f[matched&~after].copy()
 def cohort(y):
  t=pd.Timestamp(y,1,1);a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy()
  age=(t-a.ld).dt.days;ba=(t-a.approval).dt.days;assert ba.ge(age).all() and age.ge(0).all()
  a['age_band']=pd.cut(age,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['building_age_band']=pd.cut(ba,[-1,3649,7299,10949,np.inf],labels=['<10','10-20','20-30','30+']).astype(str)
  a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int);return a
 windows=[]
 for train,test in [(2013,2015),(2015,2017),(2018,2020),(2021,2023)]:
  a,b=cohort(train),cohort(test);assert pd.Timestamp(train,1,1)+pd.Timedelta(days=365)<pd.Timestamp(test,1,1)
  assert a.y.nunique()==2 and b.y.nunique()==2
  preds={'constant':np.full(len(b),a.y.mean())}
  for name,cols in [('age',['age_band']),('age_building',['age_band','building_age_band'])]:
   model=make_pipeline(OneHotEncoder(handle_unknown='ignore'),LogisticRegression(C=1,max_iter=2000,random_state=7));model.fit(a[cols],a.y);preds[name]=model.predict_proba(b[cols])[:,1]
  windows.append({'train':train,'test':test,'train_n':len(a),'train_events':int(a.y.sum()),'test_buildings':b.building_key.nunique(),'scores':{n:metrics(b.y.to_numpy(),p) for n,p in preds.items()}})
 out={'scope':'current building approval date conditioned subset, not causal or point-in-time proven','quality':quality,'windows':windows,'hashes':{'source':snapshot_sha256(src),'stores':snapshot_sha256(sp),'script':snapshot_sha256(Path(__file__))}}
 (OUT/'building_age_experiment.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 建物'.replace('建物','건물 나이 추가 소규모 탐색'),'','현재 건물 승인일 <= 인허가일 <= 기준일 조건, 동일 연결표본에서 운영기간만 vs 운영기간+건물나이 비교. 건물 동일성/과거가용성 입증 아님. 구군별100필지 표집으로 전체대구 대표성 없음. 결과로 모델 선택·튜닝하지 않음.','',json.dumps(quality,ensure_ascii=False),'','|학습→평가|후보|n|신고|실제%|예측%|Brier|log loss|','|---|---|---:|---:|---:|---:|---:|---:|']
 for w in windows:
  for name,s in w['scores'].items():lines.append(f"|{w['train']}→{w['test']}|{name}|{s['n']}|{s['events']}|{s['actual_pct']:.2f}|{s['predicted_pct']:.2f}|{s['brier']:.6f}|{s['log_loss']:.6f}|")
 lines+=['','미연결·다중건물·날짜불일치 제외에 따른 선택편향 존재. 표본 작고 기존연도 재사용. 전체표본 기존모델과 점수 직접비교 금지. 현재 건물면적·용도·층수 미사용. 서비스·DB 변경 없음.']
 (OUT/'building_age_experiment.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines))
if __name__=='__main__':main()
