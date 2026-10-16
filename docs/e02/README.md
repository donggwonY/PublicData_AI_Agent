# E-02 데이터 계약·Supabase 이행 설계

담당: 염동권 · 시작: 2026-10-14 · 상태: 진행(1단계 기준 데이터 비교 완료, 2단계 15업종 시험 적재 완료 — [9절](#9-2단계-15업종-시험-적재-2026-10-16))

## 이번 단계의 범위

| 항목 | 내용 |
| --- | --- |
| 사용자 질문 | 앱 데이터를 Supabase로 옮길 때 무엇을 기준으로 삼고, 옮긴 뒤 무엇이 같아야 하는가 |
| 산출물 | 이 문서: 앱이 실제로 쓰는 표·컬럼, 김세은 Supabase DB 현황, 둘의 대응, 선택지와 추천안, 이전 전후 검증 항목, 확인 질문 |
| 완료 기준 | 수치는 코드 검색 또는 DB 조회로 뒷받침한다. 에이전트 추천과 결정된 사항을 구분한다. 테이블 생성·적재는 이번 범위가 아니다 |

이 문서의 추천은 **에이전트의 제안**이며 아직 결정되지 않았다. 결정은 염동권과 관리자가 하고, 김세은 DB를 바꾸는 일은 김세은과 확인한 뒤 한다.

## 1. 요약

- 김세은 Supabase DB는 앱 데이터(`service/data/processed`)를 옮긴 것이 아니다. 음식 3종을 따로 정제한 분석 데이터와 보조 원본 자료를 담은 별도 DB다.
- 앱의 도구 11개는 `uid`(주소+층 자리), 7개 업종, 생존·사이클·공실 집계에 맞춰 짜여 있다. 김세은 DB에는 이 정의와 집계가 없다.
- DB 크기는 390MB다. Supabase 무료 등급 한도가 500MB라면(에이전트 이해, 미확인) 앱 데이터를 같은 프로젝트에 더 넣기 어렵다.
- **에이전트 추천**: 앱 데이터 13개 표를 서비스 계약의 기준으로 삼고, 김세은 DB는 분석용으로 유지한다. 앱용 테이블은 별도 공간에 적재하고, 첫 단계는 앱 시작 시 parquet 대신 DB에서 읽는 최소 변경으로 한다(5절).

## 2. 앱이 실제로 쓰는 데이터 (2026-10-14, 코드 검색)

`service/core/tools.py`의 `DataStore`가 앱 시작 시 parquet 13개를 모두 메모리에 올리고, 도구 11개(`TOOL_FUNCTIONS`)가 pandas로 걸러 쓴다. 아래 "사용 컬럼"은 `core/tools.py`·`app.py`·`ui_visuals.py`·`mcp_server.py`·`agent.py`에서 컬럼 이름이 문자열로 등장하는지 검색한 근사치다. 속성 접근 등으로 쓰이는 컬럼은 빠질 수 있다.

| 표 | 행 | 컬럼 | 사용 컬럼(근사) | 메모리 | 쓰는 곳 |
| --- | ---: | ---: | ---: | ---: | --- |
| stores | 197,356 | 20 | 15 | 85.9MB | tools 20곳 |
| units | 76,363 | 34 | 28 | 41.8MB | tools 14곳 |
| poi | 118,357 | 12 | 11 | 25.5MB | tools, app, agent |
| transitions | 22,945 | 14 | 14 | 5.5MB | tools |
| area_year | 6,279 | 8 | 8 | 0.5MB | tools |
| survival | 501 | 13 | 11 | 0.2MB | tools |
| area_cycle | 310 | 16 | 16 | 0.1MB | tools, app |
| vacancy_area | 297 | 7 | 6 | 0.0MB | tools, app |
| area_context | 150 | 44 | 34 | 0.1MB | tools, app, agent |
| legal_admin_map | 212 | 5 | 4 | 0.0MB | tools |
| station_traffic | 94 | 10 | 10 | 0.0MB | tools, app, agent |
| parking | 1,086 | 7 | 6 | 0.1MB | tools |
| market | 106 | 8 | 7 | 0.0MB | tools |

설계에 영향을 주는 관찰:

- `stores`의 `org_code`·`mgmt_no`는 앱 코드에서 쓰이지 않는다. 그러나 D-02 [결합 계약](../d02/handoff.md)상 인허가 식별자는 `org_code + service + mgmt_no`이므로 DB에서는 기본 키로 둔다.
- `get_survival_curve`는 `survival` 요약표가 아니라 `stores` 행으로 Kaplan–Meier를 그때그때 다시 계산한다. `survival.curve_json`은 앱에서 쓰이지 않는다. 따라서 `stores` 원 행이 DB에 있어야 한다.
- 조회 방식: 주소·상호 부분 일치(`str.contains`), 동 이름 앞부분 일치, 반경 계산(구면 거리, `find_nearby`), 업태별 `groupby`. 이것을 SQL로 옮기면 텍스트 검색 인덱스와 좌표 인덱스가 필요하다. 첫 단계에서는 옮기지 않는다.
- 앱 화면은 `meta.json`(기준일, 품질 수치)을 직접 읽는다. DB에도 데이터 버전·기준일 표가 필요하다.

## 3. 김세은 Supabase DB 현황 (2026-10-14 13:17 UTC 조회)

프로젝트 `ecqrnkvehsbxinmeukqf`, 조직 "김세은". Supabase MCP(읽기 전용)로 조회했다. DB 전체 390MB.

| 테이블 | 행 | 컬럼 | 크기 | 내용 |
| --- | ---: | ---: | ---: | --- |
| food_clean | 132,183 | 44 | 118MB | 음식 3종 인허가 1건당 1행. 원본 컬럼 + 파생 컬럼. 기본 키 `관리번호`. 원본 `01_전체정제외식업데이터.csv`, 분석 기준 2026-09-13 22:18 |
| food_high (뷰) | 92,356 | 44 | — | `food_clean` 중 `자리신뢰도 = 'HIGH'` |
| unit_summary | 76,840 | 14 | 25MB | 자리(`자리후보키`) 1곳당 1행. 원본 `03_자리별요약데이터.csv` |
| food_transitions | 15,516 | 50 | 16MB | 폐업 후 같은 자리 다음 가게. 원본 `04_업종전이_영업공백데이터.csv` |
| data_dictionary | 35 | 4 | — | 변수 설명(`05_변수설명서.csv`) |
| aux_shops | 118,357 | 42 | 76MB | 상가(상권)정보 대구 2026-06 원본 컬럼 |
| aux_subway_daily | 39,856 | 30 | 14MB | 역별·일별·시간대별 승하차 1~7월, `source_year` 비어 있음(`unverified`) |
| aux_subway_boarding / alighting | 345 / 247 | 99 | — | 월별 승차·하차 |
| aux_parking / aux_markets / aux_population | 1,086 / 106 / 152 | 37 / 19 / 233 | — | 주차장, 전통시장, 행정동 인구(2026-08-31) |
| aux_import_rows | 165,982 | 5 | 127MB | 보조 자료 적재용 원본 줄 보관(스테이징) |

- 업종별: 일반음식점 97,189, 휴게음식점 30,993, 제과점영업 4,001.
- 자리 신뢰도: HIGH 92,356행, REVIEW 39,827행.
- **자리 수 차이의 원인 확인**: `food_clean`의 서로 다른 `자리후보키` 89,190개 중 `unit_summary`에 없는 12,350개는 모두 MULTI 자리이고, 그 행 39,827건은 전부 REVIEW다. 즉 `unit_summary`는 신뢰도 HIGH 자리만 담는다. 반대로 `unit_summary`에만 있는 자리는 0개다. 의도한 설계인지는 김세은 확인이 필요하다.
- 접근 권한: 12개 테이블 모두 RLS가 켜져 있고 SELECT 허용 규칙이 있다. `anon`·`authenticated`에는 테이블 권한(GRANT)이 없어 공개용 키로는 읽히지 않는다. `aux_` 테이블은 원본 자료이므로 저장소의 "원본 비공개" 원칙상 공개 키 접근을 열지 않는 편이 맞다.

## 4. 앱 데이터와의 대응

| 앱 표 | 김세은 DB | 대응 상태 |
| --- | --- | --- |
| stores (7업종, 197,356) | food_clean (음식 3종, 132,183) | 부분. 음식 3종 건수가 다르다(앱 132,087 / DB 132,183). 기준일(2026-09-23 / 2026-09-13)과 정제 규칙이 다르다 |
| units (`uid` = 주소+층, 76,363) | unit_summary (`자리후보키` = 건물주소·10m 좌표, HIGH만 76,840) | 정의가 다르다. 서로 바꿔 쓸 수 없다 |
| transitions (22,945) | food_transitions (15,516) | 정의가 다르다 |
| survival, area_cycle, area_year, vacancy_area | 없음 | 앱 전용 집계 |
| poi | aux_shops | 원본 대 가공본. 앱 `poi`는 12개 컬럼으로 줄인 것 |
| station_traffic | aux_subway_daily 등 | 원본 대 집계 |
| parking, market | aux_parking, aux_markets | 원본 대 가공본 |
| area_context, legal_admin_map | aux_population(일부) | 앱 전용 가공 결과 |
| meta.json | 없음 | 앱 전용 |

## 5. 선택지와 추천

| | A. 앱 데이터를 기준으로 적재 (추천) | B. 김세은 DB를 기준으로 앱 전환 | C. 당분간 parquet 유지 |
| --- | --- | --- | --- |
| 방식 | 13개 표를 그대로 앱용 테이블로 적재. 김세은 DB는 분석용 | 도구 11개를 `food_clean` 등에 맞게 재작성 | DB 이전을 미루고 R1·R2만 배치 쪽에서 해결 |
| 장점 | 도구 결과가 지금과 같음을 행 단위로 검증 가능. D-01·D-02 검증이 그대로 유효 | 데이터가 한 곳에 모임 | 비용 없음 |
| 단점 | 저장 공간이 따로 필요 | 7업종 확장분·생존/사이클 집계가 사라짐. D-02 정의 검증을 다시 해야 함 | Supabase 목표가 늦어짐 |
| 저장 공간 | 앱 표 메모리 합계 약 160MB. Postgres 크기는 인덱스 포함 추정 필요(미측정) | 기존 DB 사용 | — |

추천 근거: 서비스 숫자가 지금과 같다는 것을 증명하는 것이 이전의 첫 목표다. A는 비교 대상이 명확하고(같은 13개 표), B는 결과가 바뀌는 것이 정상이라 이전 검증과 정의 변경 검증이 섞인다.

A를 택할 경우 첫 구현 범위(제안):

1. 적재 공간: 김세은 프로젝트에 공간을 만들려면 스테이징 127MB 정리가 필요하다(김세은 결정). 그렇지 않으면 염동권 소유의 별도 프로젝트를 만든다. 어느 쪽이든 앱용 스키마(예: `app`)를 분석 테이블과 분리한다.
2. 버전 관리: 모든 앱 테이블에 `dataset_version`을 두고, `dataset_versions` 표에 기준일·빌드 시각·행 수·상태를 기록한다. 새 버전을 다 적재하고 검증한 뒤에만 "현재 버전"을 바꾼다. 이 방식이 E-01의 R1·R2(저장 도중 실패 시 섞임)를 막는다.
3. 앱 변경 최소화: `DataStore`가 시작 시 parquet 대신 현재 버전의 DB 테이블을 읽는다. 도구 코드는 바꾸지 않는다. DB 연결에 실패하면 저장소의 parquet로 대체한다.
4. 비밀값: 앱은 서버에서 DB 비밀값으로 읽는다(Streamlit Cloud Secrets). 공개 키 읽기 권한은 열지 않는다.

## 6. 이전 전후 검증 항목 (A 기준)

| 검사 | 기준 |
| --- | --- |
| 표별 행 수 | parquet 13개와 같음 |
| 키 유일성 | `stores`(org_code, service, mgmt_no), `units.uid` 중복 0 |
| 관계 | `stores.uid`, `transitions.uid`가 모두 `units`에 존재 |
| D-01 일치 검사 10개 | [`scripts/profile_data.py`](../../scripts/profile_data.py)의 검사를 DB에서 읽은 데이터로 재실행해 통과 |
| 값 동일성 | 표별로 정렬 후 pandas `equals`. 날짜·불리언·결측 자료형 보존 확인 |
| 도구 결과 | `tests.smoke_test`의 도구 호출 결과가 parquet 경로와 DB 경로에서 같음 |
| 기준일 | 앱 사이드바 기준일·누적 수치가 `meta.json`과 같음 |
| 실패 처리 | 적재 도중 중단 시 현재 버전이 바뀌지 않음 |

## 7. 김세은에게 확인할 것

1. 이 DB는 분석·실험용인가, 서비스에 쓸 생각인가?
2. `unit_summary`가 신뢰도 HIGH 자리만 담는 것은 의도한 설계인가? (REVIEW 자리 12,350개, 39,827행 제외)
3. `aux_import_rows`(127MB 스테이징)를 지워도 되는가? 앱 데이터를 같은 프로젝트에 둘 공간이 생기는지와 연결된다.
4. `food_clean` 기준일 2026-09-13과 정제 규칙은 어디에 기록돼 있는가? 저장소에 테이블 생성 SQL·적재 스크립트를 올릴 수 있는가?
5. 기본 키가 `관리번호` 하나인데, D-02 전달 문서의 `org_code + service + mgmt_no`와 맞출 계획이 있는가?

## 8. 재현

- 앱 사용 현황: `service/` 가상환경에서 parquet 13개의 컬럼을 위 5개 파일에서 문자열 검색(일회성 점검, 스크립트 미보관).
- DB 현황: Supabase MCP 읽기 전용 `execute_sql`. 테이블 크기는 `pg_total_relation_size`, 자리 차이는 `food_clean`의 고유 `자리후보키`를 `unit_summary`와 left join해 접두어(SINGLE/MULTI)와 `자리신뢰도`별로 집계했다.
- DB는 변경하지 않았다.

## 9. 2단계: 15업종 시험 적재 (2026-10-16)

### 9-1. 결정 사항 (2026-10-15 4차 회의, 이후 염동권 결정)

- 기준 데이터: 앱 데이터(배치 산출물 13개 표)를 서비스 기준으로 적재한다(5절 A안).
- 업종: 기존 7개 + 1차 8개(의원·병원, 약국, 체력단련장업, 인터넷컴퓨터게임시설제공업, 당구장업, 체육도장업, 골프연습장업, 축산판매업) = 15개. 근거는 4차 회의록.
- 적재 위치: 염동권 소유의 새 Supabase 프로젝트(무료 플랜, 서울 리전). 김세은 프로젝트(390MB 사용)에는 공간이 부족하다.

### 9-2. 무료 플랜 조건 (2026-10-15 supabase.com/pricing 확인)

| 항목 | Free | Pro ($25/월) |
| --- | --- | --- |
| DB 크기 | 프로젝트당 500MB | 프로젝트당 8GB |
| 데이터 전송량(egress) | 월 5GB | 월 250GB |
| 비활성 | 1주일 비활성 시 일시정지 | 정지 없음 |
| 프로젝트 수 | 활성 2개 | 첫 프로젝트 포함, 추가 $10/월부터 |
| 백업 | 없음 | 매일(7일 보관) |

### 9-3. 시험 데이터

- 원본: 행정안전부 인허가 대구광역시 압축 파일(195개 업종, 2026-10-13까지). 15업종에 해당하는 16개 CSV만 골라 임시 폴더에서 기존 `pipeline/build.py`를 코드 수정 없이 실행(19초). 보조 데이터 6개 표는 업종과 무관해 현재 `service/data/processed`의 것을 사용했다.
- 결과: 인허가 225,858건(기존 7업종 197,356), 자리 86,386곳(76,363), 영업 중 71,543, 기준일 2026-10-13.
- 주의: 배치는 파일 이름에 업종명이 들어 있는지로 업종을 판별한다. "병원"은 "동물병원", "약국"은 "동물약국" 파일에도 걸리므로, 원본 전체를 `data/raw`에 넣기 전에 정확히 일치하는 판별로 바꿔야 한다. 이번 시험은 필요한 파일만 넣어 피했다.
- 앱 데이터(`service/data/processed`)와 `deploy` 브랜치는 바꾸지 않았다.

### 9-4. 적재 방식 (`service/pipeline/load_supabase.py`)

- 스키마 `app`에 parquet 13개를 같은 이름의 표로 만들고, 모든 행에 `version_id`를 붙인다. 자료형은 parquet에서 정한다(불리언·timestamp·bigint·double precision·text).
- `app.dataset_versions`: 버전별 상태(`loading` → `validated`/`failed` → `current` → `retired`), 기준일, 업종 목록, `meta.json` 전체, 표별 행 수.
- `app.current_version`: 앱이 읽을 버전 한 줄. `--activate`를 줄 때만 바뀐다. 적재 도중 실패해도 서비스 버전은 섞이지 않는다(E-01 R1·R2 대응).
- 기본 키: `stores`는 (version_id, org_code, service, mgmt_no), `units`는 (version_id, uid). 조회용 인덱스는 (version_id, uid), (version_id, gu, dong) 등.
- 권한: 모든 표에 RLS를 켜고 `anon`·`authenticated` 권한을 회수했다. `app` 스키마는 공개 API 대상이 아니다. 접속 정보는 로컬 `.env`의 `APP_DATABASE_URL`(Session pooler)에서 읽고 출력하지 않는다.
- 의존성: `psycopg[binary]==3.3.6`(`requirements-dev.txt`, 로컬 적재 전용).

### 9-5. 결과 (version_id 1, 상태 `validated`, 현재 버전으로 교체하지 않음)

| 항목 | 결과 |
| --- | --- |
| 소요 시간 | 24초 (stores 12.7초, units 5.1초, poi 2.7초) |
| 행 수 | 13개 표 모두 parquet와 일치 |
| 값 대조 (stores) | 폐업 154,315건, 영업일수 합 681,041,510, 최초 개업 1960-03-29, 최근 폐업 2026-10-13, 자리 86,386곳, 평균 위도 35.860910 — parquet와 모두 일치 |
| 값 대조 (units) | 공실 후보 38,533곳, 최근 공실(90일~3년) 5,729곳, 인허가 합계 225,858 — 일치 |
| 크기 | `app` 스키마 214MB(stores 128MB, units 52MB, poi 24MB, transitions 7MB), DB 전체 225MB |
| 추정 대비 | 사전 추정 약 239MB(9-2 이전 계산) → 실측 214MB |
| 권한 | `anon`의 `app` 스키마 사용 권한·`stores` 조회 권한 없음, RLS 켜짐 |

### 9-6. 해석과 남은 일

- 무료 플랜 500MB에 한 버전(약 214MB)은 충분히 들어간다. 버전 교체 시 두 버전이 함께 있으면 약 440MB로, 한도 안이지만 여유가 작다. 교체 뒤 이전 버전을 바로 지우는 운영 규칙이 필요하다.
- 아직 확인하지 않은 것: 앱이 DB에서 읽을 때의 시작 시간과 전송량(egress 월 5GB 대비), 1주일 비활성 일시정지가 공개 앱에 주는 영향.
- 다음 단계: (1) `DataStore`가 `current_version`의 표를 읽는 경로와 parquet 대체 경로 구현 및 smoke test 결과 동일성 확인, (2) 앱 시작 1회당 전송량 측정, (3) 배치의 업종 판별을 정확 일치로 수정하고 15업종 원본으로 정식 배치, (4) 김세은 D-01·D-02 검증을 15업종 데이터로 재실행.

### 9-7. 앱의 DB 읽기 경로 (2026-10-16)

구현:

- `service/core/datasource.py`(새 파일): 환경변수로 출처를 고른다. `APP_DATA_SOURCE` = `auto`(기본, `APP_DATABASE_URL`이 있으면 DB, 실패하면 parquet) · `db`(DB만, 실패 시 오류 — 검증용) · `parquet`. `APP_DATA_VERSION`이 없으면 `app.current_version`을 읽는다. 검증되지 않은 버전은 읽지 않는다.
- `DataStore`는 출처에서 받은 표를 그대로 쓴다. 도구 11개는 바꾸지 않았다. `S.source`(예: `db v2`)를 사이드바 기준일 옆에 표시한다.
- `app.py`: Streamlit Secrets의 `APP_DATABASE_URL`·`APP_DATA_SOURCE`·`APP_DATA_VERSION`을 서버 환경변수로 옮긴다. Secrets가 없으면 지금처럼 parquet를 쓴다. 배포 의존성(`requirements.txt`)에는 아직 `psycopg`가 없어서, 지금 배포본은 `auto` 모드에서 parquet로 동작한다.
- 적재 스크립트 보완: 원래 행 순서 `_row`, 키 순서를 보존한 `meta_text`, pandas 자료형 `dtypes`를 함께 저장한다. 읽을 때 `extra_float_digits = 3`과 `float_precision="round_trip"`으로 실수 값을 잘림 없이 복원한다.

같은 데이터에서 parquet 경로와 DB 경로를 비교했다(15업종 시험 데이터, DB version 2).

| 비교 | 결과 |
| --- | --- |
| 13개 표 (값·자료형, 오차 허용 없음) | 모두 일치 |
| smoke test 도구 호출 20건 결과 (JSON 문자열) | 20/20 일치 |
| 처음 비교에서 나온 차이와 원인 | 업종 목록 순서(jsonb 키 재정렬) · 좌표 마지막 자리(서버 실수 출력 자릿수, pandas CSV 파싱) · `transitions.to_closed` 자료형 — 모두 위 보완으로 해결 |
| 로컬 앱 (`APP_DATA_SOURCE=db`, version 2) | 사이드바 15업종 누적 225,858건·기준일 2026-10-13·"데이터 db v2", 대시보드 정상, 서버 오류 없음 |
| 연결 실패 시 | `auto`는 parquet로 대체하고 사유(예: `ConnectionTimeout`)를 기록, `db`는 오류로 중단 |
| 기본 경로 회귀 | 환경변수 없이 단위 14개 OK, smoke test ALL PASSED (parquet 경로) |

측정 (로컬 PC → Supabase 서울, Session pooler):

| 항목 | 값 |
| --- | --- |
| 앱 시작 시 데이터 읽기 시간 | DB 8~15초 (parquet 0.1초) |
| 앱 시작 1회당 받는 데이터 | 약 150MB (CSV 기준, egress 근사) |
| 무료 플랜 egress 월 5GB 기준 | 앱 시작 약 33회/월이면 한도 도달 |
| DB 크기 | 457MB (version 1·2 공존, 무료 한도 500MB에 근접) |

해석:

- 지금 구조(시작할 때 표 전체를 읽음)는 무료 플랜 전송량과 맞지 않는다. Streamlit Community Cloud 앱은 잠들었다 깰 때·재배포 때마다 다시 시작하므로 공개 운영 시 월 33회를 넘기 쉽다(재시작 횟수는 미측정).
- 선택지: (a) Pro 플랜(egress 월 250GB, 약 1,600회), (b) 앱이 필요한 행만 SQL로 조회하도록 도구를 바꿈(구조 변경 큼), (c) 배포는 당분간 parquet를 유지하고 DB는 적재·검증·분석 공유용으로 사용.
- version 1(`_row` 없는 첫 시험분)은 더 쓰지 않는다. 정리하면 공간이 확보되지만 행 삭제만으로는 디스크 크기가 바로 줄지 않아 표 재작성이 필요하다(소유자 확인 후 진행).

### 9-8. 한 버전만 유지 (2026-10-16)

- 염동권 결정: DB에는 한 버전만 둔다. 무료 플랜(500MB)에서 교체 중 두 버전이 겹치는 문제를 피하고, 되돌리기는 저장소의 parquet로 다시 적재한다.
- 적재 스크립트 옵션 추가: `--fresh`(적재 전에 `app` 스키마를 비움), `--start-version`(버전 번호 시작값), `--max-db-mb`(표마다 DB 크기를 확인해 넘으면 중단, 기본 450MB).
- 실행: `--fresh --start-version 2`로 같은 시험 데이터를 다시 넣어 version 2만 남겼다(45초). DB 457MB → 240MB. `_row` 컬럼과 순서 인덱스가 추가돼 처음 적재(225MB)보다 약간 크다.
- 재검증: parquet 경로와 도구 결과 20/20 일치, 공개 키 접근 차단 유지, `current_version`은 아직 비어 있음(서비스 버전 미지정).

### 9-9. 15업종 정식 반영 (2026-10-16)

| 단계 | 내용 | 검증 |
| --- | --- | --- |
| 1. 업종 판별 수정 | `pipeline/build.py`: 파일 이름 `분류_업종명[_지역].csv`의 두 번째 칸이 `config.SERVICES`와 정확히 같을 때만 읽음. `config.SERVICES`에 9개 이름 추가 | 압축 파일 195개 중 정확히 16개만 선택(동물병원·동물약국 제외), 기존 이름 형식도 인식 |
| 2. 정식 배치 | 16개 원본을 `service/data/raw`(Git 제외)에 두고 `python -m pipeline.build` 실행(18초) | 7개 산출 표가 시험 배치와 완전 일치. 인허가 225,858 · 자리 86,386 · 기준일 2026-10-13 |
| 기존 검증 보존 | 확장 이전 14개 파일을 `service/data/snapshots/20260923_7services/`에 그대로 복사(바이트 일치). D-01·D-02 스크립트 10개와 `tests/test_snapshot_hashes.py`의 데이터 경로만 이 폴더로 변경. 기대 해시는 바꾸지 않음 | D-01·D-02 오프라인 스크립트 8개 재실행 통과, 분석 수치 변화 없음(코드 지문 기록만 달라져 원본 보고서는 유지) |
| 3. 테스트 | `service/` 단위 14개·smoke ALL PASSED·에이전트 루프 2개·MCP 점검 통과. 저장소 테스트 26개 중 24개 통과 | 실패 2개는 이전부터 있던 Windows 파일 권한 검사 |
| 4. DB 재적재 | `--fresh --start-version 3`으로 정식 데이터를 version 3으로 적재(43초, 240MB). 현재 버전 지정은 하지 않음 | parquet 경로와 도구 결과 20/20 일치 |

주의:

- 보조 데이터(poi·station_traffic 등 6개 표)는 이번에 다시 만들지 않아 확장 이전과 같은 파일이다. A-01 스크립트(보조 데이터만 사용)는 그대로 동작한다.
- `scripts/profile_data.py --demo service`는 `service/data/processed`로 D-01 manifest를 새로 쓰는 생성기다. 실행하면 기록된 9/23 해시가 15업종 해시로 바뀌므로, D-01을 다시 만들 때가 아니면 실행하지 않는다.
- 공개 앱(`deploy`)은 아직 7업종이다. 15업종 반영은 `main` 푸시 후 `deploy` 갱신(소유자 결정) 때 이루어진다.

### 9-10. 공개 앱의 DB 전환 준비 (2026-10-16)

- 결정(염동권): 공개 앱이 parquet 대신 DB를 읽도록 전환한다. egress(월 5GB, 앱 시작 1회 약 150MB) 위험은 `auto` 모드의 parquet 대체로 서비스 중단을 막는 전제로 감수한다.
- 배포 의존성: `service/requirements.txt`에 `psycopg[binary]==3.3.6` 추가(적재 스크립트도 같은 버전 사용, `requirements-dev.txt`는 이를 포함).
- 서비스 버전 지정: `--activate-version` 옵션 추가 후 version 3을 `app.current_version`으로 지정.
- 앱 전용 계정 `app_reader`: `app` 스키마 읽기만 허용(표마다 SELECT 권한 + RLS 읽기 정책). 적재 스크립트가 표를 만들 때마다 권한을 다시 적용한다. 비밀번호는 무작위로 만들어 로컬 `.env`의 `APP_READER_DATABASE_URL`에만 두었고 문서·로그에 남기지 않았다.
- 확인: `app_reader`로 version 3 인허가 225,858건 조회 가능, 삭제·표 생성·수정은 모두 권한 없음. 이 계정으로 `auto` 모드 실행 시 `db v3`에서 읽음(14.6초).
- 공개 앱 적용 순서: `main`·`deploy` 푸시 → 소유자가 Streamlit Secrets에 `APP_DATABASE_URL`(=`APP_READER_DATABASE_URL` 값) 추가 → Reboot → 로그와 사이드바 "데이터 db v3" 확인.
- 적용 결과(2026-10-16 06:38 UTC Reboot, `deploy` d16af85): 설치 로그에 `psycopg==3.3.6`·`psycopg-binary==3.3.6` 포함 61개 패키지, 오류 없이 서버 시작. 공개 화면 사이드바 "기준일 2026-10-13 · 배치 2026-10-16 14:46:59 · 데이터 db v3", 누적 225,858·폐업 154,315·영업 중 71,543, 대시보드(쇠퇴 진입기·중앙생존 5.5년·최근 공실 후보 4,145곳·새 업종 표시) 정상. 남은 확인: Supabase egress 사용량 추이, 공개 서버 메모리.
