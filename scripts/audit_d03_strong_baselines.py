"""Fixed stronger baselines plus subgroup temporal stability; no model refit."""
import json,math
from pathlib import Path
from collections import defaultdict
import numpy as np,pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'

def constant_scores(n,events,p):
 rate=events/n;p=float(p);q=np.clip(p,np.finfo(float).eps,1-np.finfo(float).eps)
 return {'n':n,'events':events,'actual_pct':rate*100,'predicted_pct':p*100,'brier':p*p-2*p*rate+rate,'log_loss':float(-rate*np.log(q)-(1-rate)*np.log1p(-q))}

def main():
 source=OUT/'all_quarters_evaluation.json';r=json.loads(source.read_text(encoding='utf-8'))
 path=ROOT/'service/data/processed/stores.parquet';assert snapshot_sha256(path)==r['hashes']['stores']
 f=pd.read_parquet(path);f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna();f=f[~bad].copy()
 cache={};windows=[];history=defaultdict(list)
 for w in r['results']:
  cal=w['cal']
  if cal not in cache:
   t=pd.Timestamp(cal);a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy()
   a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
   cache[cal]={(name,str(gu)):(len(g),int(g.y.sum())) for (name,gu),g in a.groupby(['industry','gu'],dropna=False)}
  regions=[]
  for g in w['regions']:
   key=(g['industry'],g['gu']);n=g['scores']['candidate']['n'];events=g['scores']['candidate']['events']
   cn,ce=cache[cal].get(key,(0,0));pindustry=g['scores']['baseline']['predicted_pct']/100
   plain=ce/cn if cn else pindustry;shrunk=(ce+500*pindustry)/(cn+500)
   # Both baselines use calibration-period outcomes only, never evaluation outcomes.
   scores={'industry_mean':g['scores']['baseline'],'regional_mean':constant_scores(n,events,plain),'regional_shrink500':constant_scores(n,events,shrunk),'candidate':g['scores']['candidate']}
   check=constant_scores(n,events,pindustry)
   for metric in ['brier','log_loss']:assert abs(check[metric]-scores['industry_mean'][metric])<1e-10
   wins={base:all(scores['candidate'][m]<scores[base][m] for m in ['brier','log_loss']) for base in ['industry_mean','regional_mean','regional_shrink500']}
   item={'industry':key[0],'gu':key[1],'cal_n':cn,'small_sample':n<200 or events<20,'scores':scores,'wins':wins};regions.append(item)
   history[key].append({'landmark':w['landmark'],'small_sample':item['small_sample'],'win':wins['regional_shrink500'],'mean_gap_pp':scores['candidate']['predicted_pct']-scores['candidate']['actual_pct'],'n':n})
  total=w['scores']['candidate']['n'];overall={}
  for model in ['industry_mean','regional_mean','regional_shrink500','candidate']:
   overall[model]={'n':total,'events':sum(g['scores'][model]['events'] for g in regions),**{metric:sum(g['scores'][model][metric]*g['scores'][model]['n'] for g in regions)/total for metric in ['actual_pct','predicted_pct','brier','log_loss']}}
  for metric in ['brier','log_loss']:assert abs(overall['candidate'][metric]-w['scores']['candidate'][metric])<1e-12
  windows.append({'landmark':w['landmark'],'scores':overall,'regions':regions})
 stability=[]
 for (industry,gu),hist in sorted(history.items()):
  sufficient=[x for x in hist if not x['small_sample']]
  recent=[x for x in hist if x['landmark']>='2023-01-01'];recent_ok=[x for x in recent if not x['small_sample']]
  stability.append({'industry':industry,'gu':gu,'observed_quarters':len(hist),'sufficient_quarters':len(sufficient),'wins_vs_shrunk':sum(x['win'] for x in sufficient),'recent_expected_quarters':12,'recent_observed':len(recent),'recent_sufficient':len(recent_ok),'recent_wins':sum(x['win'] for x in recent_ok),'recent_max_abs_gap_pp':max([abs(x['mean_gap_pp']) for x in recent_ok],default=None),'history':hist})
 out={'primary_comparator':'regional_shrink500','scope':'Same 96 windows and same fixed candidate; no refit. Plain regional mean is secondary sensitivity comparator.','pseudocount':500,'windows':windows,'stability':stability,'hashes':{'input':snapshot_sha256(source),'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__))},'limitations':['Post-hoc stronger baseline comparison.','Recent2023-2025 is a separate operational recency summary; earlier periods remain reported.','Overlapping followups/repeated permits; improvement counts are not independent trials.','No subgroup selected for deployment based on this report.']}
 (OUT/'strong_baselines_stability.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 地域基準線比較'.replace('地域基準線比較','地域基準線比較')]
 lines=['# 地域別過去平均比較'.replace('地域別過去平均比較','업종·지역별 과거 평균과 모델 비교'),'','주 비교는 보정연도 업종·지역 신고율을 업종 평균으로 축소한 기준선(가상표본500)입니다. 단순 지역평균도 함께 제시합니다. 미관측 지역은 원 실험의 업종 기준선을 사용합니다. 모델·평가표본은 변경하지 않았습니다.','','|기간|분기 수|업종평균 대비 개선|단순 지역평균 대비 개선|축소 지역평균 대비 개선|','|---|---:|---:|---:|---:|']
 summaries=[]
 for label,start,end in [('전체','2002-01-01','2025-10-01'),('기존 최근 범위','2013-01-01','2025-10-01'),('최근3년','2023-01-01','2025-10-01')]:
  selected=[w for w in windows if start<=w['landmark']<=end]
  wins={name:sum(all(w['scores']['candidate'][m]<w['scores'][name][m] for m in ['brier','log_loss']) for w in selected) for name in ['industry_mean','regional_mean','regional_shrink500']}
  summaries.append({'scope':label,'quarters':len(selected),'wins':wins})
  lines.append(f"|{label}|{len(selected)}|{wins['industry_mean']}|{wins['regional_mean']}|{wins['regional_shrink500']}|")
 lines+=['','## 최근3년 지역별 안정성','','|업종·지역|충분표본 분기/12|축소 지역평균 대비 두 오차 개선 분기|최대 평균오차(%p)|','|---|---:|---:|---:|']
 for s in stability:
  if not s['recent_sufficient']:continue
  lines.append(f"|{s['industry']} · {s['gu']}|{s['recent_sufficient']}|{s['recent_wins']}|{s['recent_max_abs_gap_pp']:.2f}|")
 lines+=['','충분표본 n≥200·신고≥20은 기존 점검 기준입니다. 최근3년12분기 결과를 사후 확인한 것이므로, 조건이 좋아 보이는 지역만 선택해 서비스 성능이 검증됐다고 주장하지 않습니다. 과거지역/신고완전성/기간중첩 한계가 남습니다.']
 (OUT/'strong_baselines_stability.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps(summaries,ensure_ascii=False))
 print('RECENT_COMPLETE',sum(s['recent_sufficient']==12 for s in stability),'RECENT_ALL_WINS',sum(s['recent_sufficient']==12 and s['recent_wins']==12 for s in stability))
 print('JAN2025',next(w['scores'] for w in windows if w['landmark']=='2025-01-01'))
 print('OCT2025',windows[-1]['scores'])
if __name__=='__main__':main()
