# E-02 데이터 계약·Supabase 이행

담당: 염동권 · 기간: 2026-10-14 ~ · 상태: **진행** — 공개 앱 DB 전환 완료(2026-10-16), 운영 확인 중

이 문서는 앱 데이터를 Supabase(PostgreSQL)로 옮긴 과정과 지금 구성을 정리한다. 앞부분(1~6절)은 **현재 상태와 운영 방법**, 뒷부분(부록)은 **조사·시험 기록**이다. 수치는 코드 실행·DB 조회로 확인한 값이며, 확인하지 못한 것은 "미확인"으로 표시한다.

## 한눈에 보기

| 항목 | 현재 |
| --- | --- |
| 공개 앱 | [pubdai.streamlit.app](https://pubdai.streamlit.app) (`deploy` d16af85) — 사이드바 "데이터 db v3" |
| 데이터 출처 | 염동권 소유 Supabase 프로젝트(무료 플랜, 서울)의 `app` 스키마. DB 실패 시 저장소 parquet로 자동 대체 |
| 데이터 | 15업종 인허가 225,858건 · 자리 86,386곳 · 기준일 2026-10-13 (DB version 3) |
| DB 크기 | 240MB / 무료 한도 500MB (한 버전만 유지) |
| 앱 접속 계정 | `app_reader` — `app` 스키마 읽기 전용 |
| 검증 | DB 경로와 parquet 경로의 13개 표·도구 결과 20건 완전 일치 |
| 남은 위험 | 앱 시작 1회당 약 150MB 전송 → 무료 전송량(월 5GB)으로 약 33회. 실사용량 측정 필요 |

## 1. 결정 기록

| 날짜 | 결정 | 근거 | 결정 |
| --- | --- | --- | --- |
| 10-14 | 앱 데이터(배치 산출물 13개 표)를 서비스 기준으로 적재한다. 김세은 DB는 분석용으로 둔다 | 같은 표를 옮겨야 "이전 후에도 숫자가 같다"를 행 단위로 증명할 수 있다. 김세은 DB는 음식 3종·다른 정의라 도구를 다시 짜야 한다(부록 A) | 염동권 |
| 10-15 | 1차로 8개 업종을 더해 15업종으로 확장한다 | 4차 회의. 대구 상가 대응 42.3% → 47.3% | 팀 회의 |
| 10-15 | 염동권 소유의 새 Supabase 프로젝트(무료)에 적재한다 | 김세은 프로젝트는 390MB를 써서 공간이 부족하다 | 염동권 |
| 10-16 | DB에는 한 버전만 유지한다 | 무료 500MB에서 교체 중 두 버전이 겹치면 한도에 닿는다. 되돌리기는 저장소 parquet로 재적재 | 염동권 |
| 10-16 | 확장 이전 7업종 데이터를 스냅샷으로 보존한다 | 김세은 D-01·D-02 검증의 기대 해시를 바꾸지 않고 재현성을 유지하기 위해 | 염동권 |
| 10-16 | 공개 앱이 DB를 읽도록 전환한다. 접속은 읽기 전용 계정으로 한다 | 전송량 위험은 parquet 자동 대체로 서비스 중단을 막는 전제로 감수. 최소 권한 원칙([구현 설계](../IMPLEMENTATION_DESIGN.md)) | 염동권 |

## 2. 현재 구성

### 2-1. 데이터

- **업종 15개** (`service/config.py`의 `SERVICES`, 파일 기준 16개 이름): 일반음식점, 휴게음식점, 제과점영업, 미용업, 세탁업, 노래연습장업, 담배소매업 + 의원·병원, 약국, 체력단련장업, 인터넷컴퓨터게임시설제공업, 당구장업, 체육도장업, 골프연습장업, 축산판매업
- **원본**: 행정안전부 인허가 대구광역시 압축 파일(195개 업종, 2026-10-13까지) 중 16개 CSV. `service/data/raw`(Git 제외)에 둔다. 배치는 파일 이름 `분류_업종명[_지역].csv`의 두 번째 칸이 `SERVICES`와 **정확히 같을 때만** 읽는다(부분 일치로 찾으면 "병원"이 "동물병원"에도 걸린다).
- **산출물**: `service/data/processed`의 parquet 13개 + `meta.json`. 인허가 225,858건(폐업 154,315 · 영업 중 71,543), 자리 86,386곳.
- **보조 데이터 6개 표**(poi·area_context·legal_admin_map·station_traffic·parking·market)는 이번 확장에서 다시 만들지 않았다. 기준 시점은 상가정보 2026-06, 인구 2026-08-31, 지하철 1~7월 평균으로 인허가와 다르다.
- **스냅샷**: 확장 이전(2026-09-23, 7업종) 14개 파일을 `service/data/snapshots/20260923_7services/`에 바이트 그대로 보존. 김세은 D-01·D-02 스크립트 10개와 `tests/test_snapshot_hashes.py`는 이 폴더를 읽는다.

### 2-2. Supabase 프로젝트 구조

```
Supabase 프로젝트 (염동권 소유, Free, 서울) — DB 240MB
├─ app 스키마 (229MB, 표 15개)
│   ├─ dataset_versions   버전 목록: 상태, 기준일, 업종, meta.json 원문, 자료형, 표별 행 수
│   ├─ current_version    앱이 읽을 버전 한 줄 → 3
│   └─ 데이터 표 13개     parquet 와 같은 이름·컬럼 + version_id, _row(원래 행 순서)
├─ public 스키마 (비어 있음 — Supabase 자동 REST API 는 public 만 공개)
└─ auth·storage·realtime·vault 등 Supabase 기본 구성 (약 1.5MB)
```

| 표 | 행 (v3) | 데이터 + 인덱스 | 기본 키 |
| --- | ---: | ---: | --- |
| stores | 225,858 | 95MB + 41MB | version_id, org_code, service, mgmt_no |
| units | 86,386 | 46MB + 10MB | version_id, uid |
| poi | 118,357 | 24MB + 4MB | — |
| transitions | 22,990 | 6MB + 2MB | — |
| area_year · survival · area_cycle · vacancy_area | 6,847 · 685 · 352 · 326 | 약 2MB | — |
| parking · area_context · market · legal_admin_map · station_traffic | 1,086 · 150 · 106 · 212 · 94 | 약 0.5MB | — |

- 모든 데이터 표는 `version_id`로 `dataset_versions`를 참조한다(버전 삭제 시 함께 삭제).
- 인덱스: 모든 표 (version_id, _row), `stores`·`units`의 (version_id, gu, dong), `stores`·`transitions`의 (version_id, uid).
- 버전 상태: `loading` → `validated` / `failed` → `current` → `retired`. 앱은 `current_version`이 가리키는 버전만 읽으므로 적재 도중 실패해도 서비스 데이터가 섞이지 않는다(E-01 R1·R2 대응).
- 지금 남아 있는 버전은 **3번 하나**(상태 `current`, 기준일 2026-10-13, "15업종 정식 배치").

### 2-3. 권한

| 계정 | 쓰는 곳 | 권한 |
| --- | --- | --- |
| `postgres` (관리자) | 염동권 PC의 적재 스크립트. 접속 정보는 로컬 `.env`의 `APP_DATABASE_URL` | 전체 |
| `app_reader` (앱 전용) | 공개 앱. 접속 정보는 Streamlit Secrets의 `APP_DATABASE_URL`(로컬 사본은 `.env`의 `APP_READER_DATABASE_URL`) | `app` 스키마 15개 표 **읽기만** |
| `anon`, `authenticated` (공개 키) | 브라우저용 Supabase 기본 계정 | `app` 스키마 접근 불가 |

- 모든 `app` 표에 RLS가 켜져 있고, 읽기 정책은 `app_reader`용 15개뿐이다.
- 적재 스크립트가 표를 새로 만들 때마다 `app_reader` 권한·정책을 다시 적용한다.
- 비밀번호는 `.env`와 Streamlit Secrets에만 있다. 문서·로그·커밋에 남기지 않는다.

### 2-4. 앱이 데이터를 읽는 방식

`service/core/datasource.py`가 출처를 고르고, `DataStore`(`service/core/tools.py`)는 받은 표를 그대로 쓴다. 도구 11개는 바뀌지 않았다.

| 환경변수 (배포에서는 같은 이름의 Secrets) | 뜻 |
| --- | --- |
| `APP_DATABASE_URL` | DB 접속 문자열(Session pooler). 없으면 parquet |
| `APP_DATA_SOURCE` | `auto`(기본: DB, 실패 시 parquet) · `db`(DB만, 실패 시 오류 — 검증용) · `parquet` |
| `APP_DATA_VERSION` | 읽을 버전 번호. 없으면 `current_version` |

- 앱은 시작할 때 13개 표를 한 번에 읽어 메모리에 올린다(프로세스당 1회). 원래 행 순서(`_row`)·`meta.json` 원문·pandas 자료형을 복원해 parquet와 똑같은 표를 만든다.
- 사이드바 기준일 옆에 출처를 표시한다(`데이터 db v3` 또는 `데이터 parquet`).
- 배포 의존성: `service/requirements.txt`에 `psycopg[binary]==3.3.6`.

## 3. 운영 방법

### 3-1. 데이터 갱신 (염동권, 로컬)

`service/` 폴더, Python 3.12 가상환경 기준.

```powershell
python -m pipeline.build                                   # data/raw → data/processed
python -m unittest tests.test_core_units; python -m tests.smoke_test
# 테스트 통과 후 main 에 올린다 (/commit-push)
python -m pipeline.load_supabase --processed data/processed --env-file ../.env --fresh --start-version <다음 번호> --activate
```

- `--fresh`: 적재 전에 `app` 스키마를 비운다(한 버전 유지). 행만 지우면 디스크가 줄지 않아 스키마째 다시 만든다.
- `--activate`: 표별 행 수 검증을 통과하면 `current_version`을 새 버전으로 바꾼다. 빼면 `validated`로만 남는다.
- `--max-db-mb`(기본 450): 표를 넣을 때마다 DB 크기를 확인해 넘으면 중단한다.
- `--activate-version N`: 적재 없이 이미 검증된 버전을 현재 버전으로 지정한다.
- 갱신 뒤 공개 앱을 Reboot하고 사이드바의 "데이터 db v<번호>"·기준일을 확인한다. 코드 변경이 함께 있으면 [작업 흐름](../TEAM_WORKFLOW.md)의 배포 순서(`main` → `deploy` → Reboot)를 따른다.

### 3-2. 되돌리기

- DB를 이전 데이터로: 저장소의 이전 커밋 parquet로 `--fresh --activate` 재적재.
- DB를 쓰지 않게: Streamlit Secrets의 `APP_DATA_SOURCE`를 `"parquet"`로 바꾸고 Reboot.

### 3-3. 주의

- `scripts/profile_data.py --demo service`는 D-01 manifest를 `service/data/processed` 기준으로 새로 쓰는 생성기다. 실행하면 9/23 해시가 15업종 해시로 바뀌므로 D-01을 다시 만들 때가 아니면 실행하지 않는다.
- 관리자 접속 정보(`.env`의 `APP_DATABASE_URL`)는 Streamlit Secrets에 넣지 않는다.

## 4. 검증 결과

| 검증 | 결과 |
| --- | --- |
| 업종 판별 | 압축 파일 195개 중 정확히 16개 선택(동물병원·동물약국 제외), 기존 이름 형식도 인식 |
| 정식 배치 | 18초. 시험 배치 결과와 7개 산출 표 완전 일치 |
| 김세은 검증 보존 | D-01·D-02 오프라인 스크립트 8개를 스냅샷으로 재실행, 해시 검증 통과·분석 수치 동일 |
| 적재 | 13개 표 행 수 parquet와 일치(43초) |
| DB 경로 = parquet 경로 | 13개 표 값·자료형 오차 없이 일치, smoke test 도구 호출 20건 결과 20/20 일치 |
| 연결 실패 | `auto`는 parquet로 대체하고 사유 기록, `db`는 오류로 중단 |
| 읽기 전용 계정 | `app_reader`로 조회 가능, 삭제·표 생성·수정 모두 권한 없음 |
| 테스트 | `service/` 단위 14개·smoke·에이전트 루프 2개·MCP 점검 통과. 저장소 테스트 26개 중 24개 통과(실패 2개는 이전부터 있던 Windows 파일 권한 검사) |
| 공개 앱 (10-16 06:38 UTC Reboot) | 설치 로그에 `psycopg 3.3.6` 포함 61개 패키지, 오류 없음. 사이드바 "기준일 2026-10-13 · 데이터 db v3", 누적 225,858 · 폐업 154,315 · 영업 중 71,543, 대시보드 정상(새 업종 표시) |

## 5. 무료 플랜과 비용

무료 플랜 조건(2026-10-15 supabase.com/pricing 확인)과 지금 사용량:

| 항목 | Free | Pro ($25/월) | 지금 |
| --- | --- | --- | --- |
| DB 크기 | 500MB | 8GB | 240MB ✅ |
| 전송량(egress) | 월 5GB | 월 250GB | 앱 시작 1회 약 150MB ⚠️ |
| 비활성 | 1주 비활성 시 일시정지 | 없음 | 앱이 쓰이면 유지 |
| 백업 | 없음 | 매일(7일 보관) | parquet·원본으로 재생성 가능 |

측정(로컬 PC → Supabase 서울): 앱 시작 시 DB 읽기 8~20초(parquet 0.1초), 1회 약 150MB 수신.

- **용량**: 한 버전 유지 규칙이면 2차 업종·작은 보조 데이터까지 무료로 들어간다. 상가정보 과거 스냅샷처럼 큰 자료를 쌓으면 넘는다.
- **전송량**: 앱이 한 달에 약 33번 시작하면 무료 한도에 닿는다. 재시작은 방문이 없어 잠들었다 깰 때·배포·Reboot마다 생긴다(Streamlit Cloud의 재시작 빈도는 미확인). 넘더라도 `auto` 모드로 화면은 parquet로 유지된다(Supabase의 무료 한도 초과 시 제한 방식은 미확인).
- **판단 기준**: Supabase 대시보드 Usage → Egress에서 **하루 평균 170MB 이하**면 무료 유지.
- **넘을 때 선택지**: (a) Pro 전환 — 4차 회의대로 멘토 지원 요청, 실측값 첨부 / (b) 도구가 질문에 필요한 행만 SQL로 조회하도록 변경 — 비용 없이 해결되고 시작도 빨라지지만 도구 11개 재작성 / (c) 앱이 쓰지 않는 컬럼 제외 — 전송량 일부 감소.

## 6. 남은 일

- [ ] 1주일간 egress 사용량 확인 → 무료 유지 또는 Pro 전환 결정
- [ ] 공개 서버 메모리 확인(앱 반복 재시작 여부)
- [ ] 김세은: 15업종 데이터 품질 검증(D-04) — 새 업종의 폐업 기록 방식(PC방·게임업은 인허가취소일자 사용) 등
- [ ] 김세은 DB 관련 확인 질문(부록 A-4)
- [ ] (후속) 2차 업종·다른 출처 업종 검토, 필요한 행만 조회하는 구조(E-03·E-04와 연계)

## 부록 A. 1단계 조사 (2026-10-14)

### A-1. 앱이 실제로 쓰는 데이터 (코드 검색, 7업종 기준)

`DataStore`가 앱 시작 시 parquet 13개를 모두 메모리에 올리고 도구 11개가 pandas로 걸러 쓴다. "사용 컬럼"은 컬럼 이름이 코드에 문자열로 등장하는지 검색한 근사치다.

| 표 | 행 | 컬럼 | 사용 컬럼(근사) | 메모리 |
| --- | ---: | ---: | ---: | ---: |
| stores | 197,356 | 20 | 15 | 85.9MB |
| units | 76,363 | 34 | 28 | 41.8MB |
| poi | 118,357 | 12 | 11 | 25.5MB |
| transitions | 22,945 | 14 | 14 | 5.5MB |
| 나머지 9개 | 9,036 | — | — | 약 1MB |

설계에 반영한 관찰:

- `stores`의 `org_code`·`mgmt_no`는 앱 코드에서 쓰이지 않지만, D-02 [결합 계약](../d02/handoff.md)의 인허가 식별자라 DB 기본 키로 둔다.
- `get_survival_curve`는 `survival` 요약표가 아니라 `stores` 행으로 생존곡선을 그때그때 계산한다. 따라서 `stores` 원 행이 DB에 있어야 한다.
- 도구는 주소 부분 일치, 동 이름 앞부분 일치, 반경 계산(구면 거리), 업태별 집계를 pandas로 한다. SQL로 옮기려면 텍스트·좌표 인덱스가 필요해 첫 단계에서는 옮기지 않았다.
- 앱 화면은 `meta.json`(기준일·품질 수치)을 직접 읽으므로 DB에도 버전·기준일 표가 필요하다.

### A-2. 김세은 Supabase DB (프로젝트 `ecqrnkvehsbxinmeukqf`, 읽기 전용 조회)

DB 390MB(10-14, 10-16 동일). 음식 3종을 따로 정제한 분석 데이터와 보조 원본 자료다.

| 표 | 행 | 크기 | 내용 |
| --- | ---: | ---: | --- |
| aux_import_rows | 165,982 | 127MB | 보조 자료 적재 때 원본 줄을 통째로 보관한 스테이징. 아래 `aux_` 표와 내용이 겹친다 |
| food_clean | 132,183 | 118MB | 음식 3종 인허가, 원본 + 파생 44개 컬럼. 기본 키 `관리번호`. 분석 기준 2026-09-13 |
| aux_shops | 118,357 | 76MB | 상가정보 원본 42개 컬럼 |
| unit_summary | 76,840 | 25MB | `자리후보키` 단위 자리 요약 |
| food_transitions | 15,516 | 16MB | 업종 전이. `food_clean` 44개 컬럼 + 다음 가게 정보 |
| aux_subway_daily | 39,856 | 14MB | 지하철 일별 원본(`source_year` 미확인) |
| 나머지 6개 + 뷰 `food_high` | — | 약 2MB | 주차장·인구·시장·월별 승하차·변수 설명 |

- 크기가 큰 이유: 스테이징 중복(약 3분의 1), 원본 컬럼 전체 보관, 표끼리 컬럼 중복, 한글 텍스트.
- `unit_summary`가 `food_clean`보다 자리 12,350개 적은 이유: 빠진 자리는 모두 MULTI이고 그 행 39,827건이 전부 신뢰도 REVIEW다. 즉 요약표는 HIGH 자리만 담는다.
- 공개 키 접근: 읽기 정책은 있으나 GRANT가 없어 읽히지 않는다. `aux_` 표는 원본이라 열지 않는 편이 맞다.

### A-3. 앱 데이터와의 대응

| 앱 표 | 김세은 DB | 대응 |
| --- | --- | --- |
| stores (`uid` 연결) | food_clean | 부분. 업종 범위·기준일·정제 규칙이 다르다 |
| units (`uid` = 주소+층) | unit_summary (`자리후보키` = 건물주소·10m 좌표, HIGH만) | 정의가 달라 바꿔 쓸 수 없다 |
| transitions | food_transitions | 정의가 다르다 |
| survival · area_cycle · area_year · vacancy_area · meta.json | 없음 | 앱 전용 |
| poi · station_traffic · parking · market | aux_shops · aux_subway_* · aux_parking · aux_markets | 원본 대 가공본 |

검토한 선택지: A. 앱 데이터 기준 적재(채택) · B. 김세은 DB 기준으로 도구 재작성(7업종·생존/사이클 집계 소실, 정의 재검증 필요) · C. parquet 유지(Supabase 목표 지연).

### A-4. 김세은에게 확인할 것

1. 이 DB는 분석·실험용인가, 서비스에 쓸 생각인가?
2. `unit_summary`가 신뢰도 HIGH 자리만 담는 것은 의도한 설계인가?
3. `aux_import_rows`(127MB)를 지워도 되는가? (지우면 표 삭제로 공간이 확보된다)
4. `food_clean`의 정제 규칙·기준일 기록과 적재 스크립트를 저장소에 올릴 수 있는가?
5. 기본 키를 D-02 결합 계약(`org_code + service + mgmt_no`)에 맞출 계획이 있는가?

## 부록 B. 시험·전환 경위 (2026-10-16)

| 버전 | 내용 | 결과 | 현재 |
| --- | --- | --- | --- |
| v1 | 15업종 시험 데이터(임시 폴더 배치) 첫 적재 | 24초, 13개 표 행 수·주요 값 일치, `app` 214MB. 사전 추정 239MB | 삭제 |
| v2 | 원래 행 순서·`meta.json` 원문·자료형을 함께 저장하도록 보완해 재적재 | DB 경로 = parquet 경로 20/20. v1과 함께 있어 DB 457MB → `--fresh`로 v2만 남겨 240MB | 삭제 |
| v3 | 정식 배치(`service/data/processed`) 적재 | 43초, 20/20 일치, `current` 지정, 공개 앱에서 사용 중 | **사용 중** |

DB 경로와 parquet 경로의 결과가 처음에 다르게 나온 원인과 해결:

| 차이 | 원인 | 해결 |
| --- | --- | --- |
| 업종 목록 문구 순서 | `jsonb`가 키 순서를 바꿈 | `meta.json` 원문을 `meta_text`로 따로 저장 |
| 좌표 마지막 자리 | 서버의 실수 출력 자릿수, pandas CSV 파싱 정밀도 | 읽을 때 `extra_float_digits = 3`, `float_precision="round_trip"` |
| `transitions.to_closed` 자료형 | 결측 허용 불리언이 일반 불리언으로 읽힘 | 적재 때 pandas 자료형을 `dtypes`로 저장해 복원 |
| 동률 정렬 결과(예방) | DB는 행 순서를 보장하지 않음 | 원래 행 순서 `_row` 저장, 그 순서로 읽기 |

## 부록 C. 재현·관련 파일

- 배치: `service/pipeline/build.py`, `service/config.py`
- 적재: `service/pipeline/load_supabase.py` (`--dry-run`으로 생성할 표 정의만 확인 가능)
- 앱 읽기: `service/core/datasource.py`, `service/core/tools.py`(`DataStore`), `service/app.py`(Secrets → 환경변수)
- 실행 설정 예시: `service/.streamlit/secrets.toml.example`, `service/README.md`의 "Supabase DB" 절
- DB 상태 조회: 관리자 접속 정보로 `app.dataset_versions`, `app.current_version`, `pg_total_relation_size` 등 읽기 전용 SQL
- 김세은 DB 조회: Supabase MCP(읽기 전용, 해당 프로젝트 한정)
