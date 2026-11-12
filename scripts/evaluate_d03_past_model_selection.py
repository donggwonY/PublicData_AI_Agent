"""Past-only industry model routing, retrospective fixed-rule analysis."""
import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
source=OUT/'separate_industries.json';r=json.loads(source.read_text(encoding='utf-8'))
assert snapshot_sha256(ROOT/'scripts/compare_d03_separate_industries.py')==r['hashes']['script']
assert snapshot_sha256(OUT/'all_quarters_evaluation.json')==r['hashes']['source']
protocol={'selection':'Use all four quarterly evaluations of year y-2; all outcomes complete before Jan1 y',
 'rule':'Separate model only if all four past quarters exist, each n>=200/events>=20, and separate calibrated beats pooled calibrated on BOTH Brier/logloss in ALL four. Otherwise pooled.',
 'scope':'All saved quarters; no per-result threshold tuning; unavailable separate models fall back to pooled',
 'limitations':'Rule proposed after inspecting past project results; retrospective analysis, not pristine holdout. Not operational validation.'}
(OUT/'past_model_selection_protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
windows=r['results'];results=[]
for w in windows:
 year=int(w['landmark'][:4]);past=[z for z in windows if z['landmark'].startswith(str(year-2))]
 for z in past:assert pd.Timestamp(z['landmark'])+pd.Timedelta(days=365)<pd.Timestamp(year,1,1)
 groups=[]
 for g in w['groups']:
  prior=[q for z in past for q in z['groups'] if q['industry']==g['industry']]
  choose=len(prior)==4 and all(q['scores']['pooled_cal']['n']>=200 and q['scores']['pooled_cal']['events']>=20 and all(q['scores']['separate_cal'][m]<q['scores']['pooled_cal'][m] for m in ['brier','log_loss']) for q in prior)
  groups.append(dict(industry=g['industry'],selected='separate_cal' if choose else 'pooled_cal',scores=g['scores']))
 n=w['n'];scores={}
 if n:
  for model in ['pooled_cal','separate_cal','past_selected']:
   scores[model]={m:sum(g['scores'][g['selected'] if model=='past_selected' else model][m]*g['scores']['pooled_cal']['n'] for g in groups)/n for m in ['brier','log_loss']}
 results.append(dict(landmark=w['landmark'],selection_year=year-2,n=n,excluded_n=w['total_n']-n,selected_industries=[g['industry'] for g in groups if g['selected']=='separate_cal'],scores=scores))
summary=[]
for label,start in [('all','2002'),('since2013','2013'),('recent','2023')]:
 rows=[w for w in results if w['landmark']>=start and w['n']]
 better=sum(all(w['scores']['past_selected'][m]<w['scores']['pooled_cal'][m] for m in ['brier','log_loss']) for w in rows)
 worse=sum(all(w['scores']['past_selected'][m]>w['scores']['pooled_cal'][m] for m in ['brier','log_loss']) for w in rows)
 equal=sum(all(w['scores']['past_selected'][m]==w['scores']['pooled_cal'][m] for m in ['brier','log_loss']) for w in rows)
 summary.append(dict(scope=label,quarters=len(rows),better=better,worse=worse,equal=equal,mixed=len(rows)-better-worse-equal))
out=dict(protocol=protocol,summary=summary,results=results,source_hash=snapshot_sha256(source),script_hash=snapshot_sha256(Path(__file__)))
(OUT/'past_model_selection.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
lines=['# 과거 성적으로 업종별 모델을 선택한 결과','','2년 전의 4개 분기에서 표본 조건을 충족하고 별도 모델이 두 오차 모두 개선된 업종만 별도 모델을 사용한다. 그 외는 통합 모델을 유지한다. 선택에 사용한 365일 추적 결과는 적용 연도 시작 전에 모두 관측이 끝난다. 규칙을 결과에 맞춰 재조정하지 않았다.','','|기간|비교분기|두 오차 개선|두 오차 악화|동일|혼재|','|---|---:|---:|---:|---:|---:|']
for s in summary:lines.append(f"|{s['scope']}|{s['quarters']}|{s['better']}|{s['worse']}|{s['equal']}|{s['mixed']}|")
lines+=['','## 최근 분기 상세','','|평가시점|선택용 평가연도|별도모델 업종|통합 Brier|선택 Brier|통합 log loss|선택 log loss|','|---|---:|---|---:|---:|---:|---:|']
for w in results:
 if w['landmark']<'2023' or not w['n']:continue
 a=w['scores']['pooled_cal'];b=w['scores']['past_selected']
 lines.append(f"|{w['landmark']}|{w['selection_year']}|{', '.join(w['selected_industries']) or '없음'}|{a['brier']:.6f}|{b['brier']:.6f}|{a['log_loss']:.6f}|{b['log_loss']:.6f}|")
lines+=['','비교 표본은 별도 학습 실험과 같은 업종·같은 행이다. 제외된 업종까지 포함한 전 업종 성능으로 해석하지 않는다. 분기별 추적기간과 점포가 겹치므로 개선 횟수는 독립 성공률이 아니다.','','선택 규칙 자체는 기존 결과를 본 뒤 제안한 것이므로 시점 순서를 지켰더라도 완전 미사용 시험이 아니다. 특정 규칙의 결과이며 모든 혼합 모델의 가능성을 부정하거나 서비스 적용을 승인하는 근거가 아니다. 재학습·앱·DB 변경 없음.']
(OUT/'past_model_selection.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False));print(json.dumps(results[-1],ensure_ascii=False))
