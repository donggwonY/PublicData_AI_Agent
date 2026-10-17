# D-03 생존 기준선과 결과 예측 실험

**첫 실험 범위 완료 / 예측 모델 서비스 적용 보류.** 최신 결론과 남은 한계는 [완료 보고](closeout.md)를 기준으로 본다. 각 단계 보고서의 다음 단계 문구는 작성 당시 기록이다.

기준일 2026-10-13, 인허가 225,858건. 원천 업종명은 16개이고 의원·병원을 묶은 분석 그룹은 팀 합의대로 15개다. 원본 구분은 유지한다. 생존 요약 685행을 재현했으며 예측 실험은 일반음식점에 한정했다.

첫 모델의 최종 시험 평균 예측은 9.09%, 실제 365일 이내 폐업·취소·말소 신고 비율은 18.31%로 과소예측했다. 별도 동일 표본 비교에서 과거 구군 인구·세대수를 추가해도 확률 오차가 커졌다. 현재 후보는 서비스에 적용하지 않는다. 모든 추가 자료가 무용하다는 결론은 아니다.

## 근거와 재현 순서

| 단계 | 문서 또는 결과 | 실행 스크립트 (저장소 루트 기준) |
| --- | --- | --- |
| 생존 재현·표본 | [기준선 JSON](baseline.json) | `scripts/start_d03.py` |
| 질문·분할·입력 | [계획](protocol.md) | `scripts/plan_d03.py` |
| 첫 후보 검증 | [검증](validation.md) | `scripts/fit_d03.py` |
| 설정 고정 시험 | [최종 평가](final_evaluation.md) | `scripts/evaluate_d03.py` |
| 현재 자료 시점 점검 | [감사](auxiliary_audit.md) | `scripts/audit_d03_auxiliary.py` |
| 과거 인구 정리 | [준비](population_preparation.md), [결과 JSON](population_monthly.json) | `scripts/prepare_d03_population.py` |
| 인구 시차 연결 | [연결](population_join.md) | `scripts/join_d03_population.py` |
| 인구 추가 비교 | [후속 검증](population_validation.md) | `scripts/fit_d03_population.py` |

분석 환경·입력 해시는 각 JSON을 참조한다. 원본 인구 CSV는 Git 제외 대상이므로 팀 재현에는 별도 전달이 필요하다. D-02의 이전 7업종 스냅샷 결과와 혼합하지 않는다. 이번 작업에서 Supabase 변경과 서비스 배포는 하지 않았다.

팀 공유 및 논의 항목: [팀 전달문](team_handoff.md).
