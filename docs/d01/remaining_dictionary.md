# 나머지 11개 테이블의 컬럼 의미

데모 1932844 생성 코드 기준. 자료형·결측은 dictionary.md, 공통 기준일과 입력 해시는 manifest.json 참조. 보조 데이터는 각 출처 기준월을 따르며 동일 시점으로 간주하지 않는다.

## transitions

관측 단위: 단일 자리의 앞 인허가→다음 인허가 쌍. 생성: `pipeline/build.py: build_transitions`.

| column | meaning |
| --- | --- |
| uid | 단일 자리(is_single_unit) 중 앞 기록이 폐업하고 다음 인허가가 있는 자리 키. 한 uid에 여러 전이 가능. |
| gu | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| dong | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| from_name | 이전 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응). |
| from_category | 이전 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응). |
| from_service | 이전 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응). |
| from_life_years | 이전 기록 dur_days/365.25, 소수 둘째자리 반올림. |
| to_name | 다음 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응). |
| to_category | 다음 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응). |
| to_service | 다음 인허가의 상호 / 업태 / 업종(각 컬럼 접미사에 대응). |
| to_open | 다음 인허가일. |
| to_dur_days | 다음 기록의 관측 영업기간(일). 영업 중이면 기준일까지 중도절단. |
| to_closed | 다음 기록의 폐업 여부. |
| gap_days | 다음 인허가일−이전 폐업일. -60 이상만 저장. 실제 임대 공실 측정 아님. |

## area_year

관측 단위: 지역 수준별 연도. 생성: `pipeline/build.py: build_cycle`.

| column | meaning |
| --- | --- |
| gu | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| year | 개업/폐업 사건 연도, 2000년 이상만 출력. |
| opens | 해당 연도 인허가 / 폐업 기록 수. closes는 closed=true에 한함. |
| closes | 해당 연도 인허가 / 폐업 기록 수. closes는 closed=true에 한함. |
| active_end_of_year | 전체 과거 연도부터 개업−폐업 누적합. 마지막 부분연도는 기준일까지의 값. |
| level | 집계 수준. 조인 시 포함해야 하며 서로 다른 수준의 행을 합산하지 않음. |
| dong | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| partial_year | year가 기준일의 연도이면 true. 완전한 연간 수치와 직접 비교 주의. |

## area_cycle

관측 단위: 지역 수준별 사이클. 생성: `pipeline/build.py: build_cycle`.

| column | meaning |
| --- | --- |
| gu | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| open_recent | 기준일−3년보다 늦은 인허가 / 폐업 수. 폐업은 closed=true 조건. |
| close_recent | 기준일−3년보다 늦은 인허가 / 폐업 수. 폐업은 closed=true 조건. |
| open_prev | 기준일−6년 초과, 기준일−3년 이하의 인허가 / 폐업 수. |
| close_prev | 기준일−6년 초과, 기준일−3년 이하의 인허가 / 폐업 수. |
| active_now | 현재 closed=false 수. |
| active_then | 3년 전 이미 인허가되었고 당시 아직 폐업하지 않은 기록 수. |
| level | 집계 수준. 조인 시 포함해야 하며 서로 다른 수준의 행을 합산하지 않음. |
| dong | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| stage | 규칙 기반 단계와 설명. 최근 사건 20건 미만 또는 비율 계산 불가 시 보류; 경계 0.9/1.1. ML 결과 아님. |
| stage_desc | 규칙 기반 단계와 설명. 최근 사건 20건 미만 또는 비율 계산 불가 시 보류; 경계 0.9/1.1. ML 결과 아님. |
| open_close_ratio_recent | 최근 / 직전 기간의 개업÷폐업. 폐업 0이면 결측; 소수 둘째자리. |
| open_close_ratio_prev | 최근 / 직전 기간의 개업÷폐업. 폐업 0이면 결측; 소수 둘째자리. |
| active_change_pct | (active_now−active_then)/active_then×100. 분모 0이면 결측. |
| window_recent | 최근 / 직전 3년 범위 표시 문자열. 계산의 시작 경계는 초과 조건. |
| window_prev | 최근 / 직전 3년 범위 표시 문자열. 계산의 시작 경계는 초과 조건. |

## survival

관측 단위: 수준·지역·업종/업태별 생존 요약. 생성: `pipeline/build.py: build_survival`.

