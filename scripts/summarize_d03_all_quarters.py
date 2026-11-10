"""Audit complete quarterly coverage and reproduce prior annual scores."""
import json
from pathlib import Path
from collections import Counter
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
r=json.loads((OUT/'all_quarters_evaluation.json').read_text(encoding='utf-8'))
assert r['hashes']['stores']==snapshot_sha256(ROOT/'service/data/processed/stores.parquet')
assert r['hashes']['script']==snapshot_sha256(ROOT/'scripts/evaluate_d03_all_quarters.py')
coverage=r['coverage'];results=r['results'];dates=[x['landmark'] for x in coverage]
assert len(dates)==len(set(dates))
assert dates==[str(t.date()) for t in pd.date_range(dates[0],r['reference_date'],freq='QS')]
assert [x['landmark'] for x in results]==[x['landmark'] for x in coverage if not x['skip_reasons']]
prior=json.loads((OUT/'continuous_year_evaluation.json').read_text(encoding='utf-8'))
for w in prior['windows']:
 x=next(v for v in results if v['landmark']==f"{w['test']}-01-01")
 for name,previous in [('baseline','baseline'),('raw','pooled'),('candidate','region_cal')]:
  for k in ['brier','log_loss','predicted_pct']:
   assert abs(x['scores'][name][k]-w['overall'][previous][k])<1e-10
annual=[]
for year in sorted({x['landmark'][:4] for x in results}):
 qs=[x for x in results if x['landmark'].startswith(year)]
 wins=sum(all(x['scores']['candidate'][k]<x['scores']['baseline'][k] for k in ['brier','log_loss']) for x in qs)
 ratios=[100*(x['scores']['baseline']['brier']-x['scores']['candidate']['brier'])/x['scores']['baseline']['brier'] for x in qs]
 annual.append({'year':int(year),'quarters':len(qs),'both_improved':wins,'brier_gain_min':min(ratios),'brier_gain_max':max(ratios)})
lines=['# 전체 기간의 분기별 범위 점검 및 평가','','1960~2026의 모든 분기 시작일을 점검하고, 동일한 학습·보정 최소조건을 충족하는 시점만 평가했습니다. 이전2013년 시작은 자료 한계가 아닌 실험 일정이었으며 이번 점검으로 대체합니다.']
lines+=[f"\n총 {len(coverage)}개 분기 시작일 점검, {len(results)}개 분기 평가. 평가 범위 {results[0]['landmark']}~{results[-1]['landmark']}. 제외된 시점과 학습/보정/평가 표본은 all_quarters_coverage.csv에 모두 보존했습니다.",'','학습은 평가연도보다4년 전1월1일, 보정은2년 전1월1일입니다. 최소조건은 학습·보정 각각 표본200/양성20/음성20 이상. 이는 계산상 점검 기준이며 기록 완전성이나 서비스 허용 기준이 아닙니다. 모든 시점에서 적격 인허가 전체를 사용했습니다.','','|평가연도|평가분기|두 오차 개선분기|Brier 상대개선 최저%|최고%|','|---|---:|---:|---:|---:|']
for a in annual:lines.append(f"|{a['year']}|{a['quarters']}|{a['both_improved']}|{a['brier_gain_min']:.2f}|{a['brier_gain_max']:.2f}|")
lines+=['','13개 기존 연초 평가의 점수 재현, 전체 분기 누락/중복 및 제외 사유 일치 검증 통과. 분기별 결과가 좋지 않아도 숨기거나 제외하지 않았습니다.','','과거 폐업 신고가 매우 적은 시기의 표본 완전성은 확인되지 않았습니다. 초기 구간은 탐색적 스트레스 점검으로 해석해야 하며, 성능 수치만으로 운영 범위를 확정할 수 없습니다. 현재 주소·최신 스냅샷·겹치는365일 추적·같은 인허가 반복 한계가 있습니다. 각 분기를 독립 검증으로 세거나 표본을 고유 점포 수로 합산하지 않습니다. 모델 재튜닝·공개 앱 연결·푸시 없음.']
(OUT/'all_quarters_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'all_quarters_review.json').write_text(json.dumps({'quarter_starts':len(coverage),'evaluated':len(results),'annual':annual,'skip_counts':dict(Counter(s for x in coverage for s in x['skip_reasons'])),'source_hash':snapshot_sha256(OUT/'all_quarters_evaluation.json')},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(annual,ensure_ascii=False));print('Coverage',len(coverage),'evaluated',len(results),'wins',sum(x['both_improved'] for x in annual));print('All checks passed.')
