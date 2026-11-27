# E-04 자동 검사·배포 점검

담당 염동권 · 시작 2026-11-20 · [작업판](../WORKBOARD.md) E-04

질문: "배포하거나 DB 버전을 바꿀 때, 표가 비거나 키가 겹치거나 앱과 DB가 다른 데이터를 보는 일을 사람이 눈으로 찾지 않고 알아챌 수 있나?"

## 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | [데이터 계약](../e02/data_contract.md) 5절의 수동 검사를 읽기 전용 점검 스크립트로 만들고, 현재 parquet·공유 DB v10에 실행 | 완료 2026-11-20 |
| 2 | 적재 스크립트(`load_supabase`)가 적재 전에 같은 점검을 돌려 FAIL이면 적재하지 않기. 2026-11-13 보류 안건(전환 시 권한 재생성 제거·잠금 대기 제한·용량 상한 기본값·retired 버전 삭제) 반영 | 완료 2026-11-20 (DB 실행 없음, 옛 버전은 보존) |
| 3 | 배포 확인 자동화: `deploy` 올리기 전후 점검·공개 앱 응답·화면 버전 확인 | 완료 2026-11-20 (실패 알림·CI는 후속 후보) |
| 4 | 인허가 원본을 파일 사이트 직접 다운로드 대신 공공데이터포털 API로 받기, 주간(바뀐 행)·월간(전체 대조·교체) 갱신 | 완료 2026-11-24 |
| 5 | 새 원본(기준일 2026-11-22) 운영 반영: 배치·모델 표 3종 재계산·DB 적재·배포 | 완료 2026-11-24 (DB v16, deploy 23f5fe9) |

## 1단계: 데이터 점검 스크립트

**실행** (`service/` 안, 서비스 가상환경)

```powershell
python -m pipeline.check_data                    # 저장소 parquet 만
python -m pipeline.check_data --db               # + 공유 DB 현재 버전, parquet 와 대조
python -m pipeline.check_data --pubdai           # + 공개 앱 운영 DB(pubdai, 파일 방식) 현재 버전·파일 해시 (2026-11-27)
```

- 읽기만 한다. DB는 읽기 전용 `APP_READER_DATABASE_URL`을 먼저 쓰고, 없으면 `APP_DATABASE_URL`을 쓴다. 환경변수가 `.env`보다 우선하고, 접속 문자열은 출력하지 않는다.
- 접속 대상이 공유 DB(`uoiamnbkzlvlskngataq`)가 아니면 멈춘다.
- 항목마다 OK / WARN / FAIL을 낸다. FAIL이 있으면 종료 코드 1이다.
- 코드: [`service/pipeline/check_data.py`](../../service/pipeline/check_data.py), 테스트: [`service/tests/test_check_data.py`](../../service/tests/test_check_data.py) (6개).

**검사 항목**

| 검사 | 기준 | 계약 5절에서 |
| --- | --- | --- |
| 18개 표 존재·0행 아님 | 필수 7개 없으면 FAIL, 선택 표 없으면 WARN | 새로 추가 |
| 키 유일성·결측 (14개 표) | 중복 있으면 FAIL. 미확정 키 표(transitions·poi·parking·market)는 제외 | 수동 → 자동 |
| `stores`·`transitions`·`vacancy_scores`·`next_tenant_scores` → `units` (uid) | 연결 실패 있으면 FAIL | 수동 → 자동(결과 표 2개 추가) |
| 행정동 미연결 비율 | 2.5% 넘으면 WARN (E-12 수정 뒤 1.50% 기준, 처음엔 6.1%) | 수동 → 자동 |
| 자리 키에 `*`(가려진 번지) | 있으면 FAIL ([E-12](../e12/README.md)) | 새로 추가 |
| 확률 열 0~1, 업종 확률 합 = 1 | 범위 밖·결측·합 오차 0.001 초과면 FAIL | 새로 추가 |
| 결과 표 기준일 = 인허가 기준일 | 다르면 WARN | 새로 추가 |
| `current_version` = 유일한 `current` 상태 | 아니면 FAIL | 새로 추가 |
| 기준일이 이전 버전보다 앞섬 | 뒤로 가면 FAIL | 수동 → 자동 |
| 전환 안 된 새 버전 | 있으면 WARN | 새로 추가 |
| DB 크기 | 2,500MB 넘으면 WARN, retired 버전 목록 표시 | 새로 추가 |
| parquet ↔ DB 현재 버전 기준일·표별 행 수 | 다르면 WARN, 5% 넘게 줄었으면 FAIL | 새로 추가(앱의 대체 출처가 DB와 같은 배치인지) |