| column | meaning |
| --- | --- |
| level | 집계 수준. 조인 시 포함해야 하며 서로 다른 수준의 행을 합산하지 않음. |
| service | 집계 대상 업종 / 업태. 적용하지 않는 수준에서는 결측. 업태 수준 service는 최빈 업종. |
| category | 집계 대상 업종 / 업태. 적용하지 않는 수준에서는 결측. 업태 수준 service는 최빈 업종. |
| gu | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| dong | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| n | 2010년 이후 인허가 코호트의 표본 수. 그룹 n<30은 테이블에 생성하지 않음. |
| closed | 코호트 폐업 수 / 영업 중 중도절단 수. 두 값의 합은 n. |
| censored_active | 코호트 폐업 수 / 영업 중 중도절단 수. 두 값의 합은 n. |
| median_survival_years | KM 생존함수가 처음 50% 이하가 되는 일수/365.25. 도달하지 않으면 결측. |
| survival_1y_pct | 각 1·3·5년의 KM 생존율(%). 최대 관측기간 미달이면 결측. 소수 첫째자리. |
| survival_3y_pct | 각 1·3·5년의 KM 생존율(%). 최대 관측기간 미달이면 결측. 소수 첫째자리. |
| survival_5y_pct | 각 1·3·5년의 KM 생존율(%). 최대 관측기간 미달이면 결측. 소수 첫째자리. |
| curve_json | year와 survival_pct 배열의 JSON 문자열. 관측 가능한 연차만 최대 10년까지 저장. |

## vacancy_area

관측 단위: 구군/동별 공실 후보 집계. 생성: `pipeline/build.py: build_vacancy_area`.

| column | meaning |
| --- | --- |
| gu | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |
| units_3y | 현재 영업 기록이 있거나 공실 후보 기간≤1095일인 자리 수(분모). |
| vacant | 분모 중 공실 후보 기간 90~1095일인 자리 수. |
| occupied | 분모 중 vacant=false인 자리 수. 90일 미만 후보는 occupied도 vacant 집계도 아니므로 둘의 합이 분모와 다를 수 있음. |
| vacancy_rate_pct | vacant/units_3y×100, 소수 첫째자리. 실제 임대 공실률 아님. |
| level | 집계 수준. 조인 시 포함해야 하며 서로 다른 수준의 행을 합산하지 않음. |
| dong | 구군 / 구 지역 법정동·군 지역 읍면. 상위 집계 수준의 dong/gu는 구조적으로 비어 있을 수 있음. |

## poi

관측 단위: 상가정보 점포. 생성: `pipeline/external.py: build_poi`.

| column | meaning |
| --- | --- |
| name | 상가정보 상호명 / 지점명. 원천 상가업소번호는 현재 가공본에 미보존. |
| branch | 상가정보 상호명 / 지점명. 원천 상가업소번호는 현재 가공본에 미보존. |
| cat_l | 상권업종 대분류 / 중분류 / 소분류명. 인허가 업종 체계와 다름. |
| cat_m | 상권업종 대분류 / 중분류 / 소분류명. 인허가 업종 체계와 다름. |
| cat_s | 상권업종 대분류 / 중분류 / 소분류명. 인허가 업종 체계와 다름. |
| gu | 시군구명. 원천 또는 주소에서 얻음; area_context는 poi 그룹 기준. |
| admin_dong | 행정동명. legal_admin_map에서는 같은 법정동 POI 중 최빈 행정동. |
| legal_dong | 원천 상가정보의 법정동명. |
| floor | 원천 층정보. 누락 가능. |
| addr | 도로명주소 우선, 결측이면 지번주소. |
| lat | 원천 위도 / 경도 숫자 변환. 좌표 결측행은 제외됨. |
| lon | 원천 위도 / 경도 숫자 변환. 좌표 결측행은 제외됨. |

## area_context

관측 단위: 행정동별 맥락. 생성: `pipeline/external.py: build_area_context`.

