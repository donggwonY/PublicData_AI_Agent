"""Reproduce Nam-gu failure classification and all remaining column definitions."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from profile_data import table, TABLES

ROOT=Path(__file__).resolve().parents[1]
DEFINITIONS={}


def add(name, columns, meaning):
    for col in columns.split(): DEFINITIONS.setdefault(name,{})[col]=meaning


# Meanings are grounded in pipeline/build.py, pipeline/external.py and core modules.
for name in ('transitions','area_year','area_cycle','survival','vacancy_area'):
    add(name,'gu dong','구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음.')
for name in ('area_year','area_cycle','survival','vacancy_area'):
    add(name,'level','집계 수준. 조인 시 포함해야 하며 서로 다른 수준의 행을 합산하지 않음.')
add('transitions','uid','단일 자리(is_single_unit) 중 앞 기록이 폐업하고 다음 인허가가 있는 자리 키. 한 uid에 여러 전이 가능.')
add('transitions','from_name from_category from_service','이전 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응).')
add('transitions','to_name to_category to_service','다음 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응).')
add('transitions','from_life_years','이전 기록 dur_days/365.25, 소수 둘째자리 반올림.')
add('transitions','to_open','다음 인허가일.')
add('transitions','to_dur_days','다음 기록의 관측 영업기간(일). 영업 중이면 기준일까지 중도절단.')
add('transitions','to_closed','다음 기록의 폐업 여부.')
add('transitions','gap_days','다음 인허가일−이전 폐업일. -60 이상만 저장. 실제 임대 공실 측정 아님.')
add('area_year','year','개업/폐업 사건 연도, 2000년 이상만 출력.')
add('area_year','opens closes','해당 연도 인허가 / 폐업 기록 수. closes는 closed=true에 한함.')
add('area_year','active_end_of_year','전체 과거 연도부터 개업−폐업 누적합. 마지막 부분연도는 기준일까지의 값.')
add('area_year','partial_year','year가 기준일의 연도이면 true. 완전한 연간 수치와 직접 비교 주의.')
add('area_cycle','open_recent close_recent','기준일−3년보다 늦은 인허가 / 폐업 수. 폐업은 closed=true 조건.')
add('area_cycle','open_prev close_prev','기준일−6년 초과, 기준일−3년 이하의 인허가 / 폐업 수.')
add('area_cycle','active_now','현재 closed=false 수.')
add('area_cycle','active_then','3년 전 이미 인허가되었고 당시 아직 폐업하지 않은 기록 수.')
add('area_cycle','stage stage_desc','규칙 기반 단계와 설명. 최근 사건 20건 미만 또는 비율 계산 불가 시 보류; 경계 0.9/1.1. ML 결과 아님.')
add('area_cycle','open_close_ratio_recent open_close_ratio_prev','최근 / 직전 기간의 개업÷폐업. 폐업 0이면 결측; 소수 둘째자리.')
add('area_cycle','active_change_pct','(active_now−active_then)/active_then×100. 분모 0이면 결측.')
add('area_cycle','window_recent window_prev','최근 / 직전 3년 범위 표시 문자열. 계산의 시작 경계는 초과 조건.')
add('survival','service category','집계 대상 업종 / 업태. 적용하지 않는 수준에서는 결측. 업태 수준 service는 최빈 업종.')
add('survival','n','2010년 이후 인허가 코호트의 표본 수. 그룹 n<30은 테이블에 생성하지 않음.')
add('survival','closed censored_active','코호트 폐업 수 / 영업 중 중도절단 수. 두 값의 합은 n.')
add('survival','median_survival_years','KM 생존함수가 처음 50% 이하가 되는 일수/365.25. 도달하지 않으면 결측.')
add('survival','survival_1y_pct survival_3y_pct survival_5y_pct','각 1·3·5년의 KM 생존율(%). 최대 관측기간 미달이면 결측. 소수 첫째자리.')
add('survival','curve_json','year와 survival_pct 배열의 JSON 문자열. 관측 가능한 연차만 최대 10년까지 저장.')
add('vacancy_area','units_3y','현재 영업 기록이 있거나 공실 후보 기간≤1095일인 자리 수(분모).')
add('vacancy_area','vacant','분모 중 공실 후보 기간 90~1095일인 자리 수.')
add('vacancy_area','occupied','분모 중 vacant=false인 자리 수. 90일 미만 후보는 occupied도 vacant 집계도 아니므로 둘의 합이 분모와 다를 수 있음.')
add('vacancy_area','vacancy_rate_pct','vacant/units_3y×100, 소수 첫째자리. 실제 임대 공실률 아님.')
for name in ('poi','area_context','legal_admin_map','parking','market'):
    add(name,'gu','시군구명. 원천 또는 주소에서 얻음; area_context는 poi 그룹 기준.')
for name in ('poi','area_context','legal_admin_map'):
    add(name,'admin_dong','행정동명. legal_admin_map에서는 같은 법정동 POI 중 최빈 행정동.')
for name in ('poi','legal_admin_map'):
    add(name,'legal_dong','원천 상가정보의 법정동명.')
add('poi','name branch','상가정보 상호명 / 지점명. 원천 상가업소번호는 현재 가공본에 미보존.')
add('poi','cat_l cat_m cat_s','상권업종 대분류 / 중분류 / 소분류명. 인허가 업종 체계와 다름.')
add('poi','floor','원천 층정보. 누락 가능.')
add('poi','addr','도로명주소 우선, 결측이면 지번주소.')
add('poi','lat lon','원천 위도 / 경도 숫자 변환. 좌표 결측행은 제외됨.')
add('legal_admin_map','n','선택된 구·법정동·행정동 조합의 POI 수. 법정동 전체 건수 아님.')
add('legal_admin_map','share','n/해당 구·법정동의 모든 행정동 조합 POI 수, 소수 셋째자리. 일대일 행정 경계 보장 아님.')
add('area_context','poi_total poi_food','행정동 POI 전체 수 / cat_l=음식 수.')
for col,label in [('food','음식'),('retail','소매'),('edu','교육'),('office','과학·기술+부동산+시설관리·임대'),('personal','수리·개인+보건의료'),('lodging','숙박')]:
    add('area_context',col+'_share_pct',f'행정동 전체 POI 중 {label} 대분류 비율(%), 소수 첫째자리.')
    add('area_context','city_'+col,f'전체 도시 POI 중 {label} 비율(%). 각 행에 반복 저장, 합산 금지.')
add('area_context','pub_share_of_food_pct','음식 POI 중 중분류 주점 비율(%). 음식 0이면 0.')
add('area_context','city_pub','도시 전체 음식 POI 중 주점 비율(%).')
add('area_context','diversity_index city_diversity','행정동 / 도시 POI 중분류의 정규화 Shannon 다양성. -Σp log(p)/log(관찰 업종수), 종류≤1이면 0.')
add('area_context','top_categories_json','행정동 POI 중분류 상위 8개와 건수의 JSON 문자열.')
add('area_context','lat lon','행정동 POI 위도 / 경도 중앙값. 행정구역 기하학적 중심점 아님.')
add('area_context','pop_total pop_male pop_female','행정동 주민등록 인구 전체 / 남자 / 여자 수. 구·행정동으로 좌측 조인.')
for group,ages in [('0_14','0~14'),('15_29','15~29'),('30_49','30~49'),('50_64','50~64'),('65_plus','65~110')]:
    add('area_context','age_'+group,f'{ages}세 남녀 인구 합. 코드가 실제 존재하는 연령 컬럼만 합산하므로 원본 완전성은 별도 검증.')
    add('area_context','age_'+group+'_pct',f'{ages}세 인구/pop_total×100, 소수 첫째자리.')
add('area_context','pop_ref_month','원본 인구 파일 첫 행의 기준연월. 행마다 동일 기준월인지 원본 검증은 미실시.')
add('area_context','parking_count market_count','가장 가까운 POI의 행정동으로 배정된 주차장 / 시장 수. 행정 경계 포함 검사 아님. 집계 미매칭은 0 채움.')
add('area_context','parking_slots market_stores','행정동에 배정된 주차면 수 / 시장 점포 수 합계. 집계 미매칭은 0 채움.')
add('area_context','market_type market_type_basis','업종 구성·인구·시설 규칙의 상권 유형 / 근거 문장. POI 30개 미만 표본 부족. ML 아님.')
add('area_context','city_youth_pct','행정동별 15~29세 비율의 중앙값. 도시 총인구의 청년 비율과 다름.')
add('station_traffic','station','원천 역명으로 집계. 호선/역 고유 ID는 출력에 없음.')
add('station_traffic','daily_boarding daily_alighting','승차 / 하차 일계 합÷관측일수(역·월·일 조합수/역수), 정수 반올림. 역별 누락일 차이 주의.')
add('station_traffic','daily_total','일평균 승차+하차. 고유 방문자 수 아님.')
for col,hours in [('morning_07_09','07~09'),('lunch_11_14','11~14'),('evening_17_20','17~20'),('night_22_24','22~24')]:
    add('station_traffic',col+'_pct',f'{hours}시 하차 합/사용 가능한 05~24시 하차 합×100, 소수 첫째자리.')
add('station_traffic','peak_hour','하차 합계 최대인 시간대. 동률은 컬럼 순서상 첫 값.')
add('station_traffic','period','원본 월 최솟값~최댓값 문자열. 연도와 원천 파일 기준일은 별도 보존 필요.')
for name in ('parking','market'):
    add(name,'name','원천 시설명. 고유 ID 아님.')
    add(name,'kind','원천 주차장구분 / 시장유형(테이블별).')
    add(name,'addr','도로명 우선, 지번 대체. 대구로 시작하는 주소만 포함.')
    add(name,'lat lon','원천 위도 / 경도 숫자 변환; 좌표 없는 행 제외.')
add('parking','slots','원천 주차구획수. 실시간 빈 주차면 수 아님.')
add('market','stores','원천 시장 점포수.')
add('market','parking','원천 주차장보유여부 문자열.')


def main():
    src=ROOT/'service/data/processed'
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    frames={}
    for name in TABLES:
        p=src/f'{name}.parquet'
        if hashlib.sha256(p.read_bytes()).hexdigest()!=manifest['sha256'][p.name]: raise ValueError('snapshot mismatch')
        frames[name]=pd.read_parquet(p)
    pages=['# 나머지 11개 테이블의 컬럼 의미', '데모 1932844 생성 코드 기준. 자료형·결측은 dictionary.md, 공통 기준일과 입력 해시는 manifest.json 참조. 보조 데이터는 각 출처 기준월을 따르며 동일 시점으로 간주하지 않는다.']
    coverage={}
    for name,defs in DEFINITIONS.items():
        cols=list(frames[name].columns)
        if set(cols)!=set(defs): raise ValueError(f'column coverage mismatch: {name}')
        coverage[name]=len(cols)
        pages += [f'## {name}',f'관측 단위: {TABLES[name][0]}. 생성: `{TABLES[name][2]}`.',
                  table(pd.DataFrame([{'column':c,'meaning':defs[c]} for c in cols]))]
    (ROOT/'docs/d01/remaining_dictionary.md').write_text('\n\n'.join(pages)+'\n',encoding='utf-8')
    st,mp,ctx=frames['stores'],frames['legal_admin_map'],frames['area_context']
    merged=st[st.gu.eq('남구')].merge(mp[['gu','legal_dong']],left_on=['gu','dong'],right_on=['gu','legal_dong'],how='left',validate='many_to_one',indicator=True)
    failed=merged[merged._merge.eq('left_only')].copy()
    admins=set(ctx.loc[ctx.gu.eq('남구'),'admin_dong'].dropna())
    failed['reason']=failed['dong'].map(lambda d:'동 파싱 결측' if pd.isna(d) else '법정동 키에는 없고 현재 행정동명과 일치' if d in admins else '기타 미확인')
    counts=failed.reason.value_counts()
    if len(failed)!=409 or counts.sum()!=409: raise ValueError('unexpected population')
    details=[]
    for reason,group in failed.groupby('reason'):
        details += [f'## {reason}: {len(group)}건',table(group[['mgmt_no','service','dong','road_addr_raw','jibun_addr_raw']].head(5))]
    grouped=failed.groupby(['reason','dong'],dropna=False).size().reset_index(name='rows')
    report=['# 남구 미연결 409건 원인 분류','기준일 2026-09-23, 원본 파일 해시 대조 후 재현. 원본 수정 없음.',table(grouped),
            '407건의 숫자 붙은 동 이름은 법정동 매핑 키에는 없고 현재 맥락표의 남구 행정동명과 정확히 일치한다. 원문 지번에도 이런 이름이 있어 법정동만 있다고 가정한 연결 경로가 맞지 않는 것이 직접적인 미연결 원인이다. 이것이 과거 기록의 현재 행정동 배정까지 검증했다는 뜻은 아니다.',
            '2건은 dong이 비어 있고 원문은 각각 대명동 호 1723 19 / 대명동 호 2139 형태다. 도로명도 없어 현 파서가 동을 추출하지 못한 사례다. 대명동 문자열을 복원하더라도 정확한 행정동은 따로 확인해야 한다.',
            *details,'## 보정 가능성과 남은 한계',
            '407건은 행정동명 직접 연결 후보로 표시할 수 있다. 과거/현재 경계와 주소를 확인한 후만 적용하고, 법정동명에서 숫자를 무조건 지워 대표 행정동으로 보내지 않는다. 2건은 주소 정리·공식 주소 확인 대상이다. 실제 보정/일괄 삭제는 D-01에서 실행하지 않았다.',
            '남구 legal_admin_map에서 대명동의 대표 행정동 점유율은 0.159, 봉덕동은 0.434다. 대표값을 적용하면 연결은 되더라도 다른 행정동으로 배정될 수 있으므로 낮은 실패율만 목표로 삼지 않는다.',
            '김세은의 해석에 따라 원본을 보존하고 분석 목적에 따라 미연결 포함/제외를 결정한다. 행정동을 쓰지 않는 분석에서는 다른 필수 변수가 유효한지 따로 판단한다.',
            '재현: `python scripts/finish_d01.py` (pandas·pyarrow). 표본은 원래 순서 첫 5건으로 대표 표본이 아니다.']
    (ROOT/'docs/d01/namgu_causes.md').write_text('\n\n'.join(report)+'\n',encoding='utf-8')
    summary={'column_coverage':coverage,'tables':len(coverage),'columns':sum(coverage.values()),'namgu_unmatched':len(failed),'reasons':counts.to_dict(),'raw_data_modified':False}
    (ROOT/'docs/d01/completion_checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
