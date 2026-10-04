# D-01 데이터 구조 사전 초안

전체 컬럼의 자료형·결측·빈 문자열·고유값 수. null과 빈 문자열은 별도 집계한다. 지역 수준별 요약표의 상위 수준에서는 dong 등이 구조적으로 비어 있으므로 모든 결측을 오류로 세지 않는다. 컬럼별 의미 정의는 후속 작업이다.

## stores

관측 단위: 인허가 1건. 생성 코드: `pipeline/build.py: clean/build_address/main`.

검사 키: `org_code`, `mgmt_no`, `service`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| uid | str | 0 | 0.0 | 0 | 76363 |
| building_key | str | 0 | 0.0 | 0 | 65714 |
| service | str | 0 | 0.0 | 0 | 7 |
| category | str | 0 | 0.0 | 0 | 55 |
| name | str | 0 | 0.0 | 0 | 136435 |
| ld | datetime64[us] | 0 | 0.0 | 0 | 12548 |
| cd | datetime64[us] | 59049 | 29.92 | 0 | 7389 |
| closed | bool | 0 | 0.0 | 0 | 2 |
| dur_days | int64 | 0 | 0.0 | 0 | 13435 |
| gu | str | 10 | 0.01 | 0 | 9 |
| dong | str | 142 | 0.07 | 0 | 297 |
| floor | str | 113985 | 57.76 | 0 | 37 |
| road_addr_raw | str | 49213 | 24.94 | 0 | 100380 |
| jibun_addr_raw | str | 2576 | 1.31 | 0 | 118443 |
| road_key | str | 49268 | 24.96 | 0 | 50020 |
| lat | float64 | 9877 | 5.0 | 0 | 56545 |
| lon | float64 | 9877 | 5.0 | 0 | 56545 |
| area_m2 | float64 | 41822 | 21.19 | 0 | 20729 |
| mgmt_no | str | 0 | 0.0 | 0 | 195399 |
| org_code | str | 0 | 0.0 | 0 | 9 |



## units

관측 단위: 주소·층 기반 자리 1곳. 생성 코드: `pipeline/build.py: build_units`.

검사 키: `uid`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| uid | str | 0 | 0.0 | 0 | 76363 |
| gu | str | 10 | 0.01 | 0 | 9 |
| dong | str | 137 | 0.18 | 0 | 297 |
| n_records | int64 | 0 | 0.0 | 0 | 93 |
| n_active | int64 | 0 | 0.0 | 0 | 37 |
| n_closed | int64 | 0 | 0.0 | 0 | 81 |
| closures_since_2010 | int64 | 0 | 0.0 | 0 | 60 |
| first_open | datetime64[us] | 0 | 0.0 | 0 | 12251 |
| last_open | datetime64[us] | 0 | 0.0 | 0 | 10827 |
| last_close | datetime64[us] | 16099 | 21.08 | 0 | 6688 |
| lat | float64 | 4897 | 6.41 | 0 | 55945 |
| lon | float64 | 4897 | 6.41 | 0 | 55939 |
| n_services | int64 | 0 | 0.0 | 0 | 7 |
| n_categories | int64 | 0 | 0.0 | 0 | 23 |
| avg_life_closed_years | float64 | 16099 | 21.08 | 0 | 3526 |
| avg_life_since_2010_years | float64 | 48366 | 63.34 | 0 | 1492 |
| floor | str | 34620 | 45.34 | 0 | 37 |
| building_key | str | 0 | 0.0 | 0 | 65714 |
| road_addr | str | 13218 | 17.31 | 0 | 48500 |
| jibun_addr | str | 0 | 0.0 | 0 | 65714 |
| addr | str | 0 | 0.0 | 0 | 73276 |
| last_name | str | 0 | 0.0 | 0 | 62625 |
| last_category | str | 0 | 0.0 | 0 | 53 |
| last_service | str | 0 | 0.0 | 0 | 7 |
| last_life_years | float64 | 0 | 0.0 | 0 | 4076 |
| category_path | str | 0 | 0.0 | 0 | 15440 |
| current_stores | str | 36161 | 47.35 | 0 | 37505 |
| max_concurrent | int64 | 0 | 0.0 | 0 | 49 |
| max_concurrent_naive | int64 | 0 | 0.0 | 0 | 49 |
| is_single_unit | bool | 0 | 0.0 | 0 | 2 |
| vacant | bool | 0 | 0.0 | 0 | 2 |
| vacant_days | float64 | 40202 | 52.65 | 0 | 6534 |
| recent_vacancy | bool | 0 | 0.0 | 0 | 2 |
| vacancy_bucket | str | 0 | 0.0 | 0 | 6 |



