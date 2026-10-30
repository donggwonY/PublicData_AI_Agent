"""Compare service expansion at a fixed snapshot; preserve all source tables."""
import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/d04'
OLD = {'일반음식점', '휴게음식점', '제과점영업', '미용업', '세탁업', '노래연습장업', '담배소매업'}

def main():
    prior = json.loads((OUT / 'links.json').read_text(encoding='utf-8'))
    baseline_path = ROOT / 'docs/d01/join_audit.json'
    manifest_path = ROOT / 'docs/d01/manifest.json'
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    paths = {n: ROOT / 'service/data/processed' / f'{n}.parquet' for n in prior['hashes']}
    for n, p in paths.items():
        verify_snapshot_hash(p, prior['hashes'][n])
    s, m, a = [pd.read_parquet(paths[n]) for n in ['stores', 'legal_admin_map', 'area_context']]
    assert not s.duplicated(['service', 'org_code', 'mgmt_no']).any()
    j = s.merge(m[['gu', 'legal_dong', 'admin_dong']], left_on=['gu', 'dong'], right_on=['gu', 'legal_dong'], how='left', validate='many_to_one')
    j = j.merge(a[['gu', 'admin_dong']].assign(context_exists=True), on=['gu', 'admin_dong'], how='left', validate='many_to_one')
    assert len(j) == len(s) == prior['n']
    j['failed'] = j.context_exists.isna()
    j['group'] = j.service.map(lambda x: '기존 7업종' if x in OLD else '추가 8분석업종')
    j['analysis_service'] = j.service.replace({'의원': '의원+병원', '병원': '의원+병원'})
    assert set(j.loc[j.group.eq('기존 7업종'), 'service']) == OLD
    assert j.analysis_service.nunique() == 15
    groups = []
    for name, g in j.groupby('group'):
        groups.append({'group': name, 'n': len(g), 'failed': int(g.failed.sum()), 'failed_pct': float(g.failed.mean()*100)})
    by_service = [{'group': name, 'service': service, 'n': len(g), 'failed': int(g.failed.sum()), 'failed_pct': float(g.failed.mean()*100)} for (name, service), g in j.groupby(['group', 'analysis_service'])]
    old = next(x for x in groups if x['group'] == '기존 7업종')
    new = next(x for x in groups if x['group'] == '추가 8분석업종')
    hist = next(x for x in baseline['checks'] if x['join'] == 'stores → mapping → area_context')
    total_failed = int(j.failed.sum())
    assert sum(x['n'] for x in groups) == len(s)
    assert sum(x['failed'] for x in groups) == total_failed == prior['failed']
    assert sum(x['failed'] for x in by_service) == total_failed
    old_rate = hist['unmatched']/hist['denominator']*100
    current_rate = total_failed/len(s)*100
    bridge = {'historic_n': hist['denominator'], 'historic_failed': hist['unmatched'], 'historic_failed_pct': old_rate,
              'existing_services_row_change': old['n']-hist['denominator'],
              'existing_services_failure_net_change': old['failed']-hist['unmatched'],
              'added_services_rows': new['n'], 'added_services_failures': new['failed'],
              'total_failure_change': total_failed-hist['unmatched'],
              'existing_snapshot_rate_change_pp': old['failed_pct']-old_rate,
              'expansion_rate_change_pp': current_rate-old['failed_pct'], 'total_rate_change_pp': current_rate-old_rate}
    assert bridge['existing_services_failure_net_change'] + new['failed'] == bridge['total_failure_change']
    assert bridge['existing_services_row_change'] + new['n'] == len(s)-hist['denominator']
    assert abs(bridge['existing_snapshot_rate_change_pp']+bridge['expansion_rate_change_pp']-bridge['total_rate_change_pp']) < 1e-10
    mapping_same = {n: prior['hashes'][n] == manifest['sha256'][n+'.parquet'] for n in ['legal_admin_map','area_context']}
    result = {'historical_reference_date': baseline['snapshot_reference_date'], 'current_reference_date': json.loads((paths['stores'].parent/'meta.json').read_text(encoding='utf-8'))['reference_date'], 'groups': groups, 'by_service': by_service, 'bridge': bridge, 'historical_mapping_hash_matches': mapping_same, 'limitations': ['Historical aggregate comparison, not a record-level transition audit.', 'Existing-service net change mixes additions, removals and field changes; not attributable to time alone.', 'Review-only address candidates are not applied.'], 'hashes': prior['hashes'], 'baseline_hash': snapshot_sha256(baseline_path), 'manifest_hash': snapshot_sha256(manifest_path), 'script_hash': snapshot_sha256(Path(__file__))}
    (OUT/'service_expansion.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# 7업종과 15업종 연결 실패 비교', '', '현재 가공본을 같은 연결 규칙으로 나눠 비교했다. 의원·병원을 합쳐 원천 16업종을 분석 15업종으로 계산한다. 검토용 주소 보정 후보는 적용하지 않았다.', '', '| 구분 | 전체 건수 | 미연결 | 미연결률 |', '| --- | ---: | ---: | ---: |', f"| 과거 7업종 ({result['historical_reference_date']}) | {hist['denominator']:,} | {hist['unmatched']:,} | {old_rate:.4f}% |"]
    for x in groups:
        lines.append(f"| 현재 {x['group']} | {x['n']:,} | {x['failed']:,} | {x['failed_pct']:.4f}% |")
    lines += [f'| 현재 전체 15업종 | {len(s):,} | {total_failed:,} | {current_rate:.4f}% |', '', f"현재 기준일: {result['current_reference_date']}.", '', '## 증가분 해석', '', f"과거 대비 미연결 증가 {bridge['total_failure_change']:,}건 = 기존 7업종의 순증 {bridge['existing_services_failure_net_change']:,}건 + 추가 업종의 미연결 {new['failed']:,}건이다. 기존 업종의 행수도 {bridge['existing_services_row_change']:,}건 달라졌으므로 기존 표본이 그대로라고 가정하지 않는다.", '', f"비율의 순차 비교: 기존 업종 자료 변화 {bridge['existing_snapshot_rate_change_pp']:.4f}%p + 업종 확장 {bridge['expansion_rate_change_pp']:.4f}%p = 전체 변화 {bridge['total_rate_change_pp']:.4f}%p. 업종 확장 효과는 현재 7업종을 기준으로 8분석업종을 더한 산술 차이이며 인과효과 추정이 아니다.", '', f'과거 manifest와 현재 연결표·맥락표의 바이트 해시 일치: {mapping_same}. 이 표 자체의 버전 변화와 인허가 자료의 변화는 구분한다. 과거 원본 행과 현재 행을 직접 대조하지 않았으므로 순증을 신규 실패 행수나 시간 경과만의 효과로 해석할 수 없다.', '', '## 현재 업종별 내역', '', '| 구분 | 업종 | 전체 | 미연결 | 미연결률 |', '| --- | --- | ---: | ---: | ---: |']
    for x in by_service:
        lines.append(f"| {x['group']} | {x['service']} | {x['n']:,} | {x['failed']:,} | {x['failed_pct']:.4f}% |")
    lines += ['', '검증: 입력 해시, 복합 인허가 키, 다대일 연결, 행수 보존, 업종·그룹 합계, 증가 건수·비율 분해 일치. 운영 데이터·Supabase 수정 없음.', '', '재현: `python scripts/audit_d04_service_expansion.py`. [전체 결과](service_expansion.json).']
    (OUT/'service_expansion.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'groups':groups,'bridge':bridge,'mapping_hash_matches':mapping_same},ensure_ascii=False))

if __name__ == '__main__':
    main()
