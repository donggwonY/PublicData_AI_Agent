"""Exploratory official-exit/POI joins at 300m and 500m, without service edits."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/a01'
TRANSFERS = {'반월당1':'반월당','반월당2':'반월당','명덕1':'명덕','명덕3':'명덕','청라언덕2':'청라언덕','청라언덕3':'청라언덕'}
OUTSIDE = {'정평','임당','영남대'}


def distances(lat, lon, a, b):
    p, q = np.radians(lat), np.radians(a)
    h = np.sin((p-q)/2)**2 + np.cos(p)*np.cos(q)*np.sin(np.radians(lon-b)/2)**2
    return 6371008.8 * 2 * np.arcsin(np.sqrt(np.clip(h,0,1)))


def main():
    locations = json.loads((OUT/'station_locations.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    paths = [ROOT/'service/data/processed'/n for n in ('poi.parquet','station_traffic.parquet')]
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert all(hashes[n]==manifest['sha256'][n] for n in hashes), 'Source snapshot changed'
    poi = pd.read_parquet(paths[0])
    traffic = pd.read_parquet(paths[1]).set_index('station')
    assert poi[['lat','lon']].notna().all().all()
    assert poi.lat.between(-90,90).all() and poi.lon.between(-180,180).all()
    unique = ~poi.duplicated(keep='first').to_numpy()
    grouped = {}
    for g in locations['station_exit_groups']:
        if not g['traffic_match'] or g['review_cluster']:
            continue
        name = TRANSFERS.get(g['traffic_station'],g['traffic_station'])
        target = grouped.setdefault(name, {'members':[], 'points':[]})
        target['members'].append(g['traffic_station'])
        target['points'].extend(g['points'])
    lat,lon=poi.lat.to_numpy(),poi.lon.to_numpy()
    results=[]
    counters={r:np.zeros(len(poi),dtype=np.int16) for r in (300,500)}
    for station,g in sorted(grouped.items()):
        nearest=np.full(len(poi),np.inf)
        for p in g['points']:
            nearest=np.minimum(nearest,distances(lat,lon,p['latitude'],p['longitude']))
        t=traffic.loc[g['members']]
        for radius in (300,500):
            mask=nearest<=radius
            rows=poi.loc[mask]
            if station not in OUTSIDE:
                counters[radius]+=mask
            category=rows['cat_s'].fillna('(missing)').value_counts().sort_index().to_dict()
            counts={str(k):int(v) for k,v in category.items()}
            assert sum(counts.values())==int(mask.sum())
            results.append({'station':station,'traffic_members':g['members'],'radius_m':radius,
                            'exit_points':len(g['points']),'poi_rows':int(mask.sum()),
                            'poi_rows_exact_deduplicated':int((mask & unique).sum()),
                            'food_rows':int((rows.cat_l=='음식').sum()),'category_counts':counts,
                            'category_counts_exact_deduplicated':{str(k):int(v) for k,v in poi.loc[mask & unique,'cat_s'].fillna('(missing)').value_counts().items()},
                            'gu_counts':{str(k):int(v) for k,v in rows.gu.fillna('(missing)').value_counts().items()},
                            'daily_boarding_alighting_sum':float(t.daily_total.sum()),
                            'period_as_stored':t.period.unique().tolist(),
                            'transfer_group':len(g['members'])>1,
                            'coverage_status':'exclude_outside_daegu' if station in OUTSIDE else ('border_review' if station=='사월' else 'exploratory_boundary_not_verified'),
                            'overlap_other_stations_not_independent':True})
    for station in grouped:
        a,b=[r for r in results if r['station']==station]
        assert a['radius_m']==300 and b['radius_m']==500 and a['poi_rows']<=b['poi_rows']
    overlap={str(r):{'poi_in_any_in_scope_station':int((v>0).sum()),
                     'poi_in_multiple_in_scope_stations':int((v>1).sum()),
                     'total_station_poi_memberships':int(v.sum())} for r,v in counters.items()}
    report={'checked_date':'2026-10-12','primary_radius_m':300,'sensitivity_radius_m':500,
            'method':'minimum spherical distance to any official exit, union within physical station; transfer lines grouped',
            'coordinate_assumption':'source lat/lon interpreted as decimal degrees; datum not explicitly verified, exploratory only',
            'poi_rows':len(poi),'poi_exact_duplicate_excess':int((~unique).sum()),
            'station_groups':len(grouped),'outside_daegu_excluded':sorted(OUTSIDE),
            'missing_exit_stations':locations['no_usable_exit_station'],
            'input_hashes':{**hashes,'station_locations.json':hashlib.sha256((OUT/'station_locations.json').read_bytes()).hexdigest()},
            'category_definition_status':'student selected all POI rows denominator; cafe and specified quick-food categories; hypothesis report separate',
            'overlap':overlap,'station_results':results}
    (OUT/'poi_join.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# A-01 출구 300m 상가 결합 점검','','학생 선택: 300m를 기준으로, 500m를 민감도 비교에 사용한다. 도보거리가 아닌 출구와 상가 간 구면 직선거리 근사다.','',
           f'- 상가 원본 {len(poi):,}행, 전체 컬럼 동일 중복 초과 {(~unique).sum():,}행. 원천 점포 ID가 없어 본 집계는 행 수로 표시하고 전체 동일 행 제거 결과를 병기한다.',
           f'- 환승역 호선을 묶어 {len(grouped)}개 역 묶음으로 집계. 정평·임당·영남대는 대구 한정 POI 범위 밖이라 분석 제외 표시.',
           '- 같은 역 여러 출구의 범위에 들어와도 같은 POI 행은 한 번만 집계. 역 사이 중복은 유지·계량하며 독립 표본으로 단정하지 않는다.',
           '- 출구가 없는/이름 미확인 4항목은 0으로 넣지 않았다. 사월 등 경계 지역의 범위 완전성은 추가 확인 대상.',
           '- 입력 해시, 분류별 합계와 총계, 300m⊆500m 검증 통과. 좌표계 datum·승하차 원천 관측연도·시점 정합성은 미확인.', '',
           '## 역 사이 상권 겹침','','| 반경 | 한 역 이상 포함된 POI 행 | 여러 역에 포함된 POI 행 |','| --- | ---: | ---: |']
    for radius,o in overlap.items():
        lines.append(f"| {radius}m | {o['poi_in_any_in_scope_station']:,} | {o['poi_in_multiple_in_scope_stations']:,} |")
    lines += ['', '## 승하차 상위 역의 결합 예시', '', '| 역 묶음 | 300m 상가 행 | 500m 상가 행 | 300m 동일행 제거 후 |', '| --- | ---: | ---: | ---: |']
    top=sorted([r for r in results if r['radius_m']==300 and r['station'] not in OUTSIDE],key=lambda r:r['daily_boarding_alighting_sum'],reverse=True)[:8]
    for row in top:
        other=next(r for r in results if r['station']==row['station'] and r['radius_m']==500)
        lines.append(f"| {row['station']} | {row['poi_rows']:,} | {other['poi_rows']:,} | {row['poi_rows_exact_deduplicated']:,} |")
    lines += ['', '학생이 전체 상가 분모를 선택했다. 카페 및 김밥/만두/분식·버거·토스트/샌드위치/샐러드·빵/도넛으로 집계한다. 가설 비교는 hypothesis.md 참고.', '',
              '재현: `.venv/Scripts/python scripts/join_a01_poi.py`. 상세 집계와 SHA-256은 poi_join.json. 서비스 데이터 및 원본 좌표 변경 없음.']
    (OUT/'poi_join.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['poi_rows','poi_exact_duplicate_excess','station_groups','overlap']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