## transitions

관측 단위: 단일 자리의 앞 인허가→다음 인허가 쌍. 생성 코드: `pipeline/build.py: build_transitions`.

검사 키: 미확정. 행 번호를 영구 ID로 사용하지 않는다.

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| uid | str | 0 | 0.0 | 0 | 15306 |
| gu | str | 0 | 0.0 | 0 | 9 |
| dong | str | 1 | 0.0 | 0 | 268 |
| from_name | str | 0 | 0.0 | 0 | 19013 |
| from_category | str | 0 | 0.0 | 0 | 48 |
| from_service | str | 0 | 0.0 | 0 | 7 |
| from_life_years | float64 | 0 | 0.0 | 0 | 2492 |
| to_name | str | 0 | 0.0 | 0 | 19728 |
| to_category | str | 0 | 0.0 | 0 | 47 |
| to_service | str | 0 | 0.0 | 0 | 7 |
| to_open | datetime64[us] | 0 | 0.0 | 0 | 6174 |
| to_dur_days | float64 | 0 | 0.0 | 0 | 5736 |
| to_closed | boolean | 0 | 0.0 | 0 | 2 |
| gap_days | float64 | 0 | 0.0 | 0 | 4171 |



## area_year

관측 단위: 지역 수준별 연도. 생성 코드: `pipeline/build.py: build_cycle`.

검사 키: `level`, `gu`, `dong`, `year`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| gu | str | 27 | 0.43 | 0 | 9 |
| year | int64 | 0 | 0.0 | 0 | 27 |
| opens | int64 | 0 | 0.0 | 0 | 472 |
| closes | int64 | 0 | 0.0 | 0 | 432 |
| active_end_of_year | int64 | 0 | 0.0 | 0 | 1303 |
| level | str | 0 | 0.0 | 0 | 3 |
| dong | str | 270 | 4.3 | 0 | 296 |
| partial_year | bool | 0 | 0.0 | 0 | 2 |



## area_cycle

관측 단위: 지역 수준별 사이클. 생성 코드: `pipeline/build.py: build_cycle`.

검사 키: `level`, `gu`, `dong`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| gu | str | 1 | 0.32 | 0 | 9 |
| open_recent | int64 | 0 | 0.0 | 0 | 117 |
| close_recent | int64 | 0 | 0.0 | 0 | 130 |
| open_prev | int64 | 0 | 0.0 | 0 | 131 |
| close_prev | int64 | 0 | 0.0 | 0 | 124 |
| active_now | int64 | 0 | 0.0 | 0 | 174 |
| active_then | int64 | 0 | 0.0 | 0 | 179 |
| level | str | 0 | 0.0 | 0 | 3 |
| dong | str | 10 | 3.23 | 0 | 297 |
| stage | str | 0 | 0.0 | 0 | 6 |
| stage_desc | str | 0 | 0.0 | 0 | 6 |
| open_close_ratio_recent | float64 | 62 | 20.0 | 0 | 90 |
| open_close_ratio_prev | float64 | 48 | 15.48 | 0 | 100 |
| active_change_pct | float64 | 13 | 4.19 | 0 | 154 |
| window_recent | str | 0 | 0.0 | 0 | 1 |
| window_prev | str | 0 | 0.0 | 0 | 1 |



## survival

관측 단위: 수준·지역·업종/업태별 생존 요약. 생성 코드: `pipeline/build.py: build_survival`.

검사 키: `level`, `gu`, `dong`, `service`, `category`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| level | str | 0 | 0.0 | 0 | 7 |
| service | str | 398 | 79.44 | 0 | 7 |
| category | str | 242 | 48.3 | 0 | 41 |
| gu | str | 49 | 9.78 | 0 | 9 |
| dong | str | 331 | 66.07 | 0 | 169 |
| n | int64 | 0 | 0.0 | 0 | 366 |
| closed | int64 | 0 | 0.0 | 0 | 334 |
| censored_active | int64 | 0 | 0.0 | 0 | 302 |
| median_survival_years | float64 | 15 | 2.99 | 0 | 104 |
| survival_1y_pct | float64 | 0 | 0.0 | 0 | 205 |
| survival_3y_pct | float64 | 0 | 0.0 | 0 | 261 |
| survival_5y_pct | float64 | 1 | 0.2 | 0 | 265 |
| curve_json | str | 0 | 0.0 | 0 | 477 |



