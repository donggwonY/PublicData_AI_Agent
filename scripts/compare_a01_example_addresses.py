"""Illustrative address centers, not available properties or recommendations."""
import json
import hashlib
import numpy as np
import pandas as pd
from join_a01_poi import ROOT, OUT, distances


def main():
    source = OUT / 'dongdaegu_exit_cafes.json'
    prior = json.loads(source.read_text(encoding='utf-8'))
    path = ROOT / 'service/data/processed/poi.parquet'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == prior['input_hashes'][path.name]
    poi = pd.read_parquet(path)
    cafes = poi[poi.cat_s.eq('카페')].drop_duplicates().copy()
    points = prior['exit_points']
    d = np.column_stack([distances(cafes.lat.to_numpy(), cafes.lon.to_numpy(), p['latitude'], p['longitude']) for p in points])
    results = []
    for number in ('2', '3'):
        i = next(i for i, p in enumerate(points) if p['exit'] == number)
        candidates = cafes.assign(exit_distance=d[:, i]).loc[(d.argmin(axis=1) == i) & (d[:, i] <= 300)]
        center = candidates.sort_values(['exit_distance', 'addr', 'name']).iloc[0]
        dist = distances(cafes.lat.to_numpy(), cafes.lon.to_numpy(), center.lat, center.lon)
        near = cafes.loc[dist <= 300]
        same_address = near.addr.eq(center.addr)
        results.append({'exit': number, 'address': str(center.addr), 'reference_cafe': str(center['name']),
                        'latitude': float(center.lat), 'longitude': float(center.lon),
                        'distance_to_exit_m': round(float(center.exit_distance), 1),
                        'cafe_records_300m_deduplicated': len(near),
                        'same_address_records': int(same_address.sum()),
                        'other_address_records': int((~same_address).sum())})
        assert len(near) == int(same_address.sum()) + int((~same_address).sum())
    report = {'selection': 'For each exit 2 and 3, select the nearest cafe among records assigned to that exit; no commercial suitability selection.',
              'radius_m': 300, 'input_hashes': prior['input_hashes'], 'results': results,
              'limits': 'Existing cafe coordinates are illustrative centers, not vacant properties. Exact-row deduplication is not unique-shop verification. Straight-line distance, no access or sales inference. POI configured vintage 202606.'}
    (OUT / 'example_address_comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 2·3번 출구 쪽 예시 주소 비교', '', '실제 창업 후보 주소가 아직 없어 각 출구에 배정된 카페 중 출구와 가장 가까운 기록을 기준점으로 선정했다. 매물·공실 또는 입지 추천이 아니다.', '',
             '| 출구 | 기준 주소 | 출구까지 직선거리 | 주소 중심 300m 카페 기록 | 같은 주소 제외 |', '| --- | --- | ---: | ---: | ---: |']
    for r in results:
        lines.append(f"| {r['exit']}번 | {r['address']} | {r['distance_to_exit_m']}m | {r['cafe_records_300m_deduplicated']} | {r['other_address_records']} |")
    lines += ['', '모두 완전히 같은 행을 제거한 기록 수다. 같은 주소 제외는 건물 내 다른 카페도 제외할 수 있어 실제 경쟁 점포 수와 같지 않다. 각 반경은 겹치므로 합산하지 않는다.', '',
              '상가 설정 기준은 2026년 6월이며 현재 영업 상태를 확인한 수치가 아니다. 기준 좌표는 해당 카페 기록의 좌표로 건물 전체를 대표한다고 보장하지 않는다.', '',
              '이 결과만으로 한쪽이 더 좋은 입지라고 판단하지 않는다. 실제 후보 주소·층이 정해지면 그 자리의 인허가 이력과 주변 경쟁 기록을 확인한다. 기존 서비스 도구 실행·자리 이력 검증은 이번 비교에 포함하지 않았다.', '',
              '재현: `.venv/Scripts/python.exe scripts/compare_a01_example_addresses.py`', '']
    (OUT / 'example_address_comparison.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