계약 5절의 "앱 화면·도구 결과"는 아직 사람이 확인한다(3단계).

**첫 실행 결과 (2026-11-20, `main` 46b51bc 데이터, DB v10)**

- OK 72 · WARN 0 · FAIL 0 (읽기 전용 계정으로 접속). 결과: [results/check_20261120.json](results/check_20261120.json)
- 18개 표 모두 있고, 키 중복 0, uid 연결 실패 0, 확률 범위·합 통과.
- DB v10은 유일한 `current`이고 parquet와 기준일(2026-11-06)·18개 표 행 수가 모두 같다.
- DB 크기는 1,913MB다. retired 버전(v3·v5~v9)이 쌓인 결과다. 처음에는 적재 스크립트의 옛 기본 상한(450MB)으로 비교해 WARN이 났다. Pro 플랜 디스크 8GB를 기준으로 경고선을 2,500MB로 고쳤다. retired 버전 정리 방식은 2단계에서 정한다.

**새로 확인한 것: 행정동 미연결 비율 5.08%**

- 데이터 계약에는 15업종 v3 기준 1.33%로 기록돼 있었다. 42종 확장(v5) 뒤로는 다시 재지 않았다.
- 지금 14,569 / 286,896건(5.08%)이다. 그중 11,646건은 `stores.dong`이 비어 있는 행이고(주소에서 법정동을 못 읽음), 나머지 2,923건은 법정동→행정동 대표 매핑에 없는 동이다.
- 동 이름을 쓰는 동네 프로필·인구·비슷한 동네 카드는 이 행들에 대해 행정동 맥락을 붙이지 못한다. 원인 분류(어느 업종·주소 형식인지)는 이번 범위가 아니다. 데이터 품질 후속 후보로 남긴다.
- 경고 기준을 현재 수준 + 1%p(6.1%)로 잡아, 앞으로 갑자기 늘면 알 수 있게 했다.

## 2단계: 적재 스크립트 개선

코드: [`service/pipeline/load_supabase.py`](../../service/pipeline/load_supabase.py), 테스트: [`service/tests/test_load_supabase.py`](../../service/tests/test_load_supabase.py) (4개). DB에는 아무것도 쓰지 않았다(코드만 바꿈, 읽기 계정으로 확인만).

| 바꾼 것 | 이전 | 이후 | 이유 |
| --- | --- | --- | --- |
| 적재 전 점검 | 없음(행 수만 적재 후 비교) | parquet에 1단계 점검을 돌려 FAIL이면 DB에 접속하지 않음. `--dry-run`에서도 실행 | 키 중복·연결 실패가 DB까지 가지 않게 |
| 읽기 권한 정책 | 적재·전환 때마다 정책을 지우고 다시 만듦 | 적재 때 없을 때만 만듦. 전환 때는 만들지 않고 `app_reader`가 모든 표를 읽을 수 있는지 확인만, 안 되면 전환 거부 | v6 첫 전환 시간 초과 원인(앱 읽기 연결과 잠금 충돌). 전환은 버전 표 두 개의 행만 바꾸게 됨 |
| 잠금 대기 | 제한 없음 | 적재·전환·삭제 모두 `lock_timeout` 15초 | 잠금에 걸리면 오래 매달리지 않고 실패 |
| 용량 상한 기본값 | 450MB (매번 `--max-db-mb 1200~1800` 지정) | 3,000MB | Pro 플랜 디스크 8GB, 지금 1.9GB. 점검 경고선 2,500MB보다 위 |
| 옛 버전 삭제 | 없음(`--fresh`로 전체 삭제만) | `--drop-retired <버전…>` (`--dry-run`이면 확인만) | retired·failed 버전만. 현재 버전과 가장 최근 retired(되돌릴 대상)는 요청해도 지우지 않음 |
| 적재 뒤 안내 | — | 전환하지 않으면 `check_data --db --version <새 버전>` 명령 출력 | 전환 전 새 버전을 DB에서 그대로 점검 |

