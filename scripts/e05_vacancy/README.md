# E-05 공실 해소 기간 예측 실험 코드

실험 설명·결과는 [docs/e05/README.md](../../docs/e05/README.md). 이 폴더는 최종본(v2) 결과를 다시 만드는 코드다.
2026-11-08~09 스크래치에서 실행한 코드를 2026-11-10 옮기며 **경로 처리만** 바꿨다(분석 로직 변경 없음).

## 입력(저장소에 올리지 않음)
| 환경변수 | 내용 |
|---|---|
| `E05_WORK` | 작업 폴더. `input/`에 고정 빌드 8개 파일(`stores`·`units`·`transitions`·`survival`·`area_cycle`·`area_year`·`vacancy_area` parquet, `meta.json`)과 법정동→행정동 대응표 `legal_admin_map.parquet`(커밋 3fea4ca 버전: `git show 3fea4ca:service/data/processed/legal_admin_map.parquet`). 해시는 [results/input_sha256.txt](../../docs/e05/results/input_sha256.txt) |
| `E05_AUX` | 보조 자료: `subway/subway_monthly.csv`, `station/daegu_station_location.xlsx`, `population/pop_*.csv`, `sangga/sangga_daegu_YYYYMMDD.csv`(44개 분기) |

- 고정 빌드는 2026-11-09 `service/pipeline/build.py`(42종·겸업 묶기·비점포 업태 제외, **단기 행사 규칙 이전**) 산출물이다. 지금 코드로 다시 빌드하면 `short_event` 열이 추가돼 해시가 달라지므로 고정본을 써야 한다.
- 보조 자료 출처: 상가정보 공공데이터포털 15083033(`dl_sangga.py`, `sg_list.tsv`), 인구 jumin.mois.go.kr 연령별 월별(`dl_population.sh`), 지하철 대구교통공사 월별 승차, 역 좌표 철도데이터포털. 받은 날짜와 범위는 [vacancy_fill_plan.md](../../docs/e05/vacancy_fill_plan.md) 진행 기록.
- 상가정보 업종 대응표는 `docs/e05/sangga_category_map.csv`에서 읽는다.
- 주의(2026-11-11 발견): 상가정보 2025-03-31 분기 원본만 좌표가 대구 밖으로 어긋나 있다(주소는 정상). 이 실험(2023년 폐업까지)은 그 분기를 쓰지 않아 영향이 없고, 2024년 이후 사례를 쓰는 E-03 점수 배치에서 직전 분기 좌표로 보정한다([설명](../../docs/e03/vacancy_scores_step2.md#발견한-원본-오류-상가정보-2025-03-31-분기-좌표)).
- 대응표를 고정하는 이유: 실험 때는 `service/data/processed/legal_admin_map.parquet`를 직접 읽었는데, 이 파일이 실험 직후 637fc00에서 다시 만들어져 지금 파일로 돌리면 인구 변수 579/28,570건이 달라진다. 그래서 실험 당시 버전을 입력에 넣고 해시를 추가했다(2026-11-10, 기존 8개 해시는 그대로).

## 재현 확인 (2026-11-10)
이 폴더의 코드로 새 작업 폴더에서 `run_all.sh` 전체를 실행해 `docs/e05/results/`의 json 11개와 비교했다. 실행 시간 항목을 뺀 모든 값이 같다(다른 값은 부동소수점 마지막 자리 1e-17 수준 12개). 판정·선택된 설정값 변화 없음. Windows 11, Python 3.12.10, `requirements.txt` 환경.

## 환경
Python 3.12, `requirements.txt`(서비스 환경과 별개). 0단계 `episodes.py`만 `service/.venv`로 실행한다.

## 실행
```bash
E05_WORK=<작업폴더> E05_AUX=<보조폴더> PY=<실험 python> SVC_PY=service/.venv/Scripts/python.exe bash scripts/e05_vacancy/run_all.sh
```
입력 해시를 먼저 검사하고, 아래 순서로 실행해 `E05_WORK`에 중간 parquet와 결과 json을 만든다(약 30분).

| 순서 | 스크립트 | 결과 |
|---|---|---|
| 0 | `episodes.py` | 공실 사례 표 `episodes_report.json` |
| 1 | `run_asof.py`(`asof.py`, `ext.py`) → `test_asof.py` | 시점 기준 변수 `asof_report.json`, 누수 테스트 `test_asof_result.json` |
| 2 | `baseline.py` | 기준선 `baseline_valid.json` |
| 3 | `models.py`(`mlib.py`), `stage1_fix.py` | 모델 비교 `models_valid.json`, 1단계 재정의 `stage1_fix.json` |
| 4 | `run_sangga.py`(`sangga.py`) → `test_sangga.py` → `models_sangga.py` | 상가정보 변수·누수 테스트·비교 `sangga_report.json`, `test_sangga_result.json`, `models_sangga.json` |
| 5 | `final_test.py` | 평가 구간 최종 `final_test.json` |
| 6 | `leakage_compare.py` → `leakage_ablation.py` | 누수 비교 `leakage_compare.json` |
| 7 | `conditional_check.py` (2026-11-10 추가, `run_all.sh` 밖에서 따로 실행) | 오래 빈 자리 조건부 확률 사후 점검 `conditional_check.json`(약 11분) |

결과 json 사본은 `docs/e05/results/`에 있다.
