# 건물 단위 주변 업종 구성 검증

Building-normalized context; exploratory, not an untouched test.

|radius|year|comparison|Brier relative gain %|log loss difference|
|---|---|---|---:|---:|
|300|2022|permit_summary → building_summary|-0.0905|0.000044|
|300|2023|permit_summary → building_summary|-0.1524|0.000467|
|300|2024|permit_summary → building_summary|0.0624|-0.000109|
|500|2022|permit_summary → building_summary|-0.0788|0.000219|
|500|2023|permit_summary → building_summary|-0.0052|0.000120|
|500|2024|permit_summary → building_summary|0.0594|-0.000212|
|300|2022|building_density → building_summary|0.1437|-0.000656|
|300|2023|building_density → building_summary|0.0807|0.000214|
|300|2024|building_density → building_summary|0.3069|-0.000882|
|500|2022|building_density → building_summary|0.0086|0.000004|
|500|2023|building_density → building_summary|0.0325|0.000022|
|500|2024|building_density → building_summary|0.1615|-0.000593|
|300|2022|offsite_density → offsite_summary|0.1398|-0.000810|
|300|2023|offsite_density → offsite_summary|0.1179|-0.000023|
|300|2024|offsite_density → offsite_summary|0.1454|-0.000034|
|500|2022|offsite_density → offsite_summary|-0.0061|-0.000000|
|500|2023|offsite_density → offsite_summary|0.0183|0.000027|
|500|2024|offsite_density → offsite_summary|0.0894|-0.000367|
|300|2022|permit_summary → offsite_summary|-0.1070|-0.000087|
|300|2023|permit_summary → offsite_summary|-0.1281|0.000331|
|300|2024|permit_summary → offsite_summary|-0.0456|0.000422|
|500|2022|permit_summary → offsite_summary|-0.1301|0.000390|
|500|2023|permit_summary → offsite_summary|0.0254|-0.000105|
|500|2024|permit_summary → offsite_summary|0.0736|-0.001218|
|300|2022|permit_summary → subtype_control|0.1710|-0.000836|
|300|2023|permit_summary → subtype_control|0.1005|-0.000709|
|300|2024|permit_summary → subtype_control|0.0915|-0.000206|
|500|2022|permit_summary → subtype_control|0.1853|-0.000972|
|500|2023|permit_summary → subtype_control|0.1663|-0.000991|
|500|2024|permit_summary → subtype_control|0.0560|-0.000001|
|300|2022|subtype_control → subtype_building|-0.0920|-0.000018|
|300|2023|subtype_control → subtype_building|-0.1011|0.000170|
|300|2024|subtype_control → subtype_building|0.0239|-0.000063|
|500|2022|subtype_control → subtype_building|-0.1085|0.000358|
|500|2023|subtype_control → subtype_building|-0.0370|0.000310|
|500|2024|subtype_control → subtype_building|0.0848|-0.000451|

건물당1의 기여를 해당 건물에서 관측된 서로 다른 업종에 균등 배분한다. 따라서 비중은 점포 점유율이 아닌 건물 내 업종 구성의 요약값이다. 건물 내부의 실제 여러 점포를 하나의 가게로 간주하지 않는다. 동일 건물 포함·제외 조건을 모두 보고한다.

평가 표본·가중·학습기간·C값을 고정해 기존 결과와 비교했고 기존 permit_summary Brier 재현을 확인했다. category를 쓴 두 조건은 현재 기록의 세부 업태를 사용하므로 과거 입력 가능성을 확인한 것으로 해석하지 않는다.

상세 업종별 점수·해시·한계는 building_context_results.json. 원본 특성은 data/raw/d03/building_opening_context.parquet에 로컬 보관한다. 공개 앱·공유DB 변경 없음.