## vacancy_area

관측 단위: 구군/동별 공실 후보 집계. 생성 코드: `pipeline/build.py: build_vacancy_area`.

검사 키: `level`, `gu`, `dong`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| gu | str | 0 | 0.0 | 0 | 9 |
| units_3y | int64 | 0 | 0.0 | 0 | 162 |
| vacant | int64 | 0 | 0.0 | 0 | 79 |
| occupied | int64 | 0 | 0.0 | 0 | 163 |
| vacancy_rate_pct | float64 | 0 | 0.0 | 0 | 117 |
| level | str | 0 | 0.0 | 0 | 2 |
| dong | str | 9 | 3.03 | 0 | 285 |



## poi

관측 단위: 상가정보 점포. 생성 코드: `pipeline/external.py: build_poi`.

검사 키: 미확정. 행 번호를 영구 ID로 사용하지 않는다.

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| name | str | 0 | 0.0 | 0 | 99704 |
| branch | str | 107064 | 90.46 | 0 | 433 |
| cat_l | str | 0 | 0.0 | 0 | 10 |
| cat_m | str | 0 | 0.0 | 0 | 75 |
| cat_s | str | 0 | 0.0 | 0 | 247 |
| gu | str | 0 | 0.0 | 0 | 9 |
| admin_dong | str | 0 | 0.0 | 0 | 150 |
| legal_dong | str | 0 | 0.0 | 0 | 209 |
| floor | str | 53485 | 45.19 | 0 | 58 |
| addr | str | 0 | 0.0 | 0 | 53145 |
| lat | float64 | 0 | 0.0 | 0 | 54854 |
| lon | float64 | 0 | 0.0 | 0 | 54854 |



## area_context

관측 단위: 행정동별 맥락. 생성 코드: `pipeline/external.py: build_area_context`.

검사 키: `gu`, `admin_dong`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| gu | str | 0 | 0.0 | 0 | 9 |
| admin_dong | str | 0 | 0.0 | 0 | 150 |
| poi_total | int64 | 0 | 0.0 | 0 | 145 |
| poi_food | int64 | 0 | 0.0 | 0 | 125 |
| food_share_pct | float64 | 0 | 0.0 | 0 | 112 |
| retail_share_pct | float64 | 0 | 0.0 | 0 | 117 |
| edu_share_pct | float64 | 0 | 0.0 | 0 | 85 |
| office_share_pct | float64 | 0 | 0.0 | 0 | 112 |
| personal_share_pct | float64 | 0 | 0.0 | 0 | 95 |
| lodging_share_pct | float64 | 0 | 0.0 | 0 | 39 |
| pub_share_of_food_pct | float64 | 0 | 0.0 | 0 | 108 |
| diversity_index | float64 | 0 | 0.0 | 0 | 91 |
| top_categories_json | str | 0 | 0.0 | 0 | 150 |
| lat | float64 | 0 | 0.0 | 0 | 150 |
| lon | float64 | 0 | 0.0 | 0 | 150 |
| pop_total | int64 | 0 | 0.0 | 0 | 150 |
| pop_male | int64 | 0 | 0.0 | 0 | 148 |
| pop_female | int64 | 0 | 0.0 | 0 | 150 |
| age_0_14 | int64 | 0 | 0.0 | 0 | 144 |
| age_15_29 | int64 | 0 | 0.0 | 0 | 149 |
| age_30_49 | int64 | 0 | 0.0 | 0 | 147 |
| age_50_64 | int64 | 0 | 0.0 | 0 | 149 |
| age_65_plus | int64 | 0 | 0.0 | 0 | 148 |
| pop_ref_month | str | 0 | 0.0 | 0 | 1 |
| age_0_14_pct | float64 | 0 | 0.0 | 0 | 94 |
| age_15_29_pct | float64 | 0 | 0.0 | 0 | 94 |
| age_30_49_pct | float64 | 0 | 0.0 | 0 | 107 |
| age_50_64_pct | float64 | 0 | 0.0 | 0 | 90 |
| age_65_plus_pct | float64 | 0 | 0.0 | 0 | 122 |
| parking_count | float64 | 0 | 0.0 | 0 | 30 |
| parking_slots | float64 | 0 | 0.0 | 0 | 117 |
| market_count | float64 | 0 | 0.0 | 0 | 7 |
| market_stores | float64 | 0 | 0.0 | 0 | 61 |
| market_type | str | 0 | 0.0 | 0 | 7 |
| market_type_basis | str | 0 | 0.0 | 0 | 148 |
| city_food | float64 | 0 | 0.0 | 0 | 1 |
| city_retail | float64 | 0 | 0.0 | 0 | 1 |
| city_edu | float64 | 0 | 0.0 | 0 | 1 |
| city_office | float64 | 0 | 0.0 | 0 | 1 |
| city_personal | float64 | 0 | 0.0 | 0 | 1 |
| city_lodging | float64 | 0 | 0.0 | 0 | 1 |
| city_pub | float64 | 0 | 0.0 | 0 | 1 |
| city_youth_pct | float64 | 0 | 0.0 | 0 | 1 |
| city_diversity | float64 | 0 | 0.0 | 0 | 1 |



