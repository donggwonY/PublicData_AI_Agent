"""Separate industry weighting from changing sample coverage; frozen scores only."""
import json
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03';source=OUT/'age_matched_baselines.json'
r=json.loads(source.read_text(encoding='utf-8'));ws=r['results'];summaries=[];details=[]
for label,start in [('전체','2002-01-01'),('2013년 이후','2013-01-01'),('최근3년','2023-01-01')]:
 selected=[w for w in ws if w['landmark']>=start]
 common=set.intersection(*[{g['industry'] for g in w['groups'] if not g['small_sample']} for w in selected])
 for kind in ['해당 분기 충분표본 업종','기간 공통 충분표본 업종']:
  pair=[]
  for w in selected:
   gs=[g for g in w['groups'] if (not g['small_sample'] if kind=='해당 분기 충분표본 업종' else g['industry'] in common)]
   assert gs
   modes={}
   for mode in ['점포수 가중','업종 동일가중']:
    weights=[g['scores']['candidate']['n'] if mode=='점포수 가중' else 1 for g in gs]
    deltas={m:sum(weight*(g['scores']['candidate'][m]-g['scores']['age_shrink500'][m]) for weight,g in zip(weights,gs))/sum(weights) for m in ['brier','log_loss']}
    modes[mode]={'delta':deltas,'both_improved':all(v<0 for v in deltas.values())}
   pair.append({'landmark':w['landmark'],'industries':len(gs),'n':sum(g['scores']['candidate']['n'] for g in gs),'modes':modes})
  summaries.append({'scope':label,'selection':kind,'quarters':len(pair),'industry_min':min(p['industries'] for p in pair),'industry_max':max(p['industries'] for p in pair),'weighted_wins':sum(p['modes']['점포수 가중']['both_improved'] for p in pair),'equal_wins':sum(p['modes']['업종 동일가중']['both_improved'] for p in pair),'same_period_common_industries':sorted(common) if kind=='기간 공통 충분표본 업종' else None})
  details.append({'scope':label,'selection':kind,'quarters':pair})
out={'comparison':'fixed candidate versus age_shrink500','summary':summaries,'details':details,'input_hash':snapshot_sha256(source),'script_hash':snapshot_sha256(Path(__file__)),'limitations':['Post-hoc descriptive sensitivity; no significance test or causal attribution.','Sufficient sample n>=200 and events>=20; common-industry intersection uses evaluation labels, not deployable eligibility.','Identical selected cohorts for weighted/equal comparison, but differs from full-sample score.','Overlapping horizons and repeated permits; no independent-trial claims or model change.']}
(OUT/'industry_weighting_audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
lines=['# 업종 비중과 평가 구성의 영향','','비교 대상은 업종·지역·운영기간 축소평균500입니다. 가중 방식의 효과와 업종 구성 차이를 혼동하지 않도록 동일한 업종·표본에서 점포수 가중과 업종 동일가중을 비교했습니다.','','|기간|대상 선정|업종 수|평가분기|점포수 가중 개선|업종 동일가중 개선|','|---|---|---:|---:|---:|---:|']
for s in summaries:lines.append(f"|{s['scope']}|{s['selection']}|{s['industry_min']}~{s['industry_max']}|{s['quarters']}|{s['weighted_wins']}|{s['equal_wins']}|")
lines+=['','개선은 모델의 Brier·log loss 모두 기준선보다 작은 경우입니다. 충분표본 기준은 n≥200·신고≥20이며 평가 자료에 기반한 사후 분석 범위입니다. 공통 업종은 해당 기간 전체에서 이 조건을 충족한 교집합으로, 서비스 허용 목록으로 사용하지 않습니다.','','전체 업종별 건수 가중 점수에서 개선됐더라도 모든 업종에 균등한 개선이 있다는 뜻은 아닙니다. 반대로 동일가중 결과가 일부 나빠졌다는 사실만으로 전체 모델이 무효라고 해석하지 않습니다. 평가 대상과 가중 방식에 따라 서로 다른 질문에 답하는 지표입니다. 모델 변경·재학습·서비스 반영 없음.']
(OUT/'industry_weighting_audit.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps([{k:v for k,v in s.items() if k!='same_period_common_industries'} for s in summaries],ensure_ascii=False))
