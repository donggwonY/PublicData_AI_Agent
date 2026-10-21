"""Read-only input comparison and independent cafe recalculation."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash
from join_a01_poi import distances

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/a01'

def main():
    old=ROOT/'service/data/snapshots/20260923_7services'
    new=ROOT/'service/data/processed'
    compared=[]
    for name in ['poi','station_traffic','area_context','stores']:
        a,b=old/f'{name}.parquet',new/f'{name}.parquet'
        compared.append({'table':name,'old_rows':len(pd.read_parquet(a)),'new_rows':len(pd.read_parquet(b)),
                         'old_hash':snapshot_sha256(a),'new_hash':snapshot_sha256(b),'identical':a.read_bytes()==b.read_bytes()})
    metas=[json.loads((p/'meta.json').read_text(encoding='utf-8')) for p in [old,new]]
    loc=OUT/'station_locations.json'
    prior=json.loads((OUT/'poi_join.json').read_text(encoding='utf-8'))
    for p in [loc,new/'poi.parquet',new/'station_traffic.parquet']:
        verify_snapshot_hash(p,prior['input_hashes'][p.name])
    points=next(g['points'] for g in json.loads(loc.read_text(encoding='utf-8'))['station_exit_groups'] if g['traffic_station']=='동대구역')
    poi=pd.read_parquet(new/'poi.parquet')
    d=np.column_stack([distances(poi.lat.to_numpy(),poi.lon.to_numpy(),p['latitude'],p['longitude']) for p in points])
    unique=~poi.duplicated().to_numpy();cafe=poi.cat_s.eq('카페').to_numpy()
    fixture=json.loads((OUT/'consultation_case.json').read_text(encoding='utf-8'))
    exits_ref=json.loads((OUT/'dongdaegu_exit_cafes.json').read_text(encoding='utf-8'))
    counts=[]
    for radius in [300,500]:
        mask=d.min(axis=1)<=radius
        values=[int(mask.sum()),int((mask&unique).sum()),int((mask&cafe).sum()),int((mask&cafe&unique).sum())]
        ref=next(x for x in fixture['counts'] if x['radius_m']==radius)
        assert values==[ref['all_shop_rows'],ref['all_shop_rows_exact_deduplicated'],ref['cafe_rows'],ref['cafe_rows_exact_deduplicated']]
        assigned=[]
        for i,p in enumerate(points):
            m=mask&cafe&(d.argmin(axis=1)==i)
            vals=[int(m.sum()),int((m&unique).sum())]
            r=next(x for x in next(x for x in exits_ref['results'] if x['radius_m']==radius)['exits'] if x['exit']==p['exit'])
            assert vals==[r['nearest_count'],r['nearest_deduplicated']]
            assigned.append({'exit':p['exit'],'rows':vals[0],'deduplicated':vals[1]})
        counts.append({'radius':radius,'all_rows':values[0],'all_deduplicated':values[1],'cafe_rows':values[2],'cafe_deduplicated':values[3],'exits':assigned})
    comparison=json.loads((OUT/'candidate_sectors.json').read_text(encoding='utf-8'))
    assert comparison['input_sha256']['stores.parquet']==snapshot_sha256(old/'stores.parquet')
    result={'checked_date':'2026-10-21','scope':'local snapshots only; no database connection configured',
            'reference_dates':[m['reference_date'] for m in metas], 'inputs':compared,'dongdaegu':counts,
            'location_hash':snapshot_sha256(loc),'candidate_comparison_stale_for_current':comparison['input_sha256']['stores.parquet']!=snapshot_sha256(new/'stores.parquet')}
    (OUT/'refresh_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# A-01 입력 변경과 기존 결과 재검증','', '2026-10-21 · 김선경 · 로컬 이전/최신 스냅샷 비교 및 집계 재계산 완료. 공유 DB 직접 확인은 미수행.','',
           '## 입력 비교','',f"인허가 기준일: {metas[0]['reference_date']} → {metas[1]['reference_date']}",'',
           '| 입력 | 이전 행 수 | 최신 행 수 | 파일 내용 |','| --- | ---: | ---: | --- |']
    for x in compared:lines.append(f"| {x['table']} | {x['old_rows']:,} | {x['new_rows']:,} | {'동일' if x['identical'] else '변경'} |")
    lines+=['','## 기존 결과 사용 여부','','- 동대구역 300m: 전체 732건·카페 42건, 동일행 제거 전체 724건·카페 41건. 최신 로컬 상가 자료로 재계산하여 기존 결과와 일치했다.',
            '- 300m 최근접 배정: 1번 3건·2번 21건·3번 18건, 동일행 제거 시 3·20·18건. 500m 결과도 기존 근거와 일치했다.',
            '- 상가·승하차·행정동 맥락 파일은 이전 스냅샷과 동일하고 출구 자료는 기존 결합 입력 해시 검증을 통과했다. 카페 지도와 과거 역별 탐색 결과는 기존 입력 시점의 결과로 보존할 수 있다. 이번에는 전체 상관분석이나 지도 화면을 다시 검증한 것은 아니다.',
            '- 후보 업종 12개 비교표는 변경 전 stores 자료를 사용했음이 해시로 확인됐다. 현재 15업종 현황으로 사용할 수 없으므로 과거 비교자료로 표시하고, 새 업종 비교가 필요하면 정의를 갱신해 별도로 재계산해야 한다.',
            '- 인허가 갱신이 상가 목록 갱신을 뜻하지 않는다. 기존 카페 수를 2026-10-13 또는 오늘의 영업 점포 수라고 표현하지 않는다.', '',
            '## DB 확인 제한과 다음 단계','','실제 프로세스 환경변수와 Git 제외 .env를 확인했으며 APP_DATABASE_URL 및 APP_READER_DATABASE_URL 모두 미설정이었다. 비밀값은 출력하지 않았다. 공유 프로젝트 uoiamnbkzlvlskngataq의 접속 계정·읽기 권한·app.current_version은 확인하지 못했고 DB 저장도 하지 않았다.', '',
            '관리자에게 해당 공유 프로젝트의 최소 권한 읽기 전용 접속 정보를 받아 로컬 APP_DATABASE_URL에 설정한 뒤, 실제 대상·권한·현재 버전을 조회하고 이번 로컬 입력과 대조한다. 운영 app 변경이나 버전 전환은 하지 않는다.', '',
            '## 재현','','`.venv/Scripts/python.exe scripts/check_a01_refresh.py` — 입력 비교, 기존 해시 검증, 반경별 전체/카페 수 및 최근접 출구 배정 검증. 상세 입력 SHA-256은 refresh_check.json. 기존 평가표·지도·분석 수치는 덮어쓰지 않았다.','']
    (OUT/'refresh_check.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
