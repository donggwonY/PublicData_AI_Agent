# E-04 자동 검사·배포 점검

담당 염동권 · 시작 2026-11-20 · [작업판](../WORKBOARD.md) E-04

질문: "배포하거나 DB 버전을 바꿀 때, 표가 비거나 키가 겹치거나 앱과 DB가 다른 데이터를 보는 일을 사람이 눈으로 찾지 않고 알아챌 수 있나?"

## 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | [데이터 계약](../e02/data_contract.md) 5절의 수동 검사를 읽기 전용 점검 스크립트로 만들고, 현재 parquet·공유 DB v10에 실행 | 완료 2026-11-20 |
| 2 | 적재 스크립트(`load_supabase`)가 적재 전에 같은 점검을 돌려 FAIL이면 적재하지 않기. 2026-11-13 보류 안건(전환 시 권한 재생성 제거·잠금 대기 제한·용량 상한 기본값·retired 버전 삭제) 함께 검토 | 대기 |
| 3 | 배포 확인 자동화: `deploy` 올리기 전후 점검·공개 앱 기준일 확인, 실패 알림 | 대기 |

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

## 사용 규칙

- 데이터 갱신(`pipeline.build`) 뒤 `main`에 올리기 전: `python -m pipeline.check_data`
- DB 버전 전환(`--activate`) 뒤, `deploy` 올리기 전·후: `python -m pipeline.check_data --db`
- FAIL이면 전환·배포하지 않고 원인을 고친다. WARN은 이유를 작업판 기록에 남긴다.
