"""Claude API 용 Tool 정의 (JSON Schema). MCP 서버는 tools.py 함수 시그니처에서 직접 생성한다."""

_AREA = {
    "gu": {"type": "string", "description": "대구 구·군 (중구, 동구, 서구, 남구, 북구, 수성구, 달서구, 달성군, 군위군). 생략 시 대구 전체."},
    "dong": {"type": "string", "description": "법정동 또는 읍·면 (예: 범어동, 삼덕동1가, 다사읍). '삼덕동'처럼 쓰면 삼덕동1가~3가를 합산."},
}
_CATEGORY_DESC = ("업태 또는 별칭. 예: 카페, 커피숍, 치킨, 한식, 중국식, 식육(숯불구이), 분식, 일식, 호프/통닭, 기타 휴게음식점. "
                  "업종 전체를 가리킬 수도 있다(예: '일반음식점', '휴게음식점', '제과점영업' — 분석에 포함된 업종 목록은 결과의 basis.data 에 있다).")

TOOL_SPECS = [
    {
        "name": "get_survival_curve",
        "description": (
            "Kaplan-Meier 점포 생존분석(영업 중 점포는 중도절단). 업태·지역별 중앙생존기간, 1/3/5년 생존율, 연차별 생존곡선과 "
            "대구 전체 기준선을 반환한다. group_by 를 주면 업태·구·동별 순위표를 반환한다('뭐가 더 오래 가?', '어느 동이 오래 버텨?'). "
            "기본 코호트는 2010년 이후 개업(그 이전은 생존편향)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": _CATEGORY_DESC},
                **_AREA,
                "since_year": {"type": "integer", "description": "이 연도 이후 개업한 점포만 분석. 기본 2010.", "default": 2010},
                "group_by": {"type": "string", "enum": ["category", "gu", "dong", "service"], "description": "그룹별 순위표가 필요할 때."},
                "min_n": {"type": "integer", "description": "group_by 시 최소 표본 수. 기본 100.", "default": 100},
                "top_n": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_market_cycle",
        "description": (
            "상권 사이클 단계(성장기/회복기/성숙기/쇠퇴 진입기/쇠퇴기/판정 보류)를 최근 3년 vs 직전 3년 개업·폐업 비율로 판정하고 "
            "근거 수치, 연도별 개폐업 추이, 최근 3년 늘어난·줄어든 업태를 반환한다. 지역 미지정 시 대구 전체와 구별 단계."
        ),
        "input_schema": {"type": "object", "properties": {**_AREA, "years": {"type": "integer", "default": 10}}},
    },
    {
        "name": "find_vacant_units",
        "description": (
            "최근 공실 후보(폐업 후 90일~3년간 같은 자리에 분석 대상 업종의 신규 인허가 없음) 목록을 좌표·공실일수·직전 점포 정보와 함께 반환. "
            "기본은 단일 점포 자리만. previous_category 로 '직전에 카페였던 빈자리' 같은 필터 가능."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_AREA,
                "previous_category": {"type": "string", "description": "직전 점포 업태 필터. " + _CATEGORY_DESC},
                "min_days": {"type": "integer", "default": 90},
                "max_days": {"type": "integer", "default": 1095},
                "single_unit_only": {"type": "boolean", "default": True},
                "sort": {"type": "string", "enum": ["recent", "longest"], "default": "recent"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_unit_history",
        "description": (
            "특정 자리(주소 또는 상호)의 인허가 이력을 시간순으로 반환: 역대 상호·업태·영업기간·직전 폐업 후 공백일, "
            "업태별 평균 존속기간과 대구 평균 비교, 다점포 건물 여부. '이 자리 이전엔 뭐였어?'에 사용."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "도로명·지번 주소 또는 상호명 (예: '동성로5길 83', '삼덕동1가 28-6 2층', '빽다방 대구군위점')."},
                "whole_building": {"type": "boolean", "description": "층 구분 없이 건물 전체 이력.", "default": False},
                "max_records": {"type": "integer", "default": 40},
            },
            "required": ["address"],
        },
    },
    {
        "name": "find_risk_spots",
        "description": (
            "반복 폐업 지점: 2010년 이후 점포가 min_closures 회 이상 폐업한 단일 점포 자리(백화점·푸드코트 등 다점포 건물 제외)를 "
            "폐업 횟수·평균 존속기간·역대 상호와 함께 반환."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_AREA,
                "min_closures": {"type": "integer", "default": 3},
                "since_year": {"type": "integer", "default": 2010},
                "category": {"type": "string", "description": "이력에 이 업태가 있었던 자리만. " + _CATEGORY_DESC},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "compare_areas",
        "description": (
            "여러 구·동을 한 번에 비교: 업태별 생존율(중앙생존·1/3/5년), 최근 3년 공실률, 사이클 단계, 영업 중 동종 점포 수(경쟁), "
            "반복 폐업 자리 수, 주력 업태. '어느 구가 나아?'에 사용."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "areas": {"type": "array", "items": {"type": "string"},
                          "description": "비교 지역 목록. 예: ['수성구', '중구'] 또는 ['수성구 범어동', '중구 삼덕동']. 비우면 9개 구·군 전체."},
                "category": {"type": "string", "description": _CATEGORY_DESC},
                "since_year": {"type": "integer", "default": 2010},
            },
            "required": ["areas"],
        },
    },
    {
        "name": "transition_matrix",
        "description": (
            "업종 전이 분석: 같은 자리에서 A 업태가 폐업한 뒤 들어온 업태의 분포와 그 후속 점포의 생존율. "
            "from_category 만 주면 '한식 자리에 뭐가 들어오고 얼마나 버텼나', to_category 만 주면 '카페는 원래 뭐였던 자리에 들어왔나'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "from_category": {"type": "string", "description": _CATEGORY_DESC},
                "to_category": {"type": "string", "description": _CATEGORY_DESC},
                **_AREA,
                "top_n": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "get_area_profile",
        "description": (
            "동네(행정동) 프로필: 상권 유형(유흥/시장/대학·학원가/오피스/주거/관광·숙박/혼합)과 판정 근거, "
            "업종 구성비와 대구 평균 비교, 업종 다양성 지수, 주민등록 인구·연령 구성, 전통시장·주차장, "
            "그리고 같은 동네의 인허가 기반 지표(생존율·공실률·사이클). "
            "'이 동네 어떤 곳이야?', '주변에 사는 사람은?', '무슨 상권이야?' 같은 질문에 사용. "
            "상가정보는 2026-06 현재 영업 점포 단면이고, 시간 추세는 get_market_cycle 을 함께 보라."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gu": _AREA["gu"],
                "dong": {"type": "string", "description": "행정동(삼덕동, 범어3동, 다사읍) 또는 법정동(삼덕동1가). 법정동은 자동으로 행정동에 연결된다."},
                "top_n": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "find_nearby",
        "description": (
            "특정 자리 반경(기본 300m) 안의 현황: 전 업종 점포 수와 업종 구성, 같은 업종 경쟁 점포 수와 사례, "
            "최근 공실 자리, 반복 폐업 자리, 주차장 규모, 1km 내 전통시장. "
            "'이 자리 주변 경쟁은?', '근처에 빈 가게 있어?' 같은 질문에 사용."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "중심이 될 주소 또는 상호 (예: '동성로5길 83')."},
                "radius_m": {"type": "integer", "description": "반경(m). 기본 300.", "default": 300},
                "category": {"type": "string", "description": "경쟁으로 셀 업종. " + _CATEGORY_DESC},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["address"],
        },
    },
    {
        "name": "get_station_traffic",
        "description": (
            "대구 도시철도 역별 일평균 승하차 인원과 시간대 구성(아침·점심·저녁·심야 비중, 최대 시간대) — 유동인구 대리지표. "
            "역 이름을 주면 그 역의 수치와 순위, 생략하면 이용객 상위 역 순위를 반환한다. "
            "역 좌표가 없어 특정 주소와의 거리는 계산하지 못한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "station": {"type": "string", "description": "역 이름 (예: 반월당, 동대구역, 범어)."},
                "top_n": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "normalize_address",
        "description": (
            "주소·상호 문자열을 분석 단위인 '자리'(건물 지번 + 층) 후보로 정규화하고 각 후보의 현재 상태(영업중/공백일수)를 반환. "
            "주소가 모호하거나 여러 후보가 있을 때 먼저 호출."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}},
            "required": ["query"],
        },
    },
]