| column | meaning |
| --- | --- |
| gu | 시군구명. 원천 또는 주소에서 얻음; area_context는 poi 그룹 기준. |
| admin_dong | 행정동명. legal_admin_map에서는 같은 법정동 POI 중 최빈 행정동. |
| poi_total | 행정동 POI 전체 수 / cat_l=음식 수. |
| poi_food | 행정동 POI 전체 수 / cat_l=음식 수. |
| food_share_pct | 행정동 전체 POI 중 음식 대분류 비율(%), 소수 첫째자리. |
| retail_share_pct | 행정동 전체 POI 중 소매 대분류 비율(%), 소수 첫째자리. |
| edu_share_pct | 행정동 전체 POI 중 교육 대분류 비율(%), 소수 첫째자리. |
| office_share_pct | 행정동 전체 POI 중 과학·기술+부동산+시설관리·임대 대분류 비율(%), 소수 첫째자리. |
| personal_share_pct | 행정동 전체 POI 중 수리·개인+보건의료 대분류 비율(%), 소수 첫째자리. |
| lodging_share_pct | 행정동 전체 POI 중 숙박 대분류 비율(%), 소수 첫째자리. |
| pub_share_of_food_pct | 음식 POI 중 중분류 주점 비율(%). 음식 0이면 0. |
| diversity_index | 행정동 / 도시 POI 중분류의 정규화 Shannon 다양성. -Σp log(p)/log(관찰 업종수), 종류≤1이면 0. |
| top_categories_json | 행정동 POI 중분류 상위 8개와 건수의 JSON 문자열. |
| lat | 행정동 POI 위도 / 경도 중앙값. 행정구역 기하학적 중심점 아님. |
| lon | 행정동 POI 위도 / 경도 중앙값. 행정구역 기하학적 중심점 아님. |
| pop_total | 행정동 주민등록 인구 전체 / 남자 / 여자 수. 구·행정동으로 좌측 조인. |
| pop_male | 행정동 주민등록 인구 전체 / 남자 / 여자 수. 구·행정동으로 좌측 조인. |
| pop_female | 행정동 주민등록 인구 전체 / 남자 / 여자 수. 구·행정동으로 좌측 조인. |
| age_0_14 | 0~14세 남녀 인구 합. 코드가 실제 존재하는 연령 컬럼만 합산하므로 원본 완전성은 별도 검증. |
| age_15_29 | 15~29세 남녀 인구 합. 코드가 실제 존재하는 연령 컬럼만 합산하므로 원본 완전성은 별도 검증. |
| age_30_49 | 30~49세 남녀 인구 합. 코드가 실제 존재하는 연령 컬럼만 합산하므로 원본 완전성은 별도 검증. |
| age_50_64 | 50~64세 남녀 인구 합. 코드가 실제 존재하는 연령 컬럼만 합산하므로 원본 완전성은 별도 검증. |
| age_65_plus | 65~110세 남녀 인구 합. 코드가 실제 존재하는 연령 컬럼만 합산하므로 원본 완전성은 별도 검증. |
| pop_ref_month | 원본 인구 파일 첫 행의 기준연월. 행마다 동일 기준월인지 원본 검증은 미실시. |
| age_0_14_pct | 0~14세 인구/pop_total×100, 소수 첫째자리. |
| age_15_29_pct | 15~29세 인구/pop_total×100, 소수 첫째자리. |
| age_30_49_pct | 30~49세 인구/pop_total×100, 소수 첫째자리. |
| age_50_64_pct | 50~64세 인구/pop_total×100, 소수 첫째자리. |
| age_65_plus_pct | 65~110세 인구/pop_total×100, 소수 첫째자리. |
| parking_count | 가장 가까운 POI의 행정동으로 배정된 주차장 / 시장 수. 행정 경계 포함 검사 아님. 집계 미매칭은 0 채움. |
| parking_slots | 행정동에 배정된 주차면 수 / 시장 점포 수 합계. 집계 미매칭은 0 채움. |
| market_count | 가장 가까운 POI의 행정동으로 배정된 주차장 / 시장 수. 행정 경계 포함 검사 아님. 집계 미매칭은 0 채움. |
| market_stores | 행정동에 배정된 주차면 수 / 시장 점포 수 합계. 집계 미매칭은 0 채움. |
| market_type | 업종 구성·인구·시설 규칙의 상권 유형 / 근거 문장. POI 30개 미만 표본 부족. ML 아님. |
| market_type_basis | 업종 구성·인구·시설 규칙의 상권 유형 / 근거 문장. POI 30개 미만 표본 부족. ML 아님. |
| city_food | 전체 도시 POI 중 음식 비율(%). 각 행에 반복 저장, 합산 금지. |
| city_retail | 전체 도시 POI 중 소매 비율(%). 각 행에 반복 저장, 합산 금지. |
| city_edu | 전체 도시 POI 중 교육 비율(%). 각 행에 반복 저장, 합산 금지. |
| city_office | 전체 도시 POI 중 과학·기술+부동산+시설관리·임대 비율(%). 각 행에 반복 저장, 합산 금지. |
| city_personal | 전체 도시 POI 중 수리·개인+보건의료 비율(%). 각 행에 반복 저장, 합산 금지. |
| city_lodging | 전체 도시 POI 중 숙박 비율(%). 각 행에 반복 저장, 합산 금지. |
| city_pub | 도시 전체 음식 POI 중 주점 비율(%). |
| city_youth_pct | 행정동별 15~29세 비율의 중앙값. 도시 총인구의 청년 비율과 다름. |
| city_diversity | 행정동 / 도시 POI 중분류의 정규화 Shannon 다양성. -Σp log(p)/log(관찰 업종수), 종류≤1이면 0. |

