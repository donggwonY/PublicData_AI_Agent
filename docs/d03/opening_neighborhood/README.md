# 주변 업종 구성 및 영업 지속 분석 검증

기준일 2026-11-06. 기존 결과를 재실행한 탐색 분석이며 새로운 독립 최종평가가 아니다. 인과관계·창업 추천·개별 폐업 확률의 서비스 적용을 검증한 결과가 아니다.

## 모델 비교

아래는 주변 가게 수를 포함한 모델(density)에 동종 업종 비중·다양성을 추가한 모델(summary)의 Brier 오차 상대 감소율이다. 양수는 감소, 음수는 증가이며 정확도 증가율이 아니다.

|추적일|거리|검사|개업연도|평가행|Brier 상대 감소(%)|log loss 변화(추가−기준)|
|---|---|---|---|---:|---:|---:|
|365|300|unweighted|2022|8642|2.9130|-0.006102|
|365|300|unweighted|2023|8153|2.7048|-0.007007|
|365|300|unweighted|2024|7504|2.8694|-0.007254|
|365|300|exclude_30day|2022|8292|0.9375|-0.002201|
|365|300|exclude_30day|2023|7811|1.3020|-0.003326|
|365|300|exclude_30day|2024|7138|0.8448|-0.002209|
|365|300|building_weight|2022|8642|0.0901|-0.000019|
|365|300|building_weight|2023|8153|0.2276|-0.000418|
|365|300|building_weight|2024|7504|0.2244|-0.000881|
|365|300|exclude_instant_food|2022|7438|0.1960|-0.000761|
|365|300|exclude_instant_food|2023|7214|0.3832|-0.001282|
|365|300|exclude_instant_food|2024|6501|0.4317|-0.001824|
|365|300|unseen_building|2022|3430|0.0158|0.000465|
|365|300|unseen_building|2023|2941|0.2244|-0.000024|
|365|300|unseen_building|2024|2600|0.1623|-0.000621|
|365|300|joint_sensitivity|2022|8292|0.0108|0.000097|
|365|300|joint_sensitivity|2023|7811|0.1015|0.000034|
|365|300|joint_sensitivity|2024|7138|0.0796|-0.000497|
|1095|300|building_weight|2020|8580|-0.0579|0.000466|
|1095|300|building_weight|2021|9127|-0.0224|0.000033|
|1095|300|building_weight|2022|8642|0.1150|-0.000471|
|365|500|unweighted|2022|8642|1.2112|-0.002419|
|365|500|unweighted|2023|8153|0.9996|-0.003049|
|365|500|unweighted|2024|7504|0.5469|-0.001901|
|365|500|exclude_30day|2022|8292|0.4171|-0.000976|
|365|500|exclude_30day|2023|7811|0.5444|-0.001470|
|365|500|exclude_30day|2024|7138|0.2206|-0.001103|
|365|500|building_weight|2022|8642|-0.0022|0.000221|
|365|500|building_weight|2023|8153|0.0691|-0.000236|
|365|500|building_weight|2024|7504|0.1014|-0.000599|
|365|500|exclude_instant_food|2022|7438|0.1074|-0.000481|
|365|500|exclude_instant_food|2023|7214|0.3343|-0.001479|
|365|500|exclude_instant_food|2024|6501|0.5756|-0.002325|
|365|500|unseen_building|2022|3430|-0.0556|0.000527|
|365|500|unseen_building|2023|2941|-0.0267|0.000134|
|365|500|unseen_building|2024|2600|0.2914|-0.001228|
|365|500|joint_sensitivity|2022|8292|-0.0157|0.000135|
|365|500|joint_sensitivity|2023|7811|0.0587|-0.000251|
|365|500|joint_sensitivity|2024|7138|0.1576|-0.000729|
|1095|500|building_weight|2020|8580|-0.0584|0.000360|
|1095|500|building_weight|2021|9127|-0.0356|0.000130|
|1095|500|building_weight|2022|8642|0.1254|-0.000642|

## 해석
주변 정보 추가의 초기 개선은 반복 건물 가중·단기 운영 제외 후 크게 줄었다. 구체 업종 추가는 두 오차가 함께 안정적으로 개선되는 결과를 보이지 않았다. 3년 결과도 연도에 따라 혼재한다. 모든 조건을 함께 보고하며 유리한 실험만 대표 결과로 선택하지 않는다.

## 지역별 기록 비교
2018–2022년 개업 44953건을 같은 업종의 개업연도 비중으로 맞췄다. 지역별 수치와 반복 건물·30일 이하 제외 민감도는 regional_cohort_comparison.csv에 있다. 좌표 없는 기록도 지역 비교에는 포함되므로 공간 분석과 표본이 다르다. 3년은1095일, 1년은365일이며 폐업 신고 미관측 비율을 실제 사업 성공률로 해석하지 않는다.

## 재실행
저장소 루트에서 service/.venv/Scripts/python.exe scripts/analyze_opening_neighborhood.py 로 기초 특성을 생성한 뒤 service/.venv/Scripts/python.exe scripts/reproduce_opening_neighborhood_checks.py 실행. 원본·특성·스크립트 해시는 JSON에 기록한다.

## 한계
- Current snapshot coordinates and region reconstruct history; relocation/reporting availability unknown.
- Permits are not unique businesses; missing building IDs fall back to record IDs.
- Removing <=30day outcomes is sensitivity only, changes target population, not deployable filtering.
- All spatial features count raw eligible permits, including same-building neighbors; outcome weighting does not remove feature duplication.
- No spatial cluster confidence intervals, multiple-testing adjustment or causal claim.
- Regional n30/year display flag and spatial n200/events20 screening are not statistical significance.
- Specific exposure fits only use 2016-2024 generated named counts; 3year models do not use these columns.
