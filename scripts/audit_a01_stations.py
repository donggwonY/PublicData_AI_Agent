"""Audit official station coordinates against the preserved traffic snapshot.

Run with Python 3.12: .venv/Scripts/python scripts/audit_a01_stations.py
Raw official downloads live in ignored data/raw/a01; no service data is changed.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/a01'
OUT = ROOT / 'docs/a01'
PAGE = 'https://data.kric.go.kr/rips/M_01_01/detail.do?id=213'
DOWNLOAD = 'https://data.kric.go.kr/rips/dataset/download.file?type=filedata&id=213&operation=1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distance(a, b, c, d):
    p, q = math.radians(a), math.radians(c)
    h = math.sin((q-p)/2)**2 + math.cos(p)*math.cos(q)*math.sin(math.radians(d-b)/2)**2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(h)))


def main():
    OUT.mkdir(exist_ok=True)
    coords = pd.read_excel(RAW / 'kric213.xlsx', sheet_name='Sheet1')
    traffic_path = ROOT / 'service/data/processed/station_traffic.parquet'
    traffic = pd.read_parquet(traffic_path)
    manifest = json.loads((ROOT / 'docs/d01/manifest.json').read_text(encoding='utf-8'))
    assert digest(traffic_path) == manifest['sha256']['station_traffic.parquet'], 'Traffic snapshot changed'
    assert traffic.station.is_unique and traffic.station.notna().all()
    assert not coords[['노선명', '역명']].duplicated().any()
    assert coords[['위도', '경도']].notna().all().all()
    # Broad regional plausibility check; this does not establish the geodetic datum.
    assert coords['위도'].between(35, 37).all() and coords['경도'].between(128, 130).all()
    coords['base'] = coords['역명'].map(lambda s: re.sub(r'\([^)]*\)', '', s).strip())
    coords['key'] = coords['base']
    transfer = coords['base'].duplicated(keep=False)
    coords.loc[transfer, 'key'] = coords.loc[transfer, 'base'] + coords.loc[transfer, '노선명'].str.extract(r'(\d+)', expand=False)
    assert coords.key.is_unique
    exits = pd.concat([pd.read_csv(RAW / f'exits_line{i}.csv', encoding='cp949') for i in (1, 2, 3)], ignore_index=True)
    assert exits[['위도', '경도']].notna().all().all()
    assert exits['위도'].between(35, 37).all() and exits['경도'].between(128, 130).all()
    exit_duplicates = int(exits.duplicated(['호선', '역명', '출구번호']).sum())
    records = []
    for station in traffic.station:
        hit = coords[coords.key == station]
        if hit.empty:
            records.append({'traffic_station': station, 'match_status': 'unmatched', 'latitude': None, 'longitude': None})
            continue
        row = hit.iloc[0]
        line = int(re.search(r'\d+', row['노선명'])[0])
        ex = exits[(exits['역명'] == station) & (exits['호선'] == line)]
        ds = [distance(row['위도'], row['경도'], a, b) for a, b in zip(ex['위도'], ex['경도'])]
        records.append({'traffic_station': station, 'match_status': 'name_line_matched',
                        'source_station': row['역명'], 'line': line,
                        'latitude': float(row['위도']), 'longitude': float(row['경도']),
                        'exact_name_exit_rows': len(ex),
                        'nearest_exit_distance_m': round(min(ds), 1) if ds else None,
                        'furthest_exit_distance_m': round(max(ds), 1) if ds else None,
                        'spatial_review': ('review_distance_over_500m' if min(ds)>500 else 'exit_proximity_checked_datum_unconfirmed') if ds else 'no_exact_exit_match'})
    candidates = [
        {'traffic_station': '대공원', 'coordinate_station': '수성알파시티', 'line': 2,
         'status': 'candidate_not_applied', 'evidence': '대구시 역명 개정 추진 보도자료와 좌표 원본의 새 이름. 시행 고시 확인 필요',
         'source': 'https://news.daegu.go.kr/newshome/mtnmain.php?mtnkey=articleview&aid=264644'},
        {'traffic_station': '어린이회관', 'coordinate_station': '어린이세상', 'line': 3,
         'status': 'candidate_not_applied', 'evidence': '구 명칭 출구 좌표와 새 명칭 역 좌표의 공간 근접 여부 참고. 공식 개정 근거 확인 필요'}]
    for candidate in candidates:
        row = coords[(coords.base == candidate['coordinate_station']) & (coords['노선명'] == f"{candidate['line']}호선")].iloc[0]
        ex = exits[(exits['역명'] == candidate['traffic_station']) & (exits['호선'] == candidate['line'])]
        ds = [distance(row['위도'], row['경도'], a, b) for a, b in zip(ex['위도'], ex['경도'])]
        candidate['nearest_old_name_exit_distance_m'] = round(min(ds), 1) if ds else None
    matched = sum(r['match_status'] == 'name_line_matched' for r in records)
    spatial_flags = [{'station': r['traffic_station'], 'nearest_exit_distance_m': r['nearest_exit_distance_m']} for r in records if r.get('spatial_review') == 'review_distance_over_500m']
    report = {'checked_date': '2026-10-12', 'coordinate_page': PAGE, 'coordinate_download': DOWNLOAD,
              'portal_modified_date': '2026-02-05', 'coordinate_observation_date': None,
              'coordinate_datum': 'not explicitly confirmed; degree latitude/longitude only',
              'traffic_rows': len(traffic), 'coordinate_rows': len(coords), 'matched_rows': matched,
              'unmatched_stations': [r['traffic_station'] for r in records if r['match_status'] == 'unmatched'],
              'traffic_period_as_stored': traffic.period.unique().tolist(),
              'exit_rows': len(exits), 'duplicate_exit_keys': exit_duplicates,
              'spatial_review_threshold_m': 500, 'spatial_review_flags': spatial_flags,
              'ready_for_distance_analysis': False,
              'source_hashes': {p.name: digest(p) for p in [RAW/'kric213.xlsx', traffic_path] + [RAW/f'exits_line{i}.csv' for i in (1,2,3)]},
              'exit_sources': json.loads((RAW/'sources.json').read_text(encoding='utf-8')),
              'rename_candidates': candidates, 'station_matches': records}
    (OUT/'station_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# A-01 역 좌표 확보·결합 검증', '', '확인일: 2026-10-12. 원본은 `data/raw/a01/`에 보존(Git 제외).', '',
             f'- 공식 역 좌표 {len(coords)}행 / 승하차 {len(traffic)}행 / 이름·호선 연결 {matched}행.',
             '- 미연결: '+', '.join(report['unmatched_stations'])+'. 별칭 후보는 자동 적용하지 않음.',
             f'- 공식 출구 좌표 {len(exits)}행. 호선·역명·출구번호 중복 {exit_duplicates}건.',
             '- 환승역의 호선 구분 유지. 괄호 부역명을 제거하되 원래 이름도 보존.',
             '- 승하차 입력 해시가 D-01 manifest와 일치. 좌표 결측·범위·역 키 유일성 검사 통과.', '',
             '## 출처와 한계', '', f'- [국가철도공단 철도 데이터 포털: 대구교통공사 역위치]({PAGE}), 페이지 수정일 2026-02-05. 실제 측량일과 좌표계 datum은 미확인.',
             '- 출구 자료 기준 표기: 1·3호선 20240826, 2호선 20241014. 페이지 수정일과 구분한다.',
             '- 승하차 period는 01~07월 일평균. 설정 파일명에 20260731이 있으나 원천 관측연도는 별도 검증 필요.',
             '- POI는 대구 구군으로 필터링되어 경산·하양 등 경계 밖 역 주변 상가가 없거나 일부만 포함될 수 있음. 누락을 0개 상권으로 해석하지 않는다.',
             '- 좌표와 출구 간 거리는 경위도 구면거리 기반 점검값이며 도보거리가 아니다. 가까움만으로 역명 변경을 확정하지 않는다.',
             '- 역 대표점·출구 기준 선택, 반경, 카페/간편식 업종과 분모는 아직 미확정. 상관관계 계산은 수행하지 않음.', '',
             '## 이름 변경 확인 후보', '', '| 승하차 명칭 | 좌표 명칭 | 처리 |', '| --- | --- | --- |']
    lines += [f"| {c['traffic_station']} | {c['coordinate_station']} | 공식 개정 근거 확인 후 연결 |" for c in candidates]
    lines += ['', '## 좌표 불일치: 거리 분석 보류', '',
              '아래는 같은 호선·이름의 가장 가까운 출구와 대표좌표가 500m 넘게 떨어진 항목이다. 500m는 검토 대상을 찾기 위한 임시 기준이며 공식 오류 판정 기준이나 분석 반경이 아니다. 어느 원본이 틀렸는지는 아직 확정하지 않았다. 원본을 임의 보정하지 않는다.', '',
              '| 역 | 가장 가까운 출구까지 거리(m) |', '| --- | ---: |']
    lines += [f"| {r['station']} | {r['nearest_exit_distance_m']} |" for r in spatial_flags]
    lines += ['', '이름 연결 92건은 위치 검증 완료 92건을 의미하지 않는다. 공식 좌표계 확인과 불일치 해소 전 거리 기반 분석 입력으로 확정하지 않는다.', '', '## 재현', '', '` .venv/Scripts/python scripts/audit_a01_stations.py `', '',
              'Python 3.12, pandas 3.0.6, pyarrow 24.0.0, openpyxl 3.1.5 사용. 원본 다운로드 주소와 SHA-256 및 역별 연결 결과는 station_audit.json에 기록.', '',
              '서비스 코드·가공본은 변경하지 않았다. A-01은 진행 중이며 완료로 표시하지 않는다.']
    (OUT/'station_audit.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['traffic_rows','coordinate_rows','matched_rows','unmatched_stations','exit_rows','duplicate_exit_keys','rename_candidates']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
