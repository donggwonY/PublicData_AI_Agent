"""Summarize the locked continuous-year evaluation, without choosing yearly winners."""
import json
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
r=json.loads((OUT/'continuous_year_evaluation.json').read_text(encoding='utf-8'))
plan=json.loads((OUT/'continuous_year_protocol.json').read_text(encoding='utf-8'))
ws=r['windows'];assert [w['test'] for w in ws]==plan['years']
assert r['hashes']['stores']==snapshot_sha256(ROOT/'service/data/processed/stores.parquet')
assert r['hashes']['script']==snapshot_sha256(ROOT/'scripts/evaluate_d03_continuous_years.py')
rows=[]
for w in ws:
 assert w['train']==w['test']-4 and w['cal']==w['test']-2
 a=w['overall']['baseline'];b=w['overall']['region_cal']
 for model,m in w['overall'].items():
  for kind in ['groups','regions']:
   cells=[g['scores'][model] for g in w[kind]]
   assert sum(x['n'] for x in cells)==m['n']
   assert sum(x['events'] for x in cells)==m['events']
   for key in ['brier','log_loss']:assert abs(sum(x[key]*x['n'] for x in cells)/m['n']-m[key])<1e-12
 eligible=[g for g in w['regions'] if not g['small_sample']]
 row={'year':w['test'],'n':b['n'],'actual_pct':b['actual_pct'],'predicted_pct':b['predicted_pct'],'brier_relative_improvement_pct':100*(a['brier']-b['brier'])/a['brier'],'beats_baseline_both':all(b[k]<a[k] for k in ['brier','log_loss']),'beats_raw_both':all(b[k]<w['overall']['pooled'][k] for k in ['brier','log_loss']),'eligible_regions':len(eligible),'regions_gap_over5pp':sum(abs(x['scores']['region_cal']['predicted_pct']-x['scores']['region_cal']['actual_pct'])>5 for x in eligible)}
 rows.append(row)
industry=[]
for name in sorted({g['industry'] for w in ws for g in w['groups']}):
 eligible=[(w['test'],g) for w in ws for g in w['groups'] if g['industry']==name and not g['small_sample']]
 wins=[y for y,g in eligible if all(g['scores']['region_cal'][k]<g['scores']['baseline'][k] for k in ['brier','log_loss'])]
 industry.append({'industry':name,'eligible_years':len(eligible),'improved_years':len(wins),'eligible_year_list':[y for y,g in eligible],'improved_year_list':wins})
lines=['# 2013~2025 연속 연도 평가 요약','','고정 후보 region_cal, 학습 y-4/보정 y-2/평가 y. 13개 연도 누락 없이 확인했습니다. 각 기준일 영업 중 적격 인허가 전체를 평가했으며 연도 간 동일 기록이 반복될 수 있어 건수를 고유 점포 수로 합산하지 않습니다.','','|평가연도|인허가 수|실제 신고%|평균 예측%|기준선 대비 Brier 상대개선%|두 오차 개선|지역 큰 오차/충분표본 조합|','|---|---:|---:|---:|---:|---|---|']
for x in rows:lines.append(f"|{x['year']}|{x['n']:,}|{x['actual_pct']:.2f}|{x['predicted_pct']:.2f}|{x['brier_relative_improvement_pct']:.2f}|{'예' if x['beats_baseline_both'] else '아니오'}|{x['regions_gap_over5pp']}/{x['eligible_regions']}|")
lines+=['','충분표본은 n≥200·신고≥20, 큰 평균오차는 절대5%p 초과라는 기존 진단 기준입니다. 운영 허용 기준이나 유의성 검정이 아닙니다.','','|업종|충분표본 평가연도|기준선 대비 두 오차 개선연도|','|---|---:|---:|']
for x in industry:lines.append(f"|{x['industry']}|{x['eligible_years']}|{x['improved_years']}|")
lines+=['','2009학습/2011보정부터 시작해 최초 평가를2013으로 설정했습니다. 더 이전 기록이 사용 불가능하다는 검증 결과는 아닙니다. 2026은365일 추적 미완료라 제외했습니다. 이미 살펴본 연도 포함·최신자료로 과거 재구성·현재 구군 및 인허가 단위의 한계가 있어 실제 운영 검증과 구분합니다. 4년/2년 시차는 이번 고정 실험 정책이며 최적 운영 갱신 주기로 검증된 것은 아닙니다. 모델 교체·추가 튜닝·서비스 배포 없음.']
(OUT/'continuous_year_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'continuous_year_review.json').write_text(json.dumps({'years':rows,'industry':industry,'source_hash':snapshot_sha256(OUT/'continuous_year_evaluation.json')},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False));print('All aggregate and hash checks passed.')
