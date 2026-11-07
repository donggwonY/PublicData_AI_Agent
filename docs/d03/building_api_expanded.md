# 건축물대장 소량 연결 점검

2026-11-07 주소코드 연결 가능 건물 중 구군별 최대10곳 무작위(seed7). 균등구군표집으로 대구 전체 대표비율 아님.

{"requested": 90, "responses": 90, "none": 10, "single": 69, "multiple": 11, "single_valid_approval_date": 67}

주소 필지단위 조회이며 점포 호실 연결 아님. 다중 건물은 임의 첫 행 선택하지 않음. 현재 대장: 과거의 용도·층수·면적 및 생존 건물 선택편향 미검증. 사용승인일도 동일 건물인지 확인 후 기준일 이전 조건으로만 검토. 건물 연면적을 점포면적으로 대체하지 않음. 현재는 연결성 점검이며 모델 입력 채택·학습·DB 적재 없음.

출처: https://www.data.go.kr/data/15134735/openapi.do

주소코드·지번·행수90건 검증 통과.
{"addresses_match": true, "date_consistent_cohorts": [{"year": 2013, "n": 38, "events": 2}, {"year": 2015, "n": 38, "events": 4}, {"year": 2017, "n": 35, "events": 2}, {"year": 2018, "n": 39, "events": 2}, {"year": 2020, "n": 42, "events": 4}], "connected_permits": 142, "approval_after_license": 12}
표본·사건 수 부족으로 건물 효과 학습은 보류. 현재 대장 조회 누락과 과거 동일 건물 확인이 필요.
