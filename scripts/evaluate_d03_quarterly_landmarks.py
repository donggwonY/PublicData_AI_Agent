"""Frozen model evaluated at quarterly landmarks; overlapping follow-up, not independent trials."""
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
sys.path.insert(0,str(ROOT/'service'))
from core.prediction_preview import model_probability
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
path=ROOT/'service/data/processed/stores.parquet'
mp=ROOT/'service/data/research/closure_preview_model.json'
m=json.loads(mp.read_text(encoding='utf-8'));assert snapshot_sha256(path)==m['source_hash']
f=pd.read_parquet(path);ref=pd.Timestamp(m['source_reference_date'])
f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna();f=f[~bad].copy()
original=json.loads((OUT/'final2025_result.json').read_text(encoding='utf-8'))['window']
bases={x['industry']:x['scores']['baseline']['predicted_pct']/100 for x in original['groups']}
rows=[]
for date in ['2025-01-01','2025-04-01','2025-07-01','2025-10-01']:
 t=pd.Timestamp(date);end=t+pd.Timedelta(days=365);assert end<=ref
 a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy().reset_index(drop=True)
 a['age_band']=pd.cut((t-a.ld).dt.days,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
 a['y']=(a.closed&a.cd.gt(t)&a.cd.le(end)).astype(int)
 assert set(a.industry)<=set(bases), 'New industry needs predeclared fallback'
 pred=np.array([model_probability(m,x.industry,str(x.gu),x.age_band) for x in a.itertuples()])
 base=a.industry.map(bases).to_numpy();y=a.y.to_numpy()
 scores={'baseline':metrics(y,base),'candidate':metrics(y,pred)}
 if date=='2025-01-01':
  for k in ['brier','log_loss','predicted_pct']:assert abs(scores['candidate'][k]-original['overall']['region_cal'][k])<1e-12
 regions=[]
 for (industry,gu),g in a.groupby(['industry','gu'],dropna=False):
  ix=g.index.to_numpy();regions.append({'industry':industry,'gu':str(gu),'small_sample':len(g)<200 or g.y.sum()<20,'scores':{'baseline':metrics(y[ix],base[ix]),'candidate':metrics(y[ix],pred[ix])}})
 for model in scores:
  assert sum(x['scores'][model]['n'] for x in regions)==len(a)
  assert abs(sum(x['scores'][model]['brier']*x['scores'][model]['n'] for x in regions)/len(a)-scores[model]['brier'])<1e-12
 rows.append({'landmark':date,'followup_end':str(end.date()),'scores':scores,'regions':regions})
 print(date,scores,flush=True)
# numpy comparisons produce numpy bools, convert explicitly for JSON.
for row in rows:
 for cell in row['regions']:cell['small_sample']=bool(cell['small_sample'])
out={'model':'Frozen train2021/cal2023; no refitting or calibration updates','rows':rows,'hashes':{'stores':snapshot_sha256(path),'model':snapshot_sha256(mp),'script':snapshot_sha256(Path(__file__))},'limitations':['Quarterly follow-up overlaps and permits repeat; not four independent trials.','Quarter dates chosen after earlier evaluations; retrospective supplementary analysis.','No post-result exclusion or selection of good groups.','Not validation of future current-date forecasts or seasonal causality.']}
(OUT/'quarterly_landmarks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
lines=['# 고정 모델 분기 시작일 평가','','2021학습·2023보정 모델을 그대로 적용했습니다. 연초에만 평가한 모델의 시점 이동을 점검하는 사후 분석입니다. 각 시작일에 영업 중인 적격 인허가 전체를 사용하고 이후365일을 관찰했습니다.','','|기준일|표본|실제%|예측%|기준선 Brier|모델 Brier|기준선 log loss|모델 log loss|','|---|---:|---:|---:|---:|---:|---:|---:|']
for row in rows:
 b=row['scores']['baseline'];c=row['scores']['candidate'];lines.append(f"|{row['landmark']}|{c['n']:,}|{c['actual_pct']:.2f}|{c['predicted_pct']:.2f}|{b['brier']:.6f}|{c['brier']:.6f}|{b['log_loss']:.6f}|{c['log_loss']:.6f}|")
lines+=['','기간과 인허가가 겹치므로 독립된4회 검증이 아닙니다. 미래 운영 성능·계절 원인·모든 업종 적용을 입증하지 않습니다. 서비스 표시 기준으로 사후 제외한 성능이 아닌 전체 결과이며, 지역별 소표본과 점수는 JSON에 보존했습니다.']
(OUT/'quarterly_landmarks.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