`check_data`에 `--version`을 추가했다. 현재 버전 대신 전환 전(`validated`) 버전을 읽어 같은 검사를 하고, 기준일이 현재 버전보다 뒤로 가지 않았는지 본다.

**확인 (읽기 전용, 2026-11-20)**
- `app_reader`가 18개 표와 버전 표 2개를 모두 읽을 수 있다(전환 전 확인에서 거부될 표 없음).
- 버전 상태: v3 retired(15업종, 463,449행)·v4 failed(0행)·v5~v9 retired·v10 current.
- 큰 표: `stores` 1,181MB, `units` 426MB, `poi` 191MB.
- 삭제 규칙을 적용하면 v3·v4·v5·v6·v7·v8을 지울 수 있고 v9(되돌릴 대상)·v10(현재)은 남는다. **결정(2026-11-20, 염동권): 옛 버전은 일단 지우지 않고 둔다.** 디스크 여유가 충분하고, v3는 E-02 15업종 기록용 버전이다. 용량 경고(2,500MB)가 나면 다시 정한다. 지워도 공간은 vacuum 뒤 재사용될 뿐 DB 크기 숫자가 바로 줄지는 않는다.

**새 순서(데이터 갱신)**: `pipeline.build` → `check_data` → 테스트 → `main` → `load_supabase`(사전 점검 포함, 전환 없이) → `check_data --db --version <새 버전>` → `load_supabase --activate-version <새 버전>` → `check_data --db` → (2026-11-27~) `load_parquet_files --version <새 버전>` → `load_parquet_files --activate-version <새 버전>` → `check_data --db --pubdai` → 공개 앱 Reboot·확인.

## 3단계: 배포 전후 점검

코드: [`scripts/deploy_check.py`](../../scripts/deploy_check.py). 저장소 루트에서 실행하고, 푸시는 하지 않는다.

```powershell
python3 scripts/deploy_check.py pre    # deploy 로 올리기 전
python3 scripts/deploy_check.py post   # deploy 푸시·Reboot 뒤
```

| 단계 | 검사 | FAIL 조건 |
| --- | --- | --- |
| pre | `main` 브랜치·작업 폴더 깨끗함·로컬 `main` = `origin/main` | 하나라도 아니면 |
| pre | `origin/deploy` → `origin/main` fast-forward 가능 | `deploy`에 `main`에 없는 커밋(Codespaces 커밋 등) |
| pre | 바뀌는 파일 수, `service/` 변경 여부, 배포 환경 파일(`requirements.txt` 등)·가공 데이터 변경 | WARN만(배포 로그·데이터 점검 확인 안내) |
| pre | service 테스트 전체·smoke 테스트(서비스 가상환경, parquet) | 실패하면 |
| pre·post | `check_data --db --pubdai`(2026-11-27, pubdai 추가) | FAIL이 있으면 |
| post | `origin/deploy` = `origin/main` | 다르면 |
| post | 공개 앱 응답 `/~/+/_stcore/health` = ok (20초 간격 최대 6회) | 끝까지 응답 없으면 |

**첫 실행 (2026-11-20, 배포하지 않은 상태)**
- pre: Git 상태 외 모두 통과. deploy 014fd63 → main 6f79bf9 fast-forward 가능(10개 커밋, service/ 5개 파일), 테스트·smoke 통과, 데이터 점검 OK 72. 작업 폴더 FAIL은 이 스크립트 자체가 커밋 전이었기 때문이다.
- post: 공개 앱 응답 ok, 데이터 점검 통과. `deploy` ≠ `main` FAIL은 아직 배포하지 않았으니 맞는 결과다.
- 처음에는 공개 앱 응답이 인증서 오류(`CERTIFICATE_VERIFY_FAILED`)로 실패했다. 저장소 스크립트를 돌리는 MSYS Python이 Windows 인증서 저장소를 읽지 못해서다. curl이 있으면 curl로 확인하도록 고쳤다.

