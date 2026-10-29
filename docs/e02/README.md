# E-02 데이터 계약·Supabase 이행

담당: 염동권 · 기간: 2026-10-14 ~ · 상태: **진행** — Bigdata_platform DB로 앱 연결 전환 완료(2026-10-17), 운영 확인 중

이 문서는 앱 데이터를 Supabase(PostgreSQL)로 옮긴 과정과 지금 구성을 정리한다. 앞부분(1~7절)은 **현재 상태와 운영 방법**, 뒷부분(부록)은 **조사·시험 기록**이다. 수치는 코드 실행·DB 조회로 확인한 값이며, 확인하지 못한 것은 "미확인"으로 표시한다.

## 한눈에 보기

| 항목 | 현재 |
| --- | --- |
| 공개 앱 | [pubdai.streamlit.app](https://pubdai.streamlit.app) (`deploy` d16af85) — 사이드바 "데이터 db v3" |
| 데이터 출처 | Bigdata_platform 조직의 기존 Supabase 프로젝트(Pro, 시드니)의 `app` 스키마. DB 실패 시 저장소 parquet로 자동 대체 |
| 데이터 | 15업종 인허가 225,858건 · 자리 86,386곳 · 기준일 2026-10-13 (DB version 3) |
| DB 크기 | 232MB (2026-10-29 대상 DB 측정). 한 버전만 유지(7절) |
| 앱 접속 계정 | `app_reader` — `app` 스키마 읽기 전용 |
| 검증 | DB 경로와 parquet 경로의 13개 표·도구 결과 20건 완전 일치 |
| 남은 위험 | 앱 시작 1회당 약 150MB 전송. 대상 Pro 조직의 전체 사용량과 실제 지연 측정 필요(이전 무료 한도 분석은 5절) |

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
Supabase 프로젝트 (Bigdata_platform, 기존 Pro, 시드니) — 원본 DB 크기 측정 240MB
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
- 세 학생의 새 작업 대상은 모두 프로젝트 `uoiamnbkzlvlskngataq`다. 각 PC의 접속 설정·역할·분석 결과 저장·운영 반영 경계는 [공유 DB 작업 기준](../TEAM_WORKFLOW.md#공유-db-작업-기준-2026-10-17)을 따른다. `.env.example`은 빈 항목만 제공하므로 관리자에게 받은 접속 정보를 각자 로컬에 설정해야 한다. 과거 다른 프로젝트의 연결을 재사용하지 않는다.

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
python -m pipeline.load_supabase --processed data/processed --env-file ../.env --activate
```

- 실행 전에 새 프로젝트·쓰기 권한·현재 버전·백업·용량을 확인한다. 기본 용량 상한은 450MB이며, 기존 버전과 새 적재분의 합계가 넘으면 보존·교체 방식을 먼저 정한다. 이전 무료 한도 때문에 전체 교체를 자동 선택하지 않는다.
- `--fresh --start-version <다음 번호>`: 운영 데이터 전체 교체가 요청됐을 때만 추가한다. 적재 전에 `app` 스키마를 비우므로 실패 시 이전 정상 데이터가 사라질 수 있다. 백업과 되돌리기 경로를 먼저 확보한다. 이전 무료 플랜에서는 한 버전 유지에 사용했다.
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

## 5. 이전 무료 플랜의 비용 분석

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

- [x] Gemini 키 교체·답변 확인 (2026-10-29, 7-3절)
- [x] 염동권 로컬을 대상 DB로 전환·접속 확인 (2026-10-29, 7-3절)
- [x] 원본(서울) 프로젝트 `app_reader` 로그인 차단 (2026-10-29, 7-3절)
- [ ] 원본 프로젝트 보존 기한과 삭제 시점 결정
- [ ] 대상 Pro 조직의 egress 사용량·앱 접속 지연 관찰(기존 Pro 요금 유지, 새 프로젝트 추가 없음)
- [ ] 공개 서버 메모리 확인(앱 반복 재시작 여부)
- [ ] 김세은: 15업종 데이터 품질 검증(D-04) — 새 업종의 폐업 기록 방식(PC방·게임업은 인허가취소일자 사용) 등
- [ ] 김세은 DB 관련 확인 질문(부록 A-4)
- [ ] (후속) 2차 업종·다른 출처 업종 검토, 필요한 행만 조회하는 구조(E-03·E-04와 연계)

## 7. Bigdata_platform 기존 프로젝트로 DB 복사 (2026-10-17)

사용자 요청은 `pubdai`의 데이터를 `Bigdata_platform`으로 옮기는 것이다. 조직 간 프로젝트 이전 화면은 기존 Pro 조직에 프로젝트를 추가하면 **월 $10 증가**한다고 안내했다. 사용자가 추가 비용을 원하지 않아, 새 프로젝트를 만들지 않고 기존 대상 프로젝트에 논리 백업을 복원했다. 조직·구독·과금 설정은 변경하지 않았고, 기존 Pro 요금과 사용량 요금은 별개다.

- 원본: `pubdai` 조직 / `pubdai` 프로젝트 (`ihaypnmvrnvbjdbtgiaq`, 서울).
- 대상: `Bigdata_platform` 조직 / `JunseokNoh's Project` (`uoiamnbkzlvlskngataq`, 시드니).
- 사전 확인: 대상에는 애플리케이션 테이블·Auth 사용자·Storage 버킷/파일이 없었다. 원본에는 `app` 표 15개만 있었고, 사용자 정의 함수·Realtime publication·Auth 사용자·Storage 버킷/파일·배포된 Edge Function은 없었다. `public`은 비어 있었고 설치된 확장은 양쪽이 같았다.
- 방법: PostgreSQL 17.11 원본을 `pg_dump` 18.6으로 `--schema=app --no-owner` 백업하고, 대상에서 `psql --single-transaction -v ON_ERROR_STOP=1`로 복원했다. 원본의 데이터와 설정은 변경하지 않았다.
- 검증: 메타데이터 표 2개를 포함한 **15개 표, 합계 463,451행**의 행 수와 전체 행 지문이 일치했다. 각 행의 `md5(row_to_json(t)::text)`를 정렬·연결한 뒤 다시 MD5로 비교했다(중복 행도 포함). `pg_dump --schema-only --schema=app --no-owner`에서 주석과 매 실행마다 바뀌는 restrict 토큰만 제외한 구조도 일치했다. 테이블·인덱스·제약조건·시퀀스·RLS·정책·GRANT를 포함한다. 서비스 버전은 `3` 그대로다.
- 권한: 15개 표 모두 RLS 활성, `app_reader` SELECT 허용 및 INSERT/UPDATE/DELETE 불허, `anon`·`authenticated`의 `app` USAGE 불허를 카탈로그로 확인했다. 역할 소속도 원본과 동일했다. `postgres`의 SET ROLE 권한이 양쪽 모두 없어 역할 전환 조회는 검증하지 않았다.
- 인증 제한: 자동 승인 검토가 기존 `app_reader` 인증 검증값 추출을 거부해 비밀번호는 복사하지 않았다. 대상 역할은 **NOLOGIN**으로 만들었으며 읽기 권한·정책만 복원했다. 복원 직후에는 로그인과 앱 연결이 미완료였고, 이후 7-1·7-2절에서 완료했다.
- **복원 직후 운영 상태**: 이 단계에서는 공개 앱의 Streamlit Secrets·`deploy`를 변경하지 않아 원본 서울 DB를 계속 사용했다. 이후 7-2절에서 앱 연결을 전환했다. 원본은 삭제하지 않았다.
- 백업: 로컬 Git 제외 `.mentee/db-migration-20261017/`에 원본 SQL(161,321,948바이트), 대상 이전 public 백업, 양쪽 지문·구조 비교·검증 요약·결과 화면을 보관했다. 원본 SQL의 바이트 SHA-256은 `78f142d8711db5329bc8ab90f878bebe2e938bafa6f37659b4b805e944645d10`이다. 비밀번호는 로컬 `.env`에서만 읽었고 출력·문서·Git에 넣지 않았다.

| 표 | 행 수 | 원본 ↔ 대상 전체 데이터 |
| --- | ---: | --- |
| `area_context` | 150 | 일치 |
| `area_cycle` | 352 | 일치 |
| `area_year` | 6,847 | 일치 |
| `current_version` | 1 | 일치 |
| `dataset_versions` | 1 | 일치 |
| `legal_admin_map` | 212 | 일치 |
| `market` | 106 | 일치 |
| `parking` | 1,086 | 일치 |
| `poi` | 118,357 | 일치 |
| `station_traffic` | 94 | 일치 |
| `stores` | 225,858 | 일치 |
| `survival` | 685 | 일치 |
| `transitions` | 22,990 | 일치 |
| `units` | 86,386 | 일치 |
| `vacancy_area` | 326 | 일치 |

### 7-1. 앱 연결 전환 준비 (2026-10-17, 사용자 추가 요청)

- 사용자가 앱 연결 전환까지 요청해 대상의 기존 `app_reader`에 새 비밀번호를 설정하고 LOGIN을 활성화했다. 원본의 비밀번호나 인증 검증값은 읽거나 재사용하지 않았다. 대상 URL은 로컬 `.env`의 `TARGET_APP_READER_DATABASE_URL`에만 저장했으며, 운영 앱에는 이 읽기 전용 URL만 넣어야 한다.
- 실제 `app_reader` 로그인으로 15개 표의 행 수를 확인해 원본과 일치했다(총 463,451행). `current_version=3`, `stores=225858`이며, `UPDATE ... WHERE false`가 권한 오류로 차단됨을 확인했다. 증거는 로컬 `.mentee/db-migration-20261017/app-login-validation.json`에 보관한다.
- **아직 미전환**: Streamlit Cloud 관리 화면이 로그아웃 상태여서 Secrets에 접근할 수 없었다. 사용자에게 pubdai 관리 권한이 있는 계정 로그인을 요청했다. 공개 앱을 깨워 기준일 2026-10-13·데이터 db v3·누적 225,858·폐업 154,315·영업 중 71,543을 확인했지만, 이는 여전히 원본 DB 연결이다.
- 다음 행동: 관리 로그인 후 기존 `APP_DATABASE_URL`만 대상의 읽기 전용 URL로 교체 → 앱 재시작 → 대상 DB의 앱 접속 확인과 화면·도구 응답 검증. 기존 원본은 검증과 되돌리기를 위해 유지한다.

### 7-2. 앱 연결 전환 완료 (2026-10-17)

- 사용자 계정에서 `donggwony` 워크스페이스와 `pubdai`의 Settings·Reboot 접근을 확인했다. Secrets의 `APP_DATABASE_URL`만 대상 읽기 전용 `app_reader` URL로 바꾸고 저장했다. 저장된 전체 설정이 의도한 내용과 같은지 비밀값을 출력하지 않고 재확인했다. Gemini 설정과 `APP_DATA_SOURCE=auto`는 유지했다.
- Streamlit Cloud에서 Reboot 후 앱에 새로 연결했다. 화면은 **기준일 2026-10-13 · 데이터 db v3 · 누적 225,858 · 폐업 154,315 · 영업 중 71,543**으로 정상 표시됐고, 대시보드의 생존·공실 후보·차트가 오류 없이 표시됐다. LLM 상담 호출은 수행하지 않았다.
- 대상 DB의 `pg_stat_statements`에서 `app_reader`가 앱의 13개 CSV COPY 조회를 각각 1회 실행한 것을 확인했다. 행 수는 각각 22,990·326·352·685·94·225,858·106·150·118,357·1,086·212·6,847·86,386이다. 로컬 검증은 COPY가 아닌 SELECT로 수행했으므로 앱이 대상 DB에서 로드했다는 증거다.
- **완료 범위**: 15개 표 데이터·구조·권한 복사, 대상 읽기 전용 로그인, 앱 Secrets 전환, 재시작, 대상 DB 실제 조회와 화면·대시보드 확인. 원본 DB와 로컬 백업은 보존했고, 새 프로젝트·구독·코드·배포 브랜치 변경은 없었다. 기존 Pro 조직 요금·사용량 과금은 그대로이며 월 $10 프로젝트 추가는 하지 않았다.
- 로컬 증거: `.mentee/db-migration-20261017/app-cutover-validation.json`, `app-cutover.jpg`(Git 제외). 검증 증거에는 비밀번호를 기록하지 않았다.
- 보안 기록: Secrets 확인 과정에서 기존 Gemini 키와 원본 DB 연결 비밀값이 도구 출력에 포함되는 실수가 있었다. 이후 비밀값 출력은 차단했다. 대상의 새 DB 비밀번호는 해당 출력에 포함되지 않았다. 기존 Gemini 키·원본 DB 읽기 계정 비밀번호의 교체는 별도 후속 조치다.
- 다음 행동: 대상 조직 Usage와 시드니 DB 접속 지연 관찰. 원본 삭제와 인증값 교체는 아직 수행하지 않았다.

### 7-3. 후속 조치 (2026-10-29, 염동권)

- **Gemini 키 교체**: 염동권이 새 키를 발급해 Streamlit Secrets의 `GEMINI_API_KEY`를 바꾸고 Reboot했다. 공개 앱 AI 상담에 질문을 보내 답변이 오는 것을 확인했다(염동권 확인). 노출됐던 이전 키는 AI Studio에서 삭제했다(염동권 확인). Gemini 한도는 Google Cloud 프로젝트 단위라 같은 프로젝트의 키는 한도를 공유한다.
- **로컬 연결 전환**: 염동권 PC의 `.env`에서 `APP_DATABASE_URL`(관리자)·`APP_READER_DATABASE_URL`(읽기 전용)을 대상 프로젝트로 바꿨다. 비밀값을 출력하지 않고 확인: 두 계정 모두 시드니 pooler 접속, `app.current_version`=3, `stores` 225,858행. `postgres`는 쓰기 가능, `app_reader`는 쓰기 권한 없음·UPDATE 시도 권한 오류로 차단. Windows 사용자·시스템 환경변수에 같은 키가 없어 적재 스크립트는 이 `.env`를 읽는다.
- 주의: 비밀번호에 `@` 같은 URL 예약 문자가 있으면 `%40`처럼 인코딩해야 한다. Streamlit Secrets에서 복사할 때 따옴표가 따라오면 `sslmode` 값이 깨진다.
- **원본 읽기 계정 차단**: 염동권이 원본(서울) 프로젝트 SQL Editor에서 `alter role app_reader nologin;`을 실행했다(결과 "Success. No rows returned", 염동권 확인). 데이터·권한은 그대로 두고 로그인만 막았다. 원본 쪽 `rolcanlogin`은 에이전트가 재조회하지 못했다. 같은 날 대상 DB의 `app_reader`는 로그인 가능(`rolcanlogin`=true)·v3 조회를 확인해 공개 앱 연결에는 영향이 없다.
- 남은 일: 원본 프로젝트 보존 기한 결정.

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
