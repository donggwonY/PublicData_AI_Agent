"""Prepare traceable official exit points; never silently repair station centers."""
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import pandas as pd
from audit_a01_stations import distance

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/a01'
OUT = ROOT / 'docs/a01'
CHILD = 'https://council.daegu.go.kr/kr/activity/question?flag=&keyword=&mem_sch=&page=6&q_tag=C532CA2D96135ECDBFF84FDA61DA5259&reform=view&search_code=&sess_sch=&th_sch=9'
ALPHA = 'https://info.daegu.go.kr/newshome/mtnmain.php?mtnkey=articleview&aid=264644'


def packed_dms(value):
    # Diagnostic only: DDD.MMSS... is not decimal degrees.
    text = format(Decimal(str(value)), 'f')
    degrees, tail = (text + '.').split('.')[:2] if '.' not in text else text.split('.')
    tail = tail.ljust(4, '0')
    minutes = int(tail[:2])
    seconds = float(tail[2:4] + '.' + (tail[4:] or '0'))
    if minutes >= 60 or seconds >= 60:
        raise ValueError('Invalid minutes or seconds')
    return int(degrees) + minutes/60 + seconds/3600


def main():
    old = json.loads((OUT/'station_audit.json').read_text(encoding='utf-8'))
    for name, sha in old['source_hashes'].items():
        path = ROOT/'service/data/processed'/name if name.endswith('.parquet') else RAW/name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, f'Input changed: {name}'
    for name, term in [('child_rename.txt','어린이회관'),('alpha_rename.txt','대공원')]:
        assert term in (RAW/name).read_text(encoding='utf-8')
    traffic = pd.read_parquet(ROOT/'service/data/processed/station_traffic.parquet')
    exits = pd.concat([pd.read_csv(RAW/f'exits_line{i}.csv',encoding='cp949') for i in (1,2,3)],ignore_index=True)
    centers = pd.read_excel(RAW/'kric213.xlsx')
    # Alias justified by the city announcement plus both current official coordinate sources.
    # This identifies the station; it does not establish the effective date of renaming.
    exit_aliases = {'수성알파시티':'대공원'}
    exits['traffic_station'] = exits['역명'].replace(exit_aliases)
    assert not exits.duplicated(['호선','역명','출구번호']).any()
    groups=[]
    for (line, name), group in exits.groupby(['호선','traffic_station'],sort=True):
        points=[{'exit':str(int(r['출구번호'])), 'latitude':float(r['위도']), 'longitude':float(r['경도'])} for _,r in group.iterrows()]
        diameter=max(distance(a['latitude'],a['longitude'],b['latitude'],b['longitude']) for a in points for b in points)
        groups.append({'traffic_station':name,'line':int(line),'source_station':group['역명'].iat[0],
                       'traffic_match':name in set(traffic.station),'exit_count':len(points),
                       'exit_cluster_diameter_m':round(diameter,1),'review_cluster':diameter>1000,
                       'points':points})
    available={r['traffic_station'] for r in groups if r['traffic_match'] and not r['review_cluster']}
    missing=sorted(set(traffic.station)-available)
    diagnoses=[]
    for name in ['현충로','율하','용산','만촌','담티']:
        center=centers[centers['역명'].str.startswith(name)].iloc[0]
        group=exits[exits['traffic_station']==name]
        record={'station':name,'original_latitude':float(center['위도']),'original_longitude':float(center['경도']),
                'action':'exclude_original_center_use_official_exit_points_for_exploration',
                'nearest_exit_original_m':round(min(distance(center['위도'],center['경도'],a,b) for a,b in zip(group['위도'],group['경도'])),1)}
        if name in ['현충로','율하']:
            a,b=packed_dms(center['위도']),packed_dms(center['경도'])
            record.update(dms_candidate_latitude=a,dms_candidate_longitude=b,
                          dms_candidate_nearest_exit_m=round(min(distance(a,b,c,d) for c,d in zip(group['위도'],group['경도'])),1),
                          diagnosis='packed DMS hypothesis, not an authorized source correction')
        else:
            record['diagnosis']='cause unknown; source center not adopted'
        diagnoses.append(record)
    results={'checked_date':'2026-10-12','method':'official exit points; no synthetic center or automatic coordinate repair',
             'coordinate_datum_status':'not explicit in source; degree coordinates plausible, not survey validation',
             'radius_status':'student selected 300m primary; 500m sensitivity; joins in poi_join.json',
             'matched_exit_station_line_groups':len(available),'traffic_rows':len(traffic),
             'no_usable_exit_station':missing,'unmatched_exit_names':[g['source_station'] for g in groups if not g['traffic_match']],
             'cluster_review':[g['traffic_station'] for g in groups if g['review_cluster']],
             'aliases':[{'old':'어린이회관','new':'어린이세상','source':CHILD,'status':'official rename confirmed; traffic and exit file both retain old name'},
                        {'old':'대공원','new':'수성알파시티','source':ALPHA,'status':'identity supported by official proposal and subsequent official coordinates; effective date unverified'}],
             'source_hashes':old['source_hashes'],
             'evidence_hashes':{n:hashlib.sha256((RAW/n).read_bytes()).hexdigest() for n in ['child_rename.txt','alpha_rename.txt']},
             'exit_sources':old['exit_sources'],'diagnoses':diagnoses,'station_exit_groups':groups}
    (OUT/'station_locations.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    text=['# 역 위치 검토와 분석 입력 선택','',
          '2026-10-12 · 김선경 A-01. 원본 대표좌표는 수정하지 않고, 분석 위치는 공식 출구 좌표로 분리했다.', '',
          '## 좌표 불일치 처리','',
          '| 역 | 원래 좌표와 가장 가까운 출구 거리(m) | 판단 |','| --- | ---: | --- |']
    for r in diagnoses:
        diagnosis=f"도분초 표기 가설 적용 시 {r['dms_candidate_nearest_exit_m']}m. 변환값은 채택하지 않음" if 'dms_candidate_nearest_exit_m' in r else '원인 미확정. 대표좌표 대신 출구 좌표 사용'
        text.append(f"| {r['station']} | {r['nearest_exit_original_m']} | {diagnosis} |")
    text += ['', '도분초 가설은 가까운 위치를 설명하는 진단이며 제공기관이 확인한 정정이 아니다. 만촌·담티의 적은 소수 자릿수만으로 오류 원인을 확정하지 않는다.', '',
             '## 역명 연결', '',
             f'- 어린이회관 → 어린이세상: [대구시의회 답변]({CHILD})에서 변경 확인. 승하차와 출구 자료는 모두 옛 이름이라 그대로 연결.',
             f'- 대공원 → 수성알파시티: [대구시 개정 추진 자료]({ALPHA})와 이후 공식 역·출구 자료의 새 이름을 함께 근거로 동일 역 별칭 처리. 정확한 시행일은 미확인.', '',
             '## 출구 기반 입력', '',
             f'- 승하차 {len(traffic)}개 역·호선 항목 중 출구 연결 {len(available)}개.',
             '- 출구 미확보 또는 미연결: '+', '.join(missing)+'. 0개 상권으로 처리하지 않는다.',
             '- 출구 자료의 수성운동장과 승하차 자료의 수성구민운동장은 이름 관계 추가 확인 전 제외한다.',
             '- 경산권 정평·임당·영남대와 하양 연장 구간은 대구 한정 POI의 범위 문제를 별도로 점검해야 한다.',
             '- 반월당·명덕·청라언덕은 호선별 승하차를 보존한다. 최종 가설 검증에서는 환승역을 독립 표본 여러 개로 취급하지 않도록 묶음/제외 민감도 비교가 필요하다.',
             '- 좌표계 datum과 최신 출구 운영 상태는 미확인. 이 입력은 탐색 준비용이며 현장 정확성을 보증하지 않는다.',
             '- 학생 선택: 300m 기준·500m 민감도 비교. 같은 역의 출구 반경이 겹치면 상가 한 행을 한 번만 집계하고, 서로 다른 역 간 중복은 따로 기록한다.', '',
             '## 재현·검증', '',
             '`.venv/Scripts/python scripts/prepare_a01_locations.py`', '',
             '원본 5개 해시 대조, 역·출구 키와 출구 군집 거리 점검. 상세 좌표·출처·진단은 station_locations.json에 보존. 후속 POI 결합은 poi_join.md 참고. 가설 검증·서비스 데이터 변경은 아직 수행하지 않았다.']
    (OUT/'location_resolution.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps({k:results[k] for k in ['matched_exit_station_line_groups','no_usable_exit_station','unmatched_exit_names','cluster_review','diagnoses']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
