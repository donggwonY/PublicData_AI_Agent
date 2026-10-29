# E-02 데이터 계약 — 앱 데이터 13개 표

작성: 염동권 · 2026-10-29 · 대상: 공유 DB(`uoiamnbkzlvlskngataq`) `app` 스키마 version 3 = 저장소 `service/data/processed` (15업종, 기준일 2026-10-13)

이 문서는 앱이 읽는 표마다 **한 행의 의미, 키, 기준 시점, 만드는 곳, 읽는 곳**을 정한다. 컬럼별 의미와 해석 주의는 김세은의 D-01 사전을 그대로 따르고 여기서 다시 쓰지 않는다([핵심 54개 컬럼](../d01/core_dictionary.md), [나머지 144개](../d01/remaining_dictionary.md), [자료형·결측](../d01/dictionary.md)). D-01 사전은 7업종 스냅샷(2026-09-23) 기준이라 행 수·결측 비율은 지금과 다르다. 결합 규칙은 [D-02 결합 계약](../d02/handoff.md)을 따른다.

아래 검사 결과는 2026-10-29에 현재 parquet로 계산했다. DB v3는 parquet와 행 단위로 같다([E-02 4절](README.md#4-검증-결과), 7절).

## 1. 표별 계약

| 표 | 한 행 | 키 (검사 결과) | DB 제약 | 행 (v3) | 기준 시점 | 만드는 곳 | 읽는 곳 |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| `stores` | 인허가 1건 | `org_code`+`service`+`mgmt_no` 중복 0 | 기본 키 (version_id 포함) | 225,858 | 인허가 2026-10-13 | `pipeline/build.py` | 도구 8개(사이클·생존·자리 이력·위험 자리·지역 비교·주소 정규화·동네 프로필 등) |
| `units` | 자리 1곳(건물 기본주소+층) | `uid` 중복 0 | 기본 키 | 86,386 | 인허가 2026-10-13 | `build.py: build_units` | 공실·자리 이력·위험 자리·지역 비교·주소 정규화·주변 조회 |
| `transitions` | 한 자리의 앞 인허가→다음 인허가 | **미확정**. 완전 중복 행 0 | 없음 | 22,990 | 인허가 2026-10-13 | `build.py: build_transitions` | `transition_matrix` |
| `area_year` | 지역 수준×연도 개·폐업 | `level`+`gu`+`dong`+`year` 중복 0 | 없음 | 6,847 | 인허가 2026-10-13 | `build.py: build_cycle` | 사이클·지역 비교 |
| `area_cycle` | 지역 수준별 사이클 판정 | `level`+`gu`+`dong` 중복 0 | 없음 | 352 | 인허가 2026-10-13 | `build.py: build_cycle` | 사이클·지역 비교·동네 프로필·대시보드 |
| `survival` | 수준·지역·업종/업태별 생존 요약 | `level`+`gu`+`dong`+`service`+`category` 중복 0 | 없음 | 685 | 인허가 2026-10-13, 2010년 이후 개업 코호트 | `build.py: build_survival` | 자리 이력(업태 비교용). 생존곡선 도구는 이 표가 아니라 `stores`로 다시 계산 |
| `vacancy_area` | 구·동별 공실 후보 집계 | `level`+`gu`+`dong` 중복 0 | 없음 | 326 | 인허가 2026-10-13 | `build.py: build_vacancy_area` | 지역 비교·동네 프로필·대시보드 |
| `poi` | 상가정보 점포 기록 | **미확정**. 원천 점포 ID 없음, 완전 중복 673행 | 없음 | 118,357 | 상가정보 2026-06 | `pipeline/external.py: build_poi` | `find_nearby`, 대시보드 지도 |
| `area_context` | 행정동 맥락(인구·업종 구성·상권 유형) | `gu`+`admin_dong` 중복 0 | 없음 | 150 | 인구 `pop_ref_month`(2026-08), 상가 2026-06 | `external.py: build_area_context` | 동네 프로필·대시보드 |
| `legal_admin_map` | 법정동→대표 행정동 | `gu`+`legal_dong` 중복 0 | 없음 | 212 | 상가정보 2026-06에서 학습 | `external.py: build_poi` | 동네 프로필 |
| `station_traffic` | 역별 승하차 요약 | `station` 중복 0 | 없음 | 94 | `period` 컬럼(2026-01~07 평균) | `external.py: build_station_traffic` | `get_station_traffic`·동네 프로필·대시보드 |
| `parking` | 주차장 1곳 | **미확정** | 없음 | 1,086 | 전국주차장 표준데이터, 수집일 미확정 | `external.py: build_parking` | `find_nearby` |
| `market` | 전통시장 1곳 | **미확정** | 없음 | 106 | 원천 데이터셋·기준일 미확정(D-01 `source_refresh.md`) | `external.py: build_market` | `find_nearby` |

"읽는 곳"은 `core/tools.py` 각 도구 함수와 그 보조 함수가 `DataStore`의 어떤 표를 참조하는지 코드로 확인한 결과다. 13개 표는 모두 어딘가에서 쓰인다.

### 버전·메타 표 (DB 전용)

| 표 | 한 행 | 키 | 내용 |
| --- | --- | --- | --- |
| `dataset_versions` | 데이터 버전 1개 | `version_id` 기본 키 | 상태(`loading`→`validated`/`failed`→`current`→`retired`), 기준일, 업종, `meta.json` 원문(`meta_text`), 자료형(`dtypes`), 표별 행 수 |
| `current_version` | 항상 1행 | `singleton` 기본 키·검사 제약 | 앱이 읽을 `version_id` → 3 |

## 2. 공통 규칙

- **버전**: 데이터 표 13개는 모두 `version_id`(→ `dataset_versions`, 버전 삭제 시 함께 삭제)와 `_row`(parquet 원래 행 순서)를 가진다. 앱은 `current_version`이 가리키는 버전만 읽는다. 버전 안의 13개 표는 같은 배치에서 나온 한 묶음이며, 표 하나만 다른 버전으로 바꾸지 않는다.
- **기준 시점은 표마다 다르다**: 인허가 7개 표는 `meta.json`의 `reference_date`(2026-10-13)를 따른다. 보조 6개 표는 위 표의 기준 시점을 따르고, 인허가 기준일을 덮어쓰지 않는다(D-02 권고).
- **자료형 복원**: DB 컬럼형과 pandas 자료형이 1:1이 아니라(예: 결측 있는 bool), 앱은 `dataset_versions.dtypes`로 원래 자료형을 되살린다. 숫자는 `extra_float_digits=3`으로 읽어 parquet 값과 비트 단위로 같게 한다.
- **식별자 아님**: `_row`, `transitions`·`poi`·`parking`·`market`의 행 번호는 영구 ID가 아니다. 다른 버전 사이에서 이 값으로 행을 이어 붙이지 않는다.
- **`uid`의 한계**: `uid`는 층 보충 규칙(80%)에 따라 바뀔 수 있다(D-02: 60/80/100%에서 7업종 자리 74,952/76,363/76,884곳). 버전이 다르면 같은 `uid`가 같은 자리라고 가정하지 않는다.

## 3. 결합 계약과 현재 검사 결과

D-02 결합 계약의 키를 그대로 쓰고, 15업종 데이터에서 다시 쟀다.

| 결합 | 관계 | 2026-10-29 결과 | 비고 |
| --- | --- | --- | --- |
| `stores` → `units` (`uid`) | 다대일 | 연결 실패 0 | |
| `transitions` → `units` (`uid`) | 다대일 | 연결 실패 0 | 한 자리에 전이 여러 개 가능 |
| `stores` (`gu`,`dong`) → `legal_admin_map` (`gu`,`legal_dong`) → `area_context` (`gu`,`admin_dong`) | 다대일 | 미연결 3,008 / 225,858 (1.33%), 행 수 보존 | D-01 7업종 기준 1,776 / 197,356 (0.90%). 15업종 확장으로 늘었다. 원인 분류(D-01의 남구 407건 등)는 15업종에서 다시 하지 않았다 → D-04 |
| 대표 매핑 `share` < 1 | — | 재측정 안 함 | 오배정 확정 수가 아니다(D-02) |

미연결 행은 지우지 않고 보존한다. 행정동 맥락이 필요한 분석은 제외 수와 지역별 비율을 같이 보고한다(D-01·D-02).

## 4. 조회 패턴

- **앱 시작**: `core/datasource.py`가 현재 버전의 13개 표를 표마다 `COPY … TO STDOUT (FORMAT csv)` 한 번씩, 총 13회로 통째로 읽는다(2026-10-17 대상 DB `pg_stat_statements`로 확인). 약 150MB 전송. 이후 프로세스가 끝날 때까지 DB를 다시 읽지 않는다.
- **도구 조회**: 모두 메모리의 pandas에서 한다 — 주소 부분 일치(건물번호는 경계 검사), 동 이름 앞부분 일치, 반경(구면 거리), 업태·업종별 집계, `stores`로 생존곡선 재계산. SQL로 옮기지 않았다.
- **인덱스**: 모든 표 (`version_id`,`_row`) — 앱의 버전 단위 읽기와 순서 복원용. `stores`·`units`의 (`version_id`,`gu`,`dong`), `stores`·`transitions`의 (`version_id`,`uid`) — 지금은 쓰지 않고, 필요한 행만 조회하는 구조(E-03·E-04)로 바꿀 때를 대비했다.
- 분석·실험은 `app` 표를 읽기만 한다. 실험 결과를 `app` 표에 쓰지 않는다([작업 흐름](../TEAM_WORKFLOW.md) 공유 DB 기준).

## 5. 새 버전을 올릴 때 확인할 것

지금 자동으로 하는 것과 사람이 확인해야 하는 것을 나눈다.

| 검사 | 지금 | 방법 |
| --- | --- | --- |
| 표별 행 수 DB = parquet | 자동 | `load_supabase.py`가 적재 후 비교해 다르면 `failed` |
| DB 용량 한도 | 자동 | `--max-db-mb`(기본 450) 초과 시 중단 |
| `stores`·`units` 키 유일성 | 자동 | DB 기본 키 위반이면 적재 실패 |
| 나머지 표 키 유일성 (1절 "중복 0" 항목) | **수동** | 이 문서 1절 검사 반복 |
| `stores`·`transitions` → `units` 연결 0 실패 | **수동** | 3절 |
| 행정동 미연결 비율 급변 | **수동** | 3절. 1.33%에서 크게 달라지면 원인 확인 |
| 기준일이 이전 버전보다 앞으로 | **수동** | `meta.json` `reference_date` |
| 앱 화면·도구 결과 | **수동** | 공개 앱 사이드바 버전·기준일·누적 수치 |

수동 항목을 적재 스크립트의 검증 단계로 옮기는 일은 E-04(자동 검사)에서 한다.

## 6. 변경 규칙

- 키 컬럼, 표의 한 행 의미, 생존·공실·자리 정의를 바꾸면 김세은과 확인하고 D-01·D-02 문서와 이 문서를 같이 고친다.
- 컬럼을 추가·삭제하면 이 문서 1절과 D-01 사전에 반영한다. 앱 코드가 그 컬럼을 쓰는지 `core/tools.py`에서 확인한다.
- 7업종 스냅샷(`service/data/snapshots/20260923_7services/`)과 D-01 manifest 해시는 바꾸지 않는다.
- 미확정 키(`transitions`·`poi`·`parking`·`market`)를 확정하려면 원천 ID 확보가 먼저다(D-01 closeout). 그 전에는 행 번호로 버전 간 비교를 하지 않는다.

## 7. 남은 질문

- `poi` 완전 중복 673행: 원천 상가업소번호가 없어 실제 중복인지 다른 점포인지 모른다(D-01과 같은 수, 상가정보를 다시 만들지 않았기 때문).
- `market` 원천 데이터셋과 기준일, `parking` 수집일 미확정.
- 행정동 미연결이 0.90%→1.33%로 늘어난 원인 분류(새 업종 주소 형식 등) → D-04.
