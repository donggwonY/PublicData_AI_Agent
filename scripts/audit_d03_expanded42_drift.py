"""Describe calibration-to-evaluation drift; no model tuning or causal claims."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'docs/d03'
p=ROOT/'service/data/processed/stores.parquet'
source=json.loads((OUT/'expanded42_calibration.json').read_text(encoding='utf-8'))
assert snapshot_sha256(p)==source['hashes']['stores']
f=pd.read_parquet(p);f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna()
f=f[~bad].copy()
selected=json.loads((OUT/'expanded42_regions.json').read_text(encoding='utf-8'))['selected_industries']
def cohort(y):
 t=pd.Timestamp(y,1,1)
 a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy()
 a['age_band']=pd.cut((t-a.ld).dt.days,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
 a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
 return a
c,b=cohort(2021),cohort(2023)
rows=[]
for (industry,gu),g in b[b.industry.isin(selected)].groupby(['industry','gu'],dropna=False):
 cg=c[c.industry.eq(industry)&(c.gu.eq(gu) if pd.notna(gu) else c.gu.isna())]
 bands=[]
 for band in ['<1','1-3','3-5','5-10','10+']:
  old=cg[cg.age_band.eq(band)];new=g[g.age_band.eq(band)]
  bands.append({'age_band':band,'cal_n':len(old),'test_n':len(new),'cal_events':int(old.y.sum()),'test_events':int(new.y.sum()),'cal_rate_pct':float(old.y.mean()*100) if len(old) else None,'test_rate_pct':float(new.y.mean()*100) if len(new) else None})
 assert sum(x['test_n'] for x in bands)==len(g)
 assert sum(x['cal_n'] for x in bands)==len(cg)
 supported=all(x['cal_n']>0 for x in bands if x['test_n'])
 standardized=sum(x['test_n']/len(g)*x['cal_rate_pct'] for x in bands if x['test_n']) if supported else None
 scores=next(x['scores'] for x in source['windows'][-1]['regions'] if x['industry']==industry and x['gu']==str(gu))
 rows.append({'industry':industry,'gu':str(gu),'cal_n':len(cg),'test_n':len(g),'cal_rate_pct':float(cg.y.mean()*100) if len(cg) else None,'test_rate_pct':float(g.y.mean()*100),'cal_rate_with_test_age_mix_pct':standardized,'small_sample':len(g)<200 or int(g.y.sum())<20,'age_bands':bands,'scores':scores})
out={'cal_year':2021,'test_year':2023,'rows':rows,'hashes':{'stores':snapshot_sha256(p),'script':snapshot_sha256(Path(__file__)),'calibration_result':snapshot_sha256(OUT/'expanded42_calibration.json')},'limitations':['Post-hoc descriptive diagnosis; no causal attribution or new evaluation.','Age-standardized rate holds 2021 within-band rates fixed; missing bands return null.','Current address, repeated permits and historical availability limitations remain. Short events retained.']}
(OUT/'expanded42_drift.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
lines=['# 보정기간과 평가기간의 신고율·운영기간 변화','','2021년 보정 자료와 2023년 평가 자료의 사후 진단입니다. 2023 운영기간 구성으로 가중한 2021 신고율을 함께 제시합니다. 원인 입증이나 새 모델 검증이 아닙니다.','','|업종·지역|2021 n|2023 n|2021 신고%|구성만 2023으로 변경%|2023 신고%|','|---|---:|---:|---:|---:|---:|']
for x in rows:
 if (x['industry'],x['gu']) in [('휴게음식점','중구'),('일반음식점','북구'),('즉석판매제조가공업','수성구')]:
  value=x['cal_rate_with_test_age_mix_pct'];text=f'{value:.2f}' if value is not None else '산출 불가'
  lines.append(f"|{x['industry']} · {x['gu']}|{x['cal_n']}|{x['test_n']}|{x['cal_rate_pct']:.2f}|{text}|{x['test_rate_pct']:.2f}|")
lines+=['','8개 후보 업종의 모든 지역 및 운영기간별 표본·신고 건수는 JSON에 저장했습니다. 보정은 과거 신고율을 반영하므로 이후 신고율 변화에 따라 악화될 수 있습니다. 구성 조정 후에도 차이가 남는 경우 운영기간 비중 변화만으로 설명되지 않는다는 뜻이며, 경제 상황·신고 관행 등 특정 원인으로 단정할 수 없습니다. 소표본 표시는 JSON을 따릅니다. 서비스 적용·추가 튜닝 없음.']
(OUT/'expanded42_drift.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines))
