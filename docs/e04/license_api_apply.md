# 인허가 42종 API 활용신청 목록

2026-11-22 · 염동권 · [E-04](README.md) 데이터 주간 갱신 준비. 앱이 쓰는 점포형 42개 업종(`service/config.py` `SERVICES`)의 공공데이터포털 API.

## 신청 방법

1. 공공데이터포털(data.go.kr)에 로그인한다.
2. 아래 표의 링크를 열고 오른쪽 위 **활용신청**을 누른다. 활용목적은 예: "대구 상권 분석 서비스(교육·연구용) 인허가 자료 갱신". 개발계정은 자동 승인된다.
3. 42개를 모두 신청한 뒤 `service/.venv/Scripts/python scripts/check_license_api_access.py`로 승인 여부를 확인한다(키는 기존 `.env`의 `DATA_GO_KR_SERVICE_KEY` 그대로, 키 값은 출력하지 않음). 승인 직후 몇 분~1시간은 403이 날 수 있다.

개발계정 한도는 API마다 하루 10,000건, 한 페이지 100건. 대구 전체 첫 수집은 약 2,900회(42개 API에 나뉨), 주간 갱신은 바뀐 행(`DAT_UPDT_PNT`)만 받는다.

2026-11-22 확인: 42개 모두 미승인(HTTP 403). → 2026-11-23 염동권 활용신청 후 확인: **42개 모두 승인**(403 0건). 첫 확인에서 18개가 시간 초과·HTTP 504였으나 다시 시도하자 모두 정상 응답 — 포털 서버 응답이 들쭉날쭉하므로 수집 스크립트는 시간 초과·5xx를 재시도해야 한다(확인 스크립트도 3회 재시도로 수정).