## legal_admin_map

관측 단위: 법정동별 대표 행정동. 생성: `pipeline/external.py: build_poi`.

| column | meaning |
| --- | --- |
| gu | 시군구명. 원천 또는 주소에서 얻음; area_context는 poi 그룹 기준. |
| legal_dong | 원천 상가정보의 법정동명. |
| admin_dong | 행정동명. legal_admin_map에서는 같은 법정동 POI 중 최빈 행정동. |
| n | 선택된 구·법정동·행정동 조합의 POI 수. 법정동 전체 건수 아님. |
| share | n/해당 구·법정동의 모든 행정동 조합 POI 수, 소수 셋째자리. 일대일 행정 경계 보장 아님. |

## parking

관측 단위: 주차장. 생성: `pipeline/external.py: build_parking`.

| column | meaning |
| --- | --- |
| name | 원천 시설명. 고유 ID 아님. |
| kind | 원천 주차장구분 / 시장유형(테이블별). |
| addr | 도로명 우선, 지번 대체. 대구로 시작하는 주소만 포함. |
| slots | 원천 주차구획수. 실시간 빈 주차면 수 아님. |
| lat | 원천 위도 / 경도 숫자 변환; 좌표 없는 행 제외. |
| lon | 원천 위도 / 경도 숫자 변환; 좌표 없는 행 제외. |
| gu | 시군구명. 원천 또는 주소에서 얻음; area_context는 poi 그룹 기준. |

## market

관측 단위: 전통시장. 생성: `pipeline/external.py: build_market`.

| column | meaning |
| --- | --- |
| name | 원천 시설명. 고유 ID 아님. |
| kind | 원천 주차장구분 / 시장유형(테이블별). |
| addr | 도로명 우선, 지번 대체. 대구로 시작하는 주소만 포함. |
| stores | 원천 시장 점포수. |
| parking | 원천 주차장보유여부 문자열. |
| lat | 원천 위도 / 경도 숫자 변환; 좌표 없는 행 제외. |
| lon | 원천 위도 / 경도 숫자 변환; 좌표 없는 행 제외. |
| gu | 시군구명. 원천 또는 주소에서 얻음; area_context는 poi 그룹 기준. |

## station_traffic

관측 단위: 역별 승하차 요약. 생성: `pipeline/external.py: build_station_traffic`.

| column | meaning |
| --- | --- |
| station | 원천 역명으로 집계. 호선/역 고유 ID는 출력에 없음. |
| daily_boarding | 승차 / 하차 일계 합÷관측일수(역·월·일 조합수/역수), 정수 반올림. 역별 누락일 차이 주의. |
| daily_alighting | 승차 / 하차 일계 합÷관측일수(역·월·일 조합수/역수), 정수 반올림. 역별 누락일 차이 주의. |
| daily_total | 일평균 승차+하차. 고유 방문자 수 아님. |
| morning_07_09_pct | 07~09시 하차 합/사용 가능한 05~24시 하차 합×100, 소수 첫째자리. |
| lunch_11_14_pct | 11~14시 하차 합/사용 가능한 05~24시 하차 합×100, 소수 첫째자리. |
| evening_17_20_pct | 17~20시 하차 합/사용 가능한 05~24시 하차 합×100, 소수 첫째자리. |
| night_22_24_pct | 22~24시 하차 합/사용 가능한 05~24시 하차 합×100, 소수 첫째자리. |
| peak_hour | 하차 합계 최대인 시간대. 동률은 컬럼 순서상 첫 값. |
| period | 원본 월 최솟값~최댓값 문자열. 연도와 원천 파일 기준일은 별도 보존 필요. |
