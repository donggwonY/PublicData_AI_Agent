# 학습에서 보지 못한 건물의 예측 점검

세 그룹은 기초학습 등장 / 보정에만 등장 / 둘 다 미등장으로 나눈다. 미등장은 신규 독립 시험이나 이력 없음과 다르다.

| 기간 | 그룹 | 후보 | 표본 | 신고 | Brier 감소 | log loss 감소 | 소표본 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 2015-2016 | seen_training | building_rf | 845 | 59 | -0.0002774 | -0.0018168 | False |
| 2015-2016 | seen_training | building_calibrated | 845 | 59 | -0.0003675 | -0.0022610 | False |
| 2015-2016 | calibration_only | building_rf | 290 | 19 | -0.0001775 | -0.0014416 | False |
| 2015-2016 | calibration_only | building_calibrated | 290 | 19 | -0.0002852 | -0.0020062 | False |
| 2015-2016 | unseen_both | building_rf | 4193 | 239 | +0.0000264 | +0.0002692 | False |
| 2015-2016 | unseen_both | building_calibrated | 4193 | 239 | +0.0000259 | +0.0002492 | False |
| 2017-2018 | seen_training | building_rf | 1146 | 103 | +0.0003785 | +0.0028348 | False |
| 2017-2018 | seen_training | building_calibrated | 1146 | 103 | +0.0003721 | +0.0034115 | False |
| 2017-2018 | calibration_only | building_rf | 376 | 28 | -0.0000778 | -0.0001610 | False |
| 2017-2018 | calibration_only | building_calibrated | 376 | 28 | -0.0000350 | +0.0001131 | False |
| 2017-2018 | unseen_both | building_rf | 4030 | 290 | +0.0000944 | +0.0005188 | False |
| 2017-2018 | unseen_both | building_calibrated | 4030 | 290 | +0.0000252 | +0.0002205 | False |
| 2020-2021 | seen_training | building_rf | 2047 | 169 | +0.0006944 | +0.0036194 | False |
| 2020-2021 | seen_training | building_calibrated | 2047 | 169 | +0.0008653 | +0.0041870 | False |
| 2020-2021 | calibration_only | building_rf | 365 | 21 | +0.0001899 | +0.0007070 | False |
| 2020-2021 | calibration_only | building_calibrated | 365 | 21 | +0.0001645 | +0.0006375 | False |
| 2020-2021 | unseen_both | building_rf | 3146 | 196 | +0.0001864 | +0.0011966 | False |
| 2020-2021 | unseen_both | building_calibrated | 3146 | 196 | +0.0002158 | +0.0014358 | False |

양수는 대응 대조보다 오차 감소. 이전 전체 점수 재현·그룹 합계·가중지표 검사를 통과했다. 불확실성 재표집은 이번 그룹별로 수행하지 않았다. 현재주소/면적 시점 및 반복 사용한 검증기간 한계 유지. 2025 재평가 없음.

[계획](building_novelty_plan.md), [결과](building_novelty.json).

## 해석

학습·보정에 모두 등장하지 않은 건물 그룹에서 두 건물이력 모델의 Brier·log loss 점추정은 세 기간 모두 대응 대조보다 작았다. 표본은 기간별4,193/4,030/3,146건, 신고239/290/196건이다. 따라서 개선이 학습에 등장한 건물에만 한정된다는 설명과는 맞지 않는다.

차이는 작으며 그룹별 재표집 구간은 계산하지 않았다. 이 결과만으로 새 건물 일반화나 유의한 개선을 확정하지 않는다. 과거 건물 이력이 없는 표본만 따로 평가한 것도 아니다. 기존 전체표본의 첫 기간 악화 및 전기간 채택 기준 미통과는 유지한다. 이 그룹만 골라 서비스에 채택하지 않는다. 2025 동구 오차 해결 여부는 미평가다.
