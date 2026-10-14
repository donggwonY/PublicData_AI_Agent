"""Compare cafe records around the three available Dongdaegu exits."""
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash
import json
from pathlib import Path
import numpy as np
import pandas as pd
from join_a01_poi import distances

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/a01'


def main():
    fixture = json.loads((OUT / 'consultation_case.json').read_text(encoding='utf-8'))
    paths = [OUT / 'station_locations.json', ROOT / 'service/data/processed/poi.parquet']
    hashes = {p.name: snapshot_sha256(p) for p in paths}
    for p in paths:
        verify_snapshot_hash(p, fixture['input_hashes'][p.name])
    locations = json.loads(paths[0].read_text(encoding='utf-8'))
    points = next(g['points'] for g in locations['station_exit_groups'] if g['traffic_station'] == '동대구역')
    cafes = pd.read_parquet(paths[1]).query('cat_s == "카페"')
    unique = ~cafes.duplicated().to_numpy()
    d = np.column_stack([distances(cafes.lat.to_numpy(), cafes.lon.to_numpy(), p['latitude'], p['longitude']) for p in points])
    nearest = d.argmin(axis=1)
    ordered = np.sort(d, axis=1)
    ties = np.isclose(ordered[:, 0], ordered[:, 1], rtol=0, atol=1e-6)
    gap = ordered[:, 1] - ordered[:, 0]
    results = []
    for radius in (300, 500):
        inside = d.min(axis=1) <= radius
        ref = next(x for x in fixture['counts'] if x['radius_m'] == radius)
        assert int(inside.sum()) == ref['cafe_rows']
        assert int((inside & unique).sum()) == ref['cafe_rows_exact_deduplicated']
        rows = []
        for i, p in enumerate(points):
            assigned = inside & (nearest == i) & ~ties
            rows.append({'exit': p['exit'], 'buffer_count': int((d[:, i] <= radius).sum()),
                         'buffer_deduplicated': int(((d[:, i] <= radius) & unique).sum()),
                         'nearest_count': int(assigned.sum()), 'nearest_deduplicated': int((assigned & unique).sum()),
                         'nearest_gap_at_most_10m': int((assigned & (gap <= 10)).sum())})
        assert sum(x['nearest_count'] for x in rows) + int((inside & ties).sum()) == int(inside.sum())
        results.append({'radius_m': radius, 'union_count': int(inside.sum()), 'union_deduplicated': int((inside & unique).sum()),
                        'exact_ties': int((inside & ties).sum()), 'multiple_exit_buffers': int(((d <= radius).sum(axis=1) > 1).sum()), 'exits': rows})
    report = {'station': '동대구역', 'input_hashes': hashes, 'exit_points': points, 'results': results,
              'definition': 'cat_s exact 카페; spherical straight-line distance; nearest allocation within union; exact ties excluded and reported separately',
              'limitations': ['보유 공식 자료의 1·2·3번 출구만 비교', '출구 자료 2024-08-26, 상가 설정 기준 202606; 현재 영업 확인 아님',
                              '동일행 제거는 고유 점포 확인이 아님', '최근접 출구는 실제 보행 동선·출입구·고객 유입을 뜻하지 않음',
                              '거리 차이 10m 이하는 임의의 민감도 지표이며 좌표 정확도 보증이 아님']}
    (OUT / 'dongdaegu_exit_cafes.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 동대구역 카페는 어느 출구 쪽에 많은가', '', '각 카페 기록을 가장 가까운 출구에 한 번만 배정해 비교한다. 출구별 반경 집계는 서로 겹치므로 합산하지 않는다.', '']
    for r in results:
        lines += [f"## {r['radius_m']}m", '', '| 출구 | 해당 출구 반경 내 | 최근접 배정 | 동일행 제거 후 최근접 배정 | 배정 거리 차이 ≤10m |', '| --- | ---: | ---: | ---: | ---: |']
        for x in r['exits']:
            lines.append(f"| {x['exit']}번 | {x['buffer_count']} | {x['nearest_count']} | {x['nearest_deduplicated']} | {x['nearest_gap_at_most_10m']} |")
        lines += ['', f"합집합 {r['union_count']}건, 동일행 제거 {r['union_deduplicated']}건. 여러 출구 반경에 속하는 기록 {r['multiple_exit_buffers']}건. 정확한 최근접 동률 {r['exact_ties']}건.", '']
    lines += ['## 해석 한계', ''] + ['- ' + s for s in report['limitations']]
    lines += ['', '출처: [공식 1호선 출구 자료](https://www.data.go.kr/data/15133918/fileData.do). 기존 [상담 사례](consultation_case.md)와 원본 해시 및 합집합 수치를 검증했다.', '', '재현: `.venv/Scripts/python.exe scripts/analyze_a01_dongdaegu_exits.py`', '']
    (OUT / 'dongdaegu_exit_cafes.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
