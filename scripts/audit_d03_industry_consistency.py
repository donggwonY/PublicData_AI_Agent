"""Descriptive industry-level stability of frozen predictions; no model selection."""
import json
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/d03'
source=OUT/'age_matched_baselines.json'
r=json.loads(source.read_text(encoding='utf-8'))
assert snapshot_sha256(OUT/'all_quarters_evaluation.json')==r['hashes']['input']
assert snapshot_sha256(ROOT/'scripts/audit_d03_age_matched_baselines.py')==r['hashes']['script']
windows=r['results']
assert len(windows)==96 and len({w['landmark'] for w in windows})==96
industries=sorted({g['industry'] for w in windows for g in w['groups']})
records=[]
for industry in industries:
    observations=[]
    for w in windows:
        g=next((g for g in w['groups'] if g['industry']==industry),None)
        if g is None: continue
        a=g['scores']['candidate'];b=g['scores']['age_shrink500']
        assert a['n']==b['n'] and a['events']==b['events']
        observations.append(dict(landmark=w['landmark'],n=a['n'],events=a['events'],
            sufficient=not g['small_sample'],
            both_improved=a['brier']<b['brier'] and a['log_loss']<b['log_loss'],
            brier_relative_gain_pct=100*(b['brier']-a['brier'])/b['brier'] if b['brier'] else None,
            mean_error_pp=a['predicted_pct']-a['actual_pct'],auc=a['roc_auc']))
    scopes={}
    for name,start in [('all','2002'),('since2013','2013'),('recent','2023')]:
        available=[o for o in observations if o['landmark']>=start]
        valid=[o for o in available if o['sufficient']]
        january=[o for o in valid if o['landmark'].endswith('01-01')]
        scopes[name]=dict(available_quarters=len(available),sufficient_quarters=len(valid),
            wins=sum(o['both_improved'] for o in valid),january_count=len(january),
            january_wins=sum(o['both_improved'] for o in january),
            auc_at_most_half=sum(o['auc'] is not None and o['auc']<=.5 for o in valid),
            max_absolute_mean_error_pp=max((abs(o['mean_error_pp']) for o in valid),default=None))
    recent=scopes['recent']
    category=('recent_sample_incomplete' if recent['sufficient_quarters']<12 else
              'all_recent_improved' if recent['wins']==12 else
              'none_recent_improved' if recent['wins']==0 else 'mixed_recent')
    records.append(dict(industry=industry,category=category,scopes=scopes,latest=observations[-1],quarters=observations))
summary={c:sum(x['category']==c for x in records) for c in ['all_recent_improved','mixed_recent','none_recent_improved','recent_sample_incomplete']}
out=dict(source_hash=snapshot_sha256(source),script_hash=snapshot_sha256(Path(__file__)),
    comparison='fixed candidate vs industry-region-age shrink500',summary=summary,industries=records,
    limitations=['Post-hoc diagnostic, not an operational allowlist or independent holdout.',
    'Sufficiency n>=200/events>=20 uses evaluation labels; no deployment rule.',
    'Quarterly 365-day outcomes overlap; January sensitivity reduces horizon overlap but does not remove repeated-permit dependence.',
    'No significance claims, no tuning, no refitting; mean calibration and individual ranking are distinct.'])
(OUT/'industry_consistency.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
lines=['# 업종별 예측 개선의 기간별 일관성','','고정 모델을 동일 입력(업종·구군·운영기간)의 축소평균500과 비교했다. 전체96분기(2002~2025)를 사용하며 2013년 이후52분기·최근12분기를 별도로 집계한다. 개선은 Brier와 log loss 모두 낮은 경우다.','','|업종|전체 개선/충분표본 분기|2013년 이후|최근3년|최근 연초만|최근 AUC≤0.5 분기|최근 최대 평균오차(%p)|','|---|---:|---:|---:|---:|---:|---:|']
for x in records:
    a,b,c=(x['scopes'][k] for k in ['all','since2013','recent'])
    gap='—' if c['max_absolute_mean_error_pp'] is None else f"{c['max_absolute_mean_error_pp']:.2f}"
    lines.append(f"|{x['industry']}|{a['wins']}/{a['sufficient_quarters']}|{b['wins']}/{b['sufficient_quarters']}|{c['wins']}/{c['sufficient_quarters']}|{c['january_wins']}/{c['january_count']}|{c['auc_at_most_half']}|{gap}|")
lines+=['','## 해석','',f"최근12분기 모두 충분표본인 업종 중 매번 개선 {summary['all_recent_improved']}개, 기간별 혼재 {summary['mixed_recent']}개, 두 오차 동시 개선 없음 {summary['none_recent_improved']}개다. 최근12분기를 모두 충분표본으로 평가할 수 없는 업종은 {summary['recent_sample_incomplete']}개다.",'','분모는 업종별 충분표본(n≥200·신고≥20) 분기 수다. 0/0은 실패가 아니라 평가 근거 부족이며, 개선 횟수는 정확도나 성공 확률이 아니다. 최근 연초만 집계해 중첩 관찰기간에 대한 민감도도 제시했지만 반복 점포 의존성이 사라지는 것은 아니다.','','오차 개선이 반복되어도 AUC가 낮으면 개별 점포의 위험 순서를 구분하지 못할 수 있다. 평균 확률 오차와 순위 구분 능력을 함께 판단해야 한다. 평가자료를 본 후 작성한 사후 진단으로 서비스 허용 업종 선정·독립 최종 검증에 사용하지 않는다. 모델·앱·DB 변경 없음.']
(OUT/'industry_consistency.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
for x in records:
    if x['category'] in ['all_recent_improved','none_recent_improved']:
        print(x['industry'],x['category'],x['scopes']['recent'])
