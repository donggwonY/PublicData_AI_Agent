"""Build one evidence-backed consultation fixture, not a deployed AI feature."""
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from join_a01_poi import distances

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/a01'


def main():
    source=OUT/'poi_join.json';loc=OUT/'station_locations.json'
    data=json.loads(source.read_text(encoding='utf-8'))
    locations=json.loads(loc.read_text(encoding='utf-8'))
    verify_snapshot_hash(loc, data['input_hashes'][loc.name])
    poi_path=ROOT/'service/data/processed/poi.parquet'
    assert hashlib.sha256(poi_path.read_bytes()).hexdigest()==data['input_hashes'][poi_path.name]
    poi=pd.read_parquet(poi_path)
    exits=next(g for g in locations['station_exit_groups'] if g['traffic_station']=='동대구역')
    nearest=np.full(len(poi),np.inf)
    for p in exits['points']:
        nearest=np.minimum(nearest,distances(poi.lat.to_numpy(),poi.lon.to_numpy(),p['latitude'],p['longitude']))
    counts=[]
    for radius in (300,500):
        nearby=poi.loc[nearest<=radius]
        dedup=nearby.drop_duplicates()
        ref=next(r for r in data['station_results'] if r['station']=='동대구역' and r['radius_m']==radius)
        all_n=len(nearby);cafe_n=int(nearby.cat_s.eq('카페').sum());clean_cafe=int(dedup.cat_s.eq('카페').sum())
        assert (all_n,cafe_n,len(dedup),clean_cafe)==(ref['poi_rows'],ref['category_counts']['카페'],ref['poi_rows_exact_deduplicated'],ref['category_counts_exact_deduplicated']['카페'])
        counts.append({'radius_m':radius,'all_shop_rows':all_n,'cafe_rows':cafe_n,
                       'cafe_share_pct':round(cafe_n/all_n*100,2),
                       'all_shop_rows_exact_deduplicated':len(dedup),'cafe_rows_exact_deduplicated':clean_cafe,
                       'cafe_share_exact_deduplicated_pct':round(clean_cafe/len(dedup)*100,2),
                       'top_categories':[{ 'category':str(k),'rows':int(v)} for k,v in nearby.cat_s.value_counts().head(5).items()]})
    a,b=counts
    question='동대구역 근처에서 카페를 열려고 하는데, 주변 카페가 얼마나 있나요?'
    answer=(f"동대구역의 각 출구에서 직선거리 300m 이내를 합쳐 보면, 보유 상가 자료 {a['all_shop_rows']:,}건 중 카페로 분류된 기록은 {a['cafe_rows']}건({a['cafe_share_pct']:.2f}%)입니다. "
            f"범위를 500m로 넓히면 {b['cafe_rows']}건 / 전체 {b['all_shop_rows']:,}건({b['cafe_share_pct']:.2f}%)입니다. "
            "여러 출구 주변이 겹쳐도 같은 기록은 한 번만 셌습니다.\n\n"
            f"완전히 같은 행을 제거하면 300m 카페 기록은 {a['cafe_rows_exact_deduplicated']}건, 500m는 {b['cafe_rows_exact_deduplicated']}건입니다. "
            "따라서 현재 실제 영업하는 고유 카페 수로 단정하지는 않습니다. 프로젝트 설정상 2026년 6월 상가 자료이며, 원본 수집일과 출구의 최신 운영 상태는 추가 확인이 필요합니다. 거리는 도보거리가 아닙니다.\n\n"
            "이 수치로 예상 매출이나 창업 성공 여부를 판단할 수는 없습니다. 후보 점포 주소를 알려주시면, 그 주소를 중심으로 경쟁 점포와 자리 이력을 더 구체적으로 확인하겠습니다.")
    fixture={'case_id':'A01-STATION-CAFE-001','status':'offline_reference_answer_not_deployed','checked_date':'2026-10-12',
             'question':question,'station':'동대구역','category_match':{'field':'poi.cat_s','operator':'exact','value':'카페'},
             'spatial_definition':'union of official station exit buffers, spherical straight-line approximation',
             'counts':counts,'reference_answer':answer,
             'sources':{'poi':{'provider':'소상공인시장진흥공단 상가(상권)정보','configured_vintage':'202606','raw_observation_date_verified':False},
                        'exits':next(s for s in data['input_hashes'] if s=='station_locations.json'),
                        'exit_portal':'https://www.data.go.kr/data/15133918/fileData.do'},
             'input_hashes':{p.name:snapshot_sha256(p) for p in [source,loc,poi_path]},
             'live_tool_evaluation':{'performed':False,'reason':'new station-exit neighborhood tool is not implemented'},
             'handoff':{'existing_tools':['find_nearby','get_unit_history','get_station_traffic'],
                        'gap':'find_nearby requires a supported address and uses one center; no station-exit union endpoint exists',
                        'next_question':'후보 점포 주소를 알려주세요.',
                        'unsupported_address_behavior':'주소 후보를 확인하거나 자료 없음으로 응답; 역 좌표로 몰래 대체하지 않음'},
             'acceptance_criteria':['all figures agree with counts','distinguish station exits from candidate address',
                                    'state vintage uncertainty and duplicate limitation','do not infer sales, profitability or causality',
                                    'request candidate address for address-level tools','do not fabricate competing-shop names']}
    (OUT/'consultation_case.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# A-01 결과를 쓰는 상담 사례 하나','','상태: 오프라인 근거 답변 작성·수치 검증 완료. 서비스 기능 구현·LLM 실행 평가는 하지 않음.','',
           '## 해결할 사용자 질문','',question,'','## 근거 답변 예시','',answer,'','## 검증된 계산','',
           '| 범위 | 전체 상가 기록 | 카페 기록 | 카페 비중 | 동일행 제거 후 카페 |', '| --- | ---: | ---: | ---: | ---: |']
    for x in counts:lines.append(f"| {x['radius_m']}m | {x['all_shop_rows']:,} | {x['cafe_rows']} | {x['cafe_share_pct']:.2f}% | {x['cafe_rows_exact_deduplicated']} |")
    lines += ['', '카페는 상가 소분류 cat_s가 정확히 카페인 행이다. 기존 주소 도구의 키워드 부분일치 분류와 같은 정의라고 가정하지 않는다. 원천 점포 ID가 없어 동일행 제거도 고유 점포 확정을 뜻하지 않는다.',
              '상가 구성 예: 300m 내 기타 의류 소매업 116건, 카페 42건, 백반/한정식 37건, 여성 의류 소매업 37건, 신발 소매업 24건. 업종의 많고 적음만으로 좋은 입지라고 판정하지 않는다.', '',
              '## 기존 상담 도구와 연결','',
              '| 단계 | 현재 가능 여부 | 연결 방식 |','| --- | --- | --- |',
              '| 역 출구 주변 전체 구성 | 오프라인 분석 가능, 서비스 도구 없음 | 이번 JSON 근거와 답변 사례로 제품 필요성 검토 |',
              '| 특정 점포 주변 경쟁 업종 | 기존 find_nearby 존재 | 후보 주소가 인허가 자리 데이터에서 확인되면 주소 중심 반경 조회 |',
              '| 해당 자리 이력 | 기존 get_unit_history 존재 | 같은 주소의 인허가 이력 확인. 실제 공실·매물과 동일시하지 않음 |',
              '| 역별 승하차 | 기존 get_station_traffic 존재 | 참고 교통지표. 고유 방문자·카페 고객·매출로 변환하지 않음 |', '',
              '역 출구 합집합과 특정 점포 중심 원은 서로 다른 범위다. 이번 카페 수를 기존 find_nearby가 반환한 숫자라고 표시하지 않는다. 역명을 주소처럼 도구에 넣지 않는다.', '',
              '## 채택·보류 결정','',
              '- 남김: 공식 출구 연결·역명 매핑·품질 상태·300m/500m 업종 집계·원본 해시와 중복 점검.',
              '- 보류: 주거용 건물·격자 인구 추가 수집, 주거/귀가 원인 규명. 이번 상담 사례의 필수 입력이 아님.',
              '- 과거 상관 분석은 탐색 기록으로 보존하고 창업 추천의 근거로 사용하지 않음.',
              '- 서비스 도입은 이 사례의 유용성과 자료 기준일/좌표계/업종 정의를 검토한 후 결정. 원격 main 및 deploy 변경 없음.', '',
              '## 평가 기준과 수행 범위','',
              '수치 검증: 원본 POI에서 거리 결합을 다시 계산해 300m/500m 분자·분모·동일행 제거 수치를 대조했다. 입력 해시 일치. 답변은 이 수치로 생성했다.',
              '답변 평가 기준: 범위·출처 시점·중복 한계 표시, 매출/성공/인과 주장 금지, 실제 주소로 후속 질문, 없는 점포명 생성 금지.',
              '이는 근거 답변 사례이며 실제 AI가 도구를 올바르게 선택하고 답변했다는 평가 결과는 아니다. A-03 전체 평가 완료나 A-01 전체 완료로 처리하지 않는다.', '',
              '재현: `.venv/Scripts/python scripts/build_a01_consultation_case.py`. 정형 근거·입력 해시·평가 기준은 consultation_case.json.']
    (OUT/'consultation_case.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'case_id':fixture['case_id'],'counts':counts,'checks':'input hashes and independent raw POI recomputation agree'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
