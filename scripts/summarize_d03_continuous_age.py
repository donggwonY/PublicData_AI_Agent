"""Validate same-cohort comparisons and report the fixed continuous-age experiment."""
import json
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
a=json.loads((OUT/'all_quarters_evaluation.json').read_text(encoding='utf-8'))
b=json.loads((OUT/'continuous_age_result.json').read_text(encoding='utf-8'))
assert snapshot_sha256(OUT/'all_quarters_evaluation.json')==b['hashes']['comparison']
assert snapshot_sha256(ROOT/'scripts/evaluate_d03_continuous_age.py')==b['hashes']['script']
assert len(a['results'])==len(b['results'])==96
pairs=[]
for old,new in zip(a['results'],b['results']):
 assert (old['landmark'],old['n'],old['events'])==(new['landmark'],new['n'],new['events'])
 for m in ['brier','log_loss']:
  assert abs(old['scores']['baseline'][m]-new['scores']['baseline'][m])<1e-12
 for g in new['groups']:
  h=next(z for z in old['groups'] if z['industry']==g['industry'])
  assert (g['scores']['raw']['n'],g['scores']['raw']['events'])==(h['scores']['raw']['n'],h['scores']['raw']['events'])
 pairs.append((old,new))
summary=[]
for label,start in [('all','2002'),('since2013','2013'),('recent','2023')]:
 selected=[(o,n) for o,n in pairs if o['landmark']>=start]
 for mod in ['raw','candidate']:
  better=sum(all(n['scores'][mod][m]<o['scores'][mod][m] for m in ['brier','log_loss']) for o,n in selected)
  worse=sum(all(n['scores'][mod][m]>o['scores'][mod][m] for m in ['brier','log_loss']) for o,n in selected)
  summary.append(dict(scope=label,model=mod,quarters=len(selected),better=better,worse=worse,mixed=len(selected)-better-worse))
lines=['# 운영일수의 세밀한 변화 추가 실험','','기존 업종·지역·운영기간5구간에 실제 운영일수의 고정 스플라인 변환을 추가했다. 모델과 확률 보정·시간분할은 유지했다. 전체96분기의 동일 표본·신고 건수와 단순 기준선 점수 재현을 확인했다.','','|기간|비교|분기|두 오차 개선|두 오차 악화|혼재|','|---|---|---:|---:|---:|---:|']
for s in summary:lines.append(f"|{s['scope']}|{s['model']}|{s['quarters']}|{s['better']}|{s['worse']}|{s['mixed']}|")
lines+=['','## 최신2025-10 동일 표본','','|모델|Brier|log loss|AUC|평균예측%|실제%|','|---|---:|---:|---:|---:|---:|']
for label,data in [('기존',pairs[-1][0]),('운영일수 추가',pairs[-1][1])]:
 m=data['scores']['candidate'];lines.append(f"|{label}|{m['brier']:.6f}|{m['log_loss']:.6f}|{m['roc_auc']:.4f}|{m['predicted_pct']:.3f}|{m['actual_pct']:.3f}|")
lines+=['','## 업종별 최근12분기 보정 후 비교','','|업종|평가분기|두 오차 개선|','|---|---:|---:|']
for name in sorted({g['industry'] for _,n in pairs for g in n['groups']}):
 comparisons=[]
 for o,n in pairs:
  if n['landmark']<'2023':continue
  ng=next((g for g in n['groups'] if g['industry']==name),None);og=next((g for g in o['groups'] if g['industry']==name),None)
  if ng and og:comparisons.append(all(ng['scores']['candidate'][m]<og['scores']['candidate'][m] for m in ['brier','log_loss']))
 lines.append(f"|{name}|{len(comparisons)}|{sum(comparisons)}|")
lines+=['','raw는 확률 보정 전, candidate는 같은 절차로 보정한 뒤의 비교다. 업종별 표는 작은 표본도 포함한 기술적 진단이며 충분한 예측 근거를 뜻하지 않는다. 고정된 하나의 변환을 시험했으며 최적 운영기간 표현을 찾았다고 주장하지 않는다. 기존 평가자료 재사용·분기 추적 중첩·과거 스냅샷 복원 한계가 있다. 서비스 변경 없음.']
(OUT/'continuous_age_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'continuous_age_review.json').write_text(json.dumps(dict(summary=summary,source_hash=snapshot_sha256(OUT/'continuous_age_result.json'),script_hash=snapshot_sha256(Path(__file__))),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False));print('LATEST',pairs[-1][0]['scores']['candidate'],pairs[-1][1]['scores']['candidate'])
