# D-03 실험 비교 화면

2026-10-28 로컬 구현 및 검사 완료. `service/experiment_app.py`를 별도 실행한다. 공개 앱 배포·DB 적재·개인별 예측은 수행하지 않았다.

## 화면 공유

검증 기간을 바꾸며 실제 신고 비율, 모델별 평균 예측, 확률 오차를 비교한다. 2015~2016년만 두 확률 오차가 기존 모델보다 개선되고 다른 두 기간은 악화한다. 평균 예측 확률은 정확도가 아님을 화면에서 설명한다. 세 기간의 동일 표본 비교표, 표본 누락, 입력 정의와 해석 한계, 집계 JSON 다운로드를 제공한다.

## 실행

서비스 의존성을 설치한 Python3.12 환경에서 service 디렉터리 기준:

```text
python -m streamlit run experiment_app.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8513 --server.headless true
```

로컬 주소: http://127.0.0.1:8513 . 실행 프로세스가 종료되면 재실행이 필요하다. 저장소 전체의 docs/d03/historical_context.json이 필요하다. DB·LLM 인증은 필요하지 않다.

## 검증과 제한

Streamlit AppTest로 세 기간 선택 시 저장된 표본 수·실제 비율 표시와 예외 없음을 확인했다. 서로 다른 표본 및 실제 비율 불일치 파일 거부를 검증했다. `tests.test_experiment_app` 3개와 기존 `tests.test_core_units` 14개, Parquet 기반 `tests.smoke_test` 전체 통과. 별도 로컬 서버 시작 확인. 실제 브라우저의 시각 배치 검토는 별도다.

현재 PC는 별도 임시 설치 환경에서 Streamlit1.64.0·pandas3.0.1·numpy2.3.5·pyarrow24.0.0을 사용했다. 서비스 고정 pandas/numpy 버전과 달라 배포 환경 검증 완료를 뜻하지 않는다. 운영 진입점 app.py는 변경하지 않았다.

## 면적·보정 비교 추가

기본 화면을 면적·확률 보정으로 확장했다. 라디오로 기존 주변상권 비교도 유지. 2025년1608건 동일표본4모델,보정전후 평균/오차/AUC,건물재표집구간0포함 안내,확률구간표 전환,회의 설명,JSON다운로드 제공. 전체학습RF와보정기초RF의학습량차이·2025재사용·면적시점미확인 강조. 운영앱 진입점은 변경없음. 관련22개단위/AppTest 및smoke 통과. 로컬8513 health확인,브라우저시각레이아웃은 별도미검수.
