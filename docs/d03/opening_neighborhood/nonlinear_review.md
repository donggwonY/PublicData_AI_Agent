# 주변 업종 구성의 비선형 비교

고정 설정의 트리 모델로 가게 수만 포함한 경우와 업종 구성까지 추가한 경우를 비교했다. 같은 결과를 반복 확인한 탐색 분석이며 독립 최종평가가 아니다. 세부 업태는 제외했다.

|반경|연도|기준|추가|Brier 상대 감소(%)|log loss 차이|
|---|---|---|---|---:|---:|
|300|2022|permit_density|permit_summary|0.2058|-0.000684|
|300|2023|permit_density|permit_summary|0.2757|-0.000421|
|300|2024|permit_density|permit_summary|0.2717|0.000083|
|500|2022|permit_density|permit_summary|-0.0514|-0.000301|
|500|2023|permit_density|permit_summary|0.0343|-0.000220|
|500|2024|permit_density|permit_summary|0.0948|-0.000483|
|300|2022|building_density|building_summary|0.0939|-0.000263|
|300|2023|building_density|building_summary|0.2646|-0.000551|
|300|2024|building_density|building_summary|0.7287|-0.001899|
|500|2022|building_density|building_summary|-0.2514|0.000832|
|500|2023|building_density|building_summary|-0.0588|0.000144|
|500|2024|building_density|building_summary|-0.0502|0.000267|

건물 가중은 기록이 많은 건물의 영향을 줄이는 목적이며 표본의 의미를 바꾼다. 공간적 상관·과거 좌표·신고 지연·반복 평가 한계는 유지된다. 선형 대비 개선이 있더라도 주변 정보의 효과는 같은 트리 모델 내 비교로 따로 판단한다. 공개 서비스 변경 없음.