**화면 확인은 브라우저로 한다**
- 응답 확인(health)은 서버가 떠 있는지만 본다. 앱 코드가 오류를 내거나 이전 데이터 버전을 보여 주는지는 화면을 봐야 안다.
- 에이전트 브라우저로 확인할 수 있다. Streamlit Cloud 바깥 틀을 피해 `https://pubdai.streamlit.app/~/+/`를 열고, 사이드바 "수록 데이터 자세히"를 펼쳐 "데이터 db v<번호>"를 읽는다.
- 2026-11-20 확인: 기준일 2026년 11월 6일, 현재 영업 중 84,444건, "배치 2026-11-09 22:50:11 · 데이터 db v10". 데이터 점검의 현재 버전(v10)과 같다.
- 브라우저 없이 스크립트로 화면을 읽으려면 헤드리스 브라우저 설치가 필요해 이번 범위에서 뺐다.

**이번 범위에서 뺀 것(후속 후보)**
- 실패 알림: 지금은 정기 배치가 없어 사람이 실행할 때만 점검이 돈다. 정기 실행이 생기면 그때 알림을 붙인다.
- GitHub Actions로 `main` 푸시마다 테스트 자동 실행: 팀 전체 푸시에 영향을 주고 토큰 권한(`workflow`)이 필요해 팀과 정한 뒤 진행한다.
- 의존성 고정(전이 의존성 포함), 원본 갱신 API(D-01 실험) 연결.

## 4단계: 인허가 원본 API 갱신

2026-11-23~24 · 질문: "주간 갱신 때 인허가 원본을 사람이 사이트에서 내려받지 않고 API로 받을 수 있나? 받은 자료가 지금 파일과 같은가?"

**준비**: 42개 업종 API 활용신청·승인([license_api_apply.md](license_api_apply.md), [license_apis.json](license_apis.json)). 개발계정 한도 API마다 하루 10,000회·한 페이지 100행.

**스크립트** (`service/` 안에서 실행, 받은 파일은 `data/raw_api/`, Git 제외)

| 스크립트 | 하는 일 |
| --- | --- |
| `pipeline/fetch_license.py` | 대구 9개 자치단체 코드로 업종별 API를 받아 배치가 읽는 한글 열 이름의 UTF-8 CSV로 쓴다. `--full` 전체, `--since` 데이터갱신시점 이후만. 시간 초과·5xx 최대 10회 재시도, 페이지마다 `.parts/`에 중간 저장해 끊겨도 이어 받기, `--page-workers`로 한 자치단체 안의 페이지 동시 받기. `manifest.json`에 자치단체별 totalCount와 받은 행 수를 남기고 다르면 실패 |
| `pipeline/compare_license.py` | 지금 원본(`data/raw` 전체, 배치와 같은 규칙으로 합침)과 API 전체본을 키(자치단체코드+관리번호)로 대조. 값이 다른 행은 '파일 이후 바뀐 것'(최종수정·데이터갱신시점이 더 늦음)과 '설명 안 되는 차이'로 나눈다 |
| `pipeline/refresh_license.py` | `weekly`: 원본의 가장 늦은 데이터갱신시점 − 1일 이후 바뀐 행만 받아 `data/raw`에 `<분류>_<업종>_api_delta<날짜>.csv`로 얹기. `monthly`: 전체를 받아 대조하고 설명 안 되는 차이·빠진 업종이 없을 때만 원본을 `…_api_full<날짜>.csv`로 교체, 이전 원본은 `data/raw_archive/<날짜>/`로 이동(삭제 안 함). `--dry-run`, `--from-dir` |
| `pipeline/build.py` | 이름에 `_api`가 있는 원본은 UTF-8로 읽도록 한 줄 변경(기존 파일은 cp949 그대로) |

**왜 주간은 바뀐 행만, 월 1회는 전체인가**: API의 데이터갱신구분은 I(신규)·U(변경)뿐이고 삭제 표시가 없다. 원천에서 행이 지워지면(이번 대조에서 미용업 4건, 오등록 정정으로 보임) 바뀐 행만 받아서는 알 수 없다. 배치는 같은 가게의 최신 행만 남기므로 주간 갱신분은 얹기만 하면 되고, 지워진 행은 월간 교체 때 빠진다.

