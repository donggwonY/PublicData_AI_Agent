# E-04 자동 검사·배포 점검

담당 염동권 · 시작 2026-11-20 · [작업판](../WORKBOARD.md) E-04

질문: "배포하거나 DB 버전을 바꿀 때, 표가 비거나 키가 겹치거나 앱과 DB가 다른 데이터를 보는 일을 사람이 눈으로 찾지 않고 알아챌 수 있나?"

## 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | [데이터 계약](../e02/data_contract.md) 5절의 수동 검사를 읽기 전용 점검 스크립트로 만들고, 현재 parquet·공유 DB v10에 실행 | 완료 2026-11-20 |
| 2 | 적재 스크립트(`load_supabase`)가 적재 전에 같은 점검을 돌려 FAIL이면 적재하지 않기. 2026-11-13 보류 안건(전환 시 권한 재생성 제거·잠금 대기 제한·용량 상한 기본값·retired 버전 삭제) 반영 | 완료 2026-11-20 (DB 실행 없음, 옛 버전은 보존) |
| 3 | 배포 확인 자동화: `deploy` 올리기 전후 점검·공개 앱 응답·화면 버전 확인 | 완료 2026-11-20 (실패 알림·CI는 후속 후보) |

## 1단계: 데이터 점검 스크립트

**실행** (`service/` 안, 서비스 가상환경)

```powershell
python -m pipeline.check_data                    # 저장소 parquet 만
python -m pipeline.check_data --db               # + 공유 DB 현재 버전, parquet 와 대조
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
| 행정동 미연결 비율 | 6.1% 넘으면 WARN | 수동 → 자동 |
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

**새 순서(데이터 갱신)**: `pipeline.build` → `check_data` → 테스트 → `main` → `load_supabase`(사전 점검 포함, 전환 없이) → `check_data --db --version <새 버전>` → `load_supabase --activate-version <새 버전>` → `check_data --db` → 공개 앱 Reboot·확인.

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
| pre·post | `check_data --db` | FAIL이 있으면 |
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

## 사용 규칙

- 데이터 갱신(`pipeline.build`) 뒤 `main`에 올리기 전: `python -m pipeline.check_data`
- DB 버전 전환 뒤: `python -m pipeline.check_data --db`
- `deploy` 올리기 전: `python3 scripts/deploy_check.py pre`, 푸시·Reboot 뒤: `python3 scripts/deploy_check.py post`와 화면의 "데이터 db v<번호>" 확인
- FAIL이면 전환·배포하지 않고 원인을 고친다. WARN은 이유를 작업판 기록에 남긴다.