## legal_admin_map

관측 단위: 법정동별 대표 행정동. 생성 코드: `pipeline/external.py: build_poi`.

검사 키: `gu`, `legal_dong`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| gu | str | 0 | 0.0 | 0 | 9 |
| legal_dong | str | 0 | 0.0 | 0 | 209 |
| admin_dong | str | 0 | 0.0 | 0 | 97 |
| n | int64 | 0 | 0.0 | 0 | 177 |
| share | float64 | 0 | 0.0 | 0 | 48 |



## station_traffic

관측 단위: 역별 승하차 요약. 생성 코드: `pipeline/external.py: build_station_traffic`.

검사 키: `station`

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| station | str | 0 | 0.0 | 0 | 94 |
| daily_boarding | float64 | 0 | 0.0 | 0 | 94 |
| daily_alighting | float64 | 0 | 0.0 | 0 | 92 |
| daily_total | float64 | 0 | 0.0 | 0 | 94 |
| morning_07_09_pct | float64 | 0 | 0.0 | 0 | 64 |
| lunch_11_14_pct | float64 | 0 | 0.0 | 0 | 60 |
| evening_17_20_pct | float64 | 0 | 0.0 | 0 | 75 |
| night_22_24_pct | float64 | 0 | 0.0 | 0 | 55 |
| peak_hour | str | 0 | 0.0 | 0 | 9 |
| period | str | 0 | 0.0 | 0 | 1 |



## parking

관측 단위: 주차장. 생성 코드: `pipeline/external.py: build_parking`.

검사 키: 미확정. 행 번호를 영구 ID로 사용하지 않는다.

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| name | str | 0 | 0.0 | 0 | 1078 |
| kind | str | 0 | 0.0 | 0 | 2 |
| addr | str | 0 | 0.0 | 0 | 994 |
| slots | int64 | 0 | 0.0 | 0 | 175 |
| lat | float64 | 0 | 0.0 | 0 | 997 |
| lon | float64 | 0 | 0.0 | 0 | 991 |
| gu | str | 0 | 0.0 | 0 | 9 |



## market

관측 단위: 전통시장. 생성 코드: `pipeline/external.py: build_market`.

검사 키: 미확정. 행 번호를 영구 ID로 사용하지 않는다.

| column | dtype | null | null_pct | blank | distinct_non_null |
| --- | --- | --- | --- | --- | --- |
| name | str | 0 | 0.0 | 0 | 105 |
| kind | str | 0 | 0.0 | 0 | 4 |
| addr | str | 0 | 0.0 | 0 | 105 |
| stores | int64 | 0 | 0.0 | 0 | 77 |
| parking | str | 0 | 0.0 | 0 | 2 |
| lat | float64 | 0 | 0.0 | 0 | 105 |
| lon | float64 | 0 | 0.0 | 0 | 105 |
| gu | str | 0 | 0.0 | 0 | 9 |
