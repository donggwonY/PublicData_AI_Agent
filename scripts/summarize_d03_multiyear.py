"""Paired evaluation of fixed multi-year training variants; no winner cherry-picking."""
import json
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
base=json.loads((OUT/'continuous_age_result.json').read_text(encoding='utf-8'))
variants={v:json.loads((OUT/f'multiyear_{v}_result.json').read_text(encoding='utf-8')) for v in ['uniform','recent']}
for v,r in variants.items():
 assert r['hashes']['stores']==base['hashes']['stores']
 assert r['hashes']['comparison']==snapshot_sha256(OUT/'continuous_age_result.json')
 assert r['hashes']['script']==snapshot_sha256(ROOT/'scripts/evaluate_d03_multiyear.py')
 assert r['hashes']['protocol']==snapshot_sha256(OUT/'multiyear_protocol.json')
 assert len(r['results'])==len(base['results'])==96
 for o,n in zip(base['results'],r['results']):
  assert (o['landmark'],o['n'],o['events'])==(n['landmark'],n['n'],n['events'])
  assert abs(n['weight_sum']-n['latest_train_n'])<1e-7
  assert len(o['groups'])==len(n['groups'])
  for g,h in zip(o['groups'],n['groups']):
   assert (g['industry'],g['scores']['raw']['n'],g['scores']['raw']['events'])==(h['industry'],h['scores']['raw']['n'],h['scores']['raw']['events'])
summary=[]
for v,r in variants.items():
 for label,start in [('all','2002'),('since2013','2013'),('recent','2023')]:
  pairs=[(o,n) for o,n in zip(base['results'],r['results']) if o['landmark']>=start]
  for mod in ['raw','candidate']:
   better=sum(all(n['scores'][mod][m]<o['scores'][mod][m] for m in ['brier','log_loss']) for o,n in pairs)
   worse=sum(all(n['scores'][mod][m]>o['scores'][mod][m] for m in ['brier','log_loss']) for o,n in pairs)
   summary.append(dict(variant=v,scope=label,model=mod,quarters=len(pairs),better=better,worse=worse,mixed=len(pairs)-better-worse))
lines=['# 과거3년 학습과 최근 자료 가중 비교','','같은 운영일수 모델에서 학습 시점만 최근1개 연초에서3개 연초로 확장했다. uniform은 동일가중, recent는 오래된 순서로0.25·0.5·1을 적용한다. 두 방법 모두 총 가중치를 기존 최신 학습표본 수와 맞춰 C1 정규화 조건을 비교 가능하게 유지한다. 보정 시점과 절차는 동일하다.','','|방법|기간|비교|분기|두 오차 개선|두 오차 악화|혼재|','|---|---|---|---:|---:|---:|---:|']
for s in summary:lines.append(f"|{s['variant']}|{s['scope']}|{s['model']}|{s['quarters']}|{s['better']}|{s['worse']}|{s['mixed']}|")
lines+=['','## 최신2025-10 동일 평가행','','|모델|Brier|log loss|AUC|평균예측%|실제%|','|---|---:|---:|---:|---:|---:|']
for label,r in [('single_year',base),*variants.items()]:
 s=r['results'][-1]['scores']['candidate'];lines.append(f"|{label}|{s['brier']:.6f}|{s['log_loss']:.6f}|{s['roc_auc']:.4f}|{s['predicted_pct']:.3f}|{s['actual_pct']:.3f}|")
lines+=['','## 최근12분기 업종별 보정 후 개선 횟수','','|업종|평가분기|동일가중 개선|최근가중 개선|','|---|---:|---:|---:|']
for name in sorted({g['industry'] for w in base['results'] for g in w['groups']}):
 counts={};nquarters=0
 for v,r in variants.items():
  comparisons=[]
  for o,n in zip(base['results'],r['results']):
   if o['landmark']<'2023':continue
   g=next((g for g in o['groups'] if g['industry']==name),None);h=next((g for g in n['groups'] if g['industry']==name),None)
   if g and h:comparisons.append(all(h['scores']['candidate'][m]<g['scores']['candidate'][m] for m in ['brier','log_loss']))
  counts[v]=sum(comparisons);nquarters=len(comparisons)
 lines.append(f"|{name}|{nquarters}|{counts['uniform']}|{counts['recent']}|")
lines+=['','평가상 주의'+': 학습의 같은 인허가가 여러 연초에 반복 포함될 수 있으며 고유 점포 수 증가가 아니다. 분기별 평가의 추적기간도 겹친다. 새 미사용 시험이 아닌 사후 실험이며, 평가기간별 유리한 방법을 골라 하나의 성능으로 보고하지 않는다. 업종별 표는 작은 표본도 포함하므로 개선 횟수만으로 서비스 대상을 정하지 않는다. 앱·DB 변경 없음.']
(OUT/'multiyear_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
(OUT/'multiyear_review.json').write_text(json.dumps({'summary':summary,'hashes':{v:snapshot_sha256(OUT/f'multiyear_{v}_result.json') for v in variants},'script_hash':snapshot_sha256(Path(__file__))},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
for label,r in [('single_year',base),*variants.items()]:print(label,r['results'][-1]['scores']['candidate'])
