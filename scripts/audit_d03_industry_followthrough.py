"""Retrospective, past-only industry screening; no production eligibility claim."""
import json
import sys
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/d03'
source=OUT/'continuous_age_result.json'
data=json.loads(source.read_text(encoding='utf-8'))
assert data['hashes']['stores']==snapshot_sha256(ROOT/'service/data/processed/stores.parquet')
strong='--age-baseline' in sys.argv
suffix='_age_baseline' if strong else ''
rows=data['results']
matched_hash=None
if strong:
 matched_path=OUT/'age_matched_baselines.json'
 matched=json.loads(matched_path.read_text(encoding='utf-8'))
 assert matched['hashes']['stores']==data['hashes']['stores']
 assert matched['hashes']['script']==snapshot_sha256(ROOT/'scripts/audit_d03_age_matched_baselines.py')
 matched_hash=snapshot_sha256(matched_path)
 lookup={r['landmark']:r for r in matched['results']}
 for r in rows:
  old={g['industry']:g['scores']['age_shrink500'] for g in lookup[r['landmark']]['groups']}
  assert set(old)=={g['industry'] for g in r['groups']}
  for g in r['groups']:
   b=old[g['industry']];a=g['scores']['candidate']
   assert (a['n'],a['events'])==(b['n'],b['events'])
   g['scores']['baseline']=b

assert len(rows)==96 and len({r['landmark'] for r in rows})==96
by_year={}
for r in rows:
 by_year.setdefault(int(r['landmark'][:4]),[]).append(r)
def eligible(g):
 s=g['scores']['candidate']
 return s['n']>=200 and s['events']>=20 and s['n']-s['events']>=20
def better(g,model):
 s=g['scores'];return all(s[model][m]<s['baseline'][m] for m in ['brier','log_loss'])
records=[];selection=[]
for year in sorted(by_year):
 history=by_year.get(year-2,[])
 if len(history)!=4:continue
 # All 365-day outcomes from year-2 have matured before Jan1 of year.
 names=set.intersection(*[{g['industry'] for g in r['groups'] if eligible(g)} for r in history])
 for model in ['raw','candidate']:
  selected=[name for name in sorted(names) if all(better(next(g for g in r['groups'] if g['industry']==name),model) for r in history)]
  selection.append(dict(year=year,history_year=year-2,model=model,industries=selected))
  for r in by_year[year]:
   for g in r['groups']:
    if g['industry'] not in selected:continue
    s=g['scores'][model];b=g['scores']['baseline']
    assert (s['n'],s['events'])==(b['n'],b['events'])
    records.append(dict(year=year,landmark=r['landmark'],industry=g['industry'],model=model,eligible=eligible(g),n=s['n'],events=s['events'],better=better(g,model),brier_gain_pct=100*(b['brier']-s['brier'])/b['brier'],auc=s['roc_auc'],mean_gap_pp=s['predicted_pct']-s['actual_pct']))
summary=[]
for start in [2004,2013,2023]:
 for model in ['raw','candidate']:
  part=[r for r in records if r['year']>=start and r['model']==model]
  valid=[r for r in part if r['eligible']]
  summary.append(dict(start=start,model=model,selected_industry_quarters=len(part),eligible=len(valid),improved=sum(r['better'] for r in valid),not_improved=sum(not r['better'] for r in valid),mean_abs_gap_pp=sum(abs(r['mean_gap_pp']) for r in valid)/len(valid) if valid else None))
result=dict(protocol={'selection':'All four quarters of year-2 improve BOTH Brier and log loss versus industry historical average; n>=200, events>=20, non-events>=20 each quarter.','evaluation':'All four quarters of year, all available 2004-2025. Raw and calibrated assessed separately, no winning model choice.','status':'Retrospective audit on previously inspected data; not untouched validation or service approval.','limitations':['Overlapping quarterly labels and repeated permits are not independent.','Baseline is industry historical mean, not stronger age-matched baseline.','Screening sample threshold is not a statistical guarantee.','Current snapshot reconstructs history; reporting delay and corrected records may differ from information available then.']},matched_baseline_hash=matched_hash,source_hash=snapshot_sha256(source),script_hash=snapshot_sha256(Path(__file__)),summary=summary,selections=selection,records=records)
(OUT/f'industry_followthrough_audit{suffix}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 과거에 개선된 업종의 이후 성능 확인','','운영기간 연속형 모델의 저장된 96분기 결과를 재집계했다. 추가 학습이나 공개 서비스 변경은 없다.','', '선택 기준: 평가연도 2년 전의 4분기 모두에서 업종 과거 평균보다 Brier·log loss가 낮고, 매 분기 200행·폐업 신고20건·비신고20건 이상인 업종. 이후 연도 4분기 전체에서 같은 기준선 대비 개선을 확인한다. 보정 전후는 따로 평가하며 유리한 것을 골라 합치지 않는다.','','|시작연도|모델|선택 업종×분기|평가 표본 기준 충족|두 오차 개선|개선 유지 안 됨|평균 절대 비율 차이(%p)|','|---|---|---:|---:|---:|---:|---:|']
for s in summary:
 lines.append(f"|{s['start']}|{s['model']}|{s['selected_industry_quarters']}|{s['eligible']}|{s['improved']}|{s['not_improved']}|{s['mean_abs_gap_pp']:.3f}|")
lines+=['','## 최근 2023–2025 업종별 확인','','|업종|선택된 분기|표본 기준 충족|개선 유지|','|---|---:|---:|---:|']
for name in sorted({r['industry'] for r in records if r['year']>=2023 and r['model']=='candidate'}):
 part=[r for r in records if r['year']>=2023 and r['model']=='candidate' and r['industry']==name]
 valid=[r for r in part if r['eligible']]
 lines.append(f"|{name}|{len(part)}|{len(valid)}|{sum(r['better'] for r in valid)}|")
lines+=['','raw는 보정 전, candidate는 보정 후다. 행 수는 고유 업종 수가 아니라 업종×분기 수이며 평균 비율 차이는 동일 가중 평균이다.','', '## 해석 범위','과거에 좋았던 업종만 선택해도 이후 개선이 보장되는지 확인하는 사후 점검이다. 비교 대상은 업종 과거 평균이며 운영기간까지 맞춘 더 강한 기준선과의 우열은 이 검사로 판단할 수 없다. 반복 관측·겹치는 추적기간 때문에 각 행을 독립 시행으로 해석하지 않는다. 이미 확인한 자료를 재사용했으므로 새 시험 결과나 서비스 적용 승인으로 사용하지 않는다. 표본 기준은 계산 안정성을 위한 기존 기준이며 통계적 충분성을 보증하지 않는다.','']
if strong:
 result['protocol']['selection']=result['protocol']['selection'].replace('industry historical average','industry-region-age shrink500 historical average')
 result['protocol']['limitations'][1]='Baseline uses industry, region and age band, shrink500; fixed settings, no tuning.'
 (OUT/f'industry_followthrough_audit{suffix}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 lines=[line.replace('업종 과거 평균','업종·지역·운영기간을 맞춘 과거 평균').replace('운영기간까지 맞춘 더 강한 기준선과의 우열은 이 검사로 판단할 수 없다.', '같은 입력 조건의 과거 평균 표와 비교했으며 축소강도500을 고정했다.') for line in lines]
(OUT/f'industry_followthrough_audit{suffix}.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