| # | 업종 | 공공데이터포털 이름 | 신청 페이지 | API 경로 |
| ---: | --- | --- | --- | --- |
| 1 | 일반음식점 | 행정안전부_식품_일반음식점 조회서비스 | [15154916](https://www.data.go.kr/data/15154916/openapi.do) | `general_restaurants` |
| 2 | 휴게음식점 | 행정안전부_식품_휴게음식점 조회서비스 | [15154921](https://www.data.go.kr/data/15154921/openapi.do) | `rest_cafes` |
| 3 | 제과점영업 | 행정안전부_식품_제과점영업 조회서비스 | [15155252](https://www.data.go.kr/data/15155252/openapi.do) | `bakeries` |
| 4 | 미용업 | 행정안전부_생활_미용업 조회서비스 | [15154918](https://www.data.go.kr/data/15154918/openapi.do) | `beauty_salons` |
| 5 | 세탁업 | 행정안전부_생활_세탁업 조회서비스 | [15154927](https://www.data.go.kr/data/15154927/openapi.do) | `laundries` |
| 6 | 노래연습장업 | 행정안전부_문화_노래연습장업 조회서비스 | [15155135](https://www.data.go.kr/data/15155135/openapi.do) | `karaoke_rooms` |
| 7 | 담배소매업 | 행정안전부_기타_담배소매업 조회서비스 | [15155031](https://www.data.go.kr/data/15155031/openapi.do) | `tobacco_retailers` |
| 8 | 의원 | 행정안전부_건강_의원 조회서비스 | [15154874](https://www.data.go.kr/data/15154874/openapi.do) | `clinics` |
| 9 | 병원 | 행정안전부_건강_병원 조회서비스 | [15154458](https://www.data.go.kr/data/15154458/openapi.do) | `hospitals` |
| 10 | 약국 | 행정안전부_건강_약국 조회서비스 | [15154822](https://www.data.go.kr/data/15154822/openapi.do) | `pharmacies` |
| 11 | 체력단련장업 | 행정안전부_생활_체력단련장업 조회서비스 | [15155077](https://www.data.go.kr/data/15155077/openapi.do) | `fitness_centers` |
| 12 | 인터넷컴퓨터게임시설제공업 | 행정안전부_문화_인터넷컴퓨터게임시설제공업 조회서비스 | [15154951](https://www.data.go.kr/data/15154951/openapi.do) | `pc_bangs` |
| 13 | 당구장업 | 행정안전부_생활_당구장업 조회서비스 | [15155011](https://www.data.go.kr/data/15155011/openapi.do) | `billiard_halls` |
| 14 | 체육도장업 | 행정안전부_생활_체육도장업 조회서비스 | [15155085](https://www.data.go.kr/data/15155085/openapi.do) | `martial_arts_dojo` |
| 15 | 골프연습장업 | 행정안전부_생활_골프연습장업 조회서비스 | [15154975](https://www.data.go.kr/data/15154975/openapi.do) | `golf_practice_ranges` |
| 16 | 축산판매업 | 행정안전부_식품_축산판매업 조회서비스 | [15154871](https://www.data.go.kr/data/15154871/openapi.do) | `livestock_retail` |
| 17 | 단란주점영업 | 행정안전부_식품_단란주점영업 조회서비스 | [15154883](https://www.data.go.kr/data/15154883/openapi.do) | `singing_bars` |
| 18 | 유흥주점영업 | 행정안전부_식품_유흥주점영업 조회서비스 | [15154890](https://www.data.go.kr/data/15154890/openapi.do) | `entertainment_bars` |
| 19 | 관광식당 | 행정안전부_식품_관광식당 조회서비스 | [15154897](https://www.data.go.kr/data/15154897/openapi.do) | `tourist_restaurants` |
| 20 | 관광유흥음식점업 | 행정안전부_식품_관광유흥음식점업 조회서비스 | [15154903](https://www.data.go.kr/data/15154903/openapi.do) | `tourist_entertainment_restaurants` |
| 21 | 외국인전용유흥음식점업 | 행정안전부_식품_외국인전용유흥음식점업 조회서비스 | [15154910](https://www.data.go.kr/data/15154910/openapi.do) | `foreigners_entertainment_restaurants` |
| 22 | 즉석판매제조가공업 | 행정안전부_식품_즉석판매제조가공업 조회서비스 | [15155245](https://www.data.go.kr/data/15155245/openapi.do) | `instant_food_processors` |
| 23 | 식품판매업(기타) | 행정안전부_식품_식품판매업(기타) 조회서비스 | [15155170](https://www.data.go.kr/data/15155170/openapi.do) | `other_food_retailers` |
| 24 | 건강기능식품일반판매업 | 행정안전부_식품_건강기능식품일반판매업 조회서비스 | [15155221](https://www.data.go.kr/data/15155221/openapi.do) | `health_functional_food_general_retailers` |
| 25 | 안경업 | 행정안전부_건강_안경업 조회서비스 | [15154899](https://www.data.go.kr/data/15154899/openapi.do) | `optical_shops` |
| 26 | 의료유사업 | 행정안전부_건강_의료유사업 조회서비스 | [15154864](https://www.data.go.kr/data/15154864/openapi.do) | `medical_related_businesses` |
| 27 | 동물병원 | 행정안전부_동물_동물병원 조회서비스 | [15154952](https://www.data.go.kr/data/15154952/openapi.do) | `animal_hospitals` |
| 28 | 동물약국 | 행정안전부_동물_동물약국 조회서비스 | [15155272](https://www.data.go.kr/data/15155272/openapi.do) | `animal_pharmacies` |
| 29 | 동물미용업 | 행정안전부_동물_동물미용업 조회서비스 | [15154944](https://www.data.go.kr/data/15154944/openapi.do) | `pet_grooming` |
| 30 | 동물판매업 | 행정안전부_동물_동물판매업 조회서비스 | [15155083](https://www.data.go.kr/data/15155083/openapi.do) | `animal_sales` |
| 31 | 동물위탁관리업 | 행정안전부_동물_동물위탁관리업 조회서비스 | [15155055](https://www.data.go.kr/data/15155055/openapi.do) | `animal_boarding` |
| 32 | 이용업 | 행정안전부_생활_이용업 조회서비스 | [15154922](https://www.data.go.kr/data/15154922/openapi.do) | `barber_shops` |
| 33 | 목욕장업 | 행정안전부_생활_목욕장업 조회서비스 | [15155091](https://www.data.go.kr/data/15155091/openapi.do) | `public_baths` |
| 34 | 무도학원업 | 행정안전부_생활_무도학원업 조회서비스 | [15155029](https://www.data.go.kr/data/15155029/openapi.do) | `dance_academies` |
| 35 | 무도장업 | 행정안전부_생활_무도장업 조회서비스 | [15155022](https://www.data.go.kr/data/15155022/openapi.do) | `dance_halls` |
| 36 | 청소년게임제공업 | 행정안전부_문화_청소년게임제공업 조회서비스 | [15154958](https://www.data.go.kr/data/15154958/openapi.do) | `youth_game_providers` |
| 37 | 일반게임제공업 | 행정안전부_문화_일반게임제공업 조회서비스 | [15154955](https://www.data.go.kr/data/15154955/openapi.do) | `general_game_providers` |
| 38 | 복합유통게임제공업 | 행정안전부_문화_복합유통게임제공업 조회서비스 | [15154945](https://www.data.go.kr/data/15154945/openapi.do) | `mixed_game_providers` |
| 39 | 비디오물감상실업 | 행정안전부_문화_비디오물감상실업 조회서비스 | [15155128](https://www.data.go.kr/data/15155128/openapi.do) | `video_viewing_rooms` |
| 40 | 비디오물소극장업 | 행정안전부_문화_비디오물소극장업 조회서비스 | [15155043](https://www.data.go.kr/data/15155043/openapi.do) | `video_mini_theaters` |
| 41 | 복합영상물제공업 | 행정안전부_문화_복합영상물제공업 조회서비스 | [15154937](https://www.data.go.kr/data/15154937/openapi.do) | `mixed_video_content_providers` |
| 42 | 비디오물시청제공업 | 행정안전부_문화_비디오물시청제공업 조회서비스 | [15155059](https://www.data.go.kr/data/15155059/openapi.do) | `video_streaming_providers` |

기계용 목록: [license_apis.json](license_apis.json). API 주소 앞부분은 모두 `https://apis.data.go.kr/1741000/`, 현재 자료는 `/info`, 과거 스냅샷은 `/history`.