**첫 전체 수집·대조 (2026-11-23~24)** → [results/api_vs_file_20261123.json](results/api_vs_file_20261123.json)

- 42개 업종 299,684행(파일 사이트 2026-11-06 압축 299,362행). 업종·자치단체별 totalCount = 받은 행 수(42/42).
- 키 대조: 둘 다 있음 299,358 · API에만 326(11-06 이후 신규) · 파일에만 4(미용업, 원천 삭제) · 둘 다 있는데 값이 다름 1,156건은 모두 파일 이후 갱신된 행 · **설명 안 되는 값 차이 0**.
- API에 없는 필드(업종마다 인허가취소일자·소재지면적·업태구분명·위생업태명 일부)는 지금 파일에서도 모두 비어 있거나 열이 없다 → 잃는 정보 없음.
- 포털이 느리고 들쭉날쭉하다: 깊은 페이지는 한 페이지 약 40초, 504가 연속으로 난다. 첫 실행에서 일반음식점·휴게음식점·건강기능식품일반판매업이 6회 재시도 후 실패 → 재시도 10회·중간 저장·페이지 동시 받기(4개)로 고친 뒤 완료. 전체 수집은 여러 시간(일반음식점 97,792행만 약 1시간, 동시 받기 적용 후).

**첫 월간 교체 (2026-11-24, 로컬 원본만)**: `refresh_license monthly --from-dir data/raw_api/full_20261123` → 대조 통과, 이전 원본 42개를 `data/raw_archive/20261124/`로 옮기고 전체본 42개로 교체.

- 새 원본으로 임시 폴더에 배치를 돌려 확인(저장소 `data/processed`는 그대로): 정상 완료 37초, 기준일 2026-11-06 → **2026-11-22**, 인허가 286,896 → 287,203, 현재 영업 중 84,444 → 84,275, 자리 90,683 → 90,711, 업종 전이 24,257 → 24,284, 공실 구간 표·상권 사이클·생존 표 행 수 변화 없음.

**남은 것**: 새 원본을 `data/processed`·DB에 반영하는 것은 기존 데이터 갱신 절차(배치 → 점수 계산 → 점검 → 적재 → 전환, [TEAM_WORKFLOW](../TEAM_WORKFLOW.md))로 따로 한다. 첫 주간 갱신은 다음 주(약 2026-11-30)에 `refresh_license weekly`로 시험. 정기 실행(작업 스케줄러 등)은 주간 갱신을 몇 번 손으로 돌려 본 뒤 정한다.

## 5단계: 새 원본 운영 반영 (기준일 2026-11-22)

2026-11-24 · 염동권 요청 "새 원본 DB 반영하고 배포까지". 모델 결과 3종이 기준일 2026-11-06에 묶여 있어 데이터만 바꾸면 화면마다 기준일이 섞인다 → **점수도 새 기준일로 다시 계산**(염동권 결정).

**1) 배치**: `python -m pipeline.build` → 기준일 2026-11-22, 인허가 287,203, 가게 272,273, 영업 중 84,275, 자리 90,711. 보조 배치(`pipeline.external`)는 인허가를 쓰지 않아 그대로.

**2) 모델 표 재계산** (모델 설정·학습 규칙은 그대로, 입력 데이터와 기준일만 바뀜)

| 표 | 실행 | 결과 |
| --- | --- | --- |
| E-03 공실 재입점 `vacancy_scores` | `scripts/e03_vacancy_scores/step1~3` (새 환경 `C:/claude_workspace/e05_env`, `scripts/e05_vacancy/requirements.txt` 고정 버전) → `export_service_scores.py` | 후보 4,266곳(v15 4,316), 사례 연결 100%. 1년 안 재입점 확률 평균 5.0% → 5.1%. 누수 점검 T1~T3 불일치 0. 요약 [step1](../e03/results/step1_episodes_2026-11-22.json)·[step2](../e03/results/step2_features_2026-11-22.json)·[step3](../e03/results/step3_scores_2026-11-22.json), 점수표 `e05_data/serve/scores/vacancy_scores_2026-11-24.parquet` SHA-256 `2f7c7378…cc3f54` |
| E-09 다음 업종 `next_tenant_scores` | `E09_INPUT=service/data/processed` `serve_scores.py` → `export_service_scores.py` | 4,266곳, 학습 9,766행(랜드마크 ≤ 2024-11-22). 평가받은 모델과 1순위 일치 81.2%(이전 81.8%). [요약](../e09/results/serve_scores.json) |
| E-06 1년 폐업 예측 `competition_forecast` | `service_backtest.py`(새 기준일) → `service_forecast.py` | 기간 2026-11-23~2027-11-22(날짜 이동 55 → 39일). 점검: 2020~2026 매년 G1 < 기준선, MAE 2.50 vs 최선 기준선 2.93(−14.7%, 95% 구간 상한 < 0), 80% 범위 적중 84.7%(이전 85.2%). 822행(이전 777, E-12로 구가 살아난 동물·건강기능식품 업태 6개 추가). [점검](../e06/results/service_backtest_2026-11-22.json)·[예측](../e06/results/service_forecast.json) |

**스크립트 수정(새 데이터로 돌게 한 것만, 모델·판정 기준 변경 없음)**
- E-03 step1·step2, E-09 `serve_scores.py`: 번지 가림 인허가(E-12 이후 `uid` 없음)는 자리가 없어 사례에서 제외.
- E-03 step1·step2의 실험 고정 빌드 비교: 행 수·가게 ID가 달라져도 돌도록 키로 맞춰 둘 다 있는 행만 비교(진단용 기록).
- E-09 `serve_scores.py`: 이웃·동네 변수용 인허가 표를 `E09_INPUT`으로 지정(기본은 실험 고정 빌드). 인구 변수용 법정동 대응표는 학습 때와 같은 고정본.
- E-06: 날짜 이동 일수를 기준일에서 계산. 예측 전 사전 점검은 같은 기준일 점검 결과(`service_backtest_<기준일>.json`, 결정 당시 11-06은 `service_backtest.json` 그대로)의 2026 기간 MAE와 같아야 하고, 그 점검에서 G1이 기준선보다 나을 때만 예측. 범위 적중률도 그 점검 값.
- 앱: 폐업 예측 설명의 "11월 7일~다음 해 11월 6일"을 표의 기간에서 읽도록(`ui_forecast.py`), 테스트도 같게.

**3) 점검**: `check_data` OK 37·WARN 0·FAIL 0(점수 기준일 = 인허가 기준일 2026-11-22). service 테스트 161개·smoke 통과.

**4) 적재·전환·배포**: 공유 DB v16 적재(검증 통과, 211초, DB 2,870MB) → `check_data --db --version 16` OK 96·WARN 1·FAIL 0 → `--activate-version 16`(v15 retired, 되돌리기 `--activate-version 15`) → `check_data --db` OK 95·WARN 1(DB 크기)·FAIL 0 → `deploy_check pre` 통과 → `deploy` f6dfba5→23f5fe9 → Reboot → `post` 통과. 화면: `데이터 db v16`, 기준일 2026-11-22, 영업 중 84,275건, 폐업 예측 '앞으로 1년(2026.11.23~2027.11.22)'·'기간은 11월 23일~다음 해 11월 22일', 범위 '약 85%', 오류 없음.

## 사용 규칙

- 인허가 원본 갱신: 매주 `python -m pipeline.refresh_license weekly`, 월 1회 `python -m pipeline.refresh_license monthly`(대조 이상이면 원본을 바꾸지 않고 멈춤)
- 데이터 갱신(`pipeline.build`) 뒤 `main`에 올리기 전: `python -m pipeline.check_data`
- DB 버전 전환 뒤: `python -m pipeline.check_data --db`
- `deploy` 올리기 전: `python3 scripts/deploy_check.py pre`, 푸시·Reboot 뒤: `python3 scripts/deploy_check.py post`와 화면의 "데이터 db v<번호>" 확인
- FAIL이면 전환·배포하지 않고 원인을 고친다. WARN은 이유를 작업판 기록에 남긴다.
