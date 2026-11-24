"""Claude API 용 Tool 정의 (JSON Schema). MCP 서버는 tools.py 함수 시그니처에서 직접 생성한다."""
import config as C

_AREA = {
    "gu": {"type": "string", "description": "대구 구·군 (중구, 동구, 서구, 남구, 북구, 수성구, 달서구, 달성군, 군위군). 생략 시 대구 전체."},
    "dong": {"type": "string", "description": "법정동 또는 읍·면 (예: 범어동, 삼덕동1가, 다사읍). '삼덕동'처럼 쓰면 삼덕동1가~3가를 합산."},
}
_CATEGORY_DESC = ("업태 또는 별칭. 예: 카페, 커피숍, 치킨, 한식, 중국식, 분식, 호프/통닭, 미용실, 이발소, 네일샵, 안경점, 약국, "
                  "편의점, 정육점, 반찬가게, 목욕탕, 동물병원, 애견미용, 피시방, 오락실, 노래방, 헬스장, 단란주점. "
                  "업종 전체를 가리킬 수도 있다(예: '일반음식점', '이용업', '동물병원' — 서비스는 점포형 인허가 42개 업종이며 "
                  "목록은 결과의 basis.data 에 있다). 옷가게·휴대폰 매장·학원·부동산 같은 인허가 대상이 아닌 업종은 데이터에 없다.")

TOOL_SPECS = [
    {
        "name": "get_survival_curve",
        "description": (
            "Kaplan-Meier 점포 생존분석(영업 중 점포는 중도절단). 업태·지역별 중앙생존기간, 1/3/5년 생존율, 연차별 생존곡선과 "
            "대구 전체 기준선을 반환한다. group_by 를 주면 업태·구·동별 순위표를 반환한다('뭐가 더 오래 가?', '어느 동이 오래 버텨?'). "
            "기본 코호트는 2010년 이후 개업(그 이전은 생존편향). 답변에 basis의 기준일·코호트와 영업 중 기록의 중도절단을 표시한다. 단순 평균이나 개별 신규 점포의 생존 확률 보장이 아니다."
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
            "인허가 공백 후보(실제 공실 여부 미확인; 폐업 후 90일~3년간 같은 자리에 분석 대상 업종의 신규 인허가 없음) 목록을 좌표·공실일수·직전 점포 정보와 함께 반환. "
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
            "존속기간 요약과 지역 참고 통계, 다점포 기록 여부. '이 자리 이전엔 뭐였어?'에 사용. "
            "폐업 기록의 평균과 전체 코호트의 KM 중앙생존기간은 직접 비교해 우열을 판단하지 않는다. "
            "동시 영업 표시는 기록의 중첩이며 실제 독립 공간이나 구조를 증명하지 않는다. "
            "인허가 공백 후보 자리(공백 90일~3년, 단일 점포)면 vacancy_outlook 에 앞으로 1년 재입점 점수(저장된 예측값)와 "
            "답변에 그대로 쓸 display 문장이 들어 있다. '이 자리에 다시 가게가 들어올까?'에도 사용. "
            "같은 후보 자리면 next_tenant_outlook 에 '다음 가게가 들어온다면' 업종 묶음 확률(저장된 예측값, 상위 3개)과 "
            "직전 업종 기준 보통 비율, display 문장이 들어 있다. '이 빈 자리엔 보통 어떤 가게가 들어와?'에도 사용."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "도로명·지번 주소, 상호명, 또는 후보 목록의 자리 ID (예: '동성로5길 83', '삼덕동1가 28-6 2층', '빽다방 대구군위점'). 사용자가 명시한 구·건물번호·층을 생략하지 않는다. 건물이 여러 곳이면 후보 목록이 오류로 반환되니 사용자에게 고르게 한다."},
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
            "여러 구·동을 한 번에 비교: 업태별 생존율(중앙생존·1/3/5년), 최근 3년 인허가 공백 후보율(실제 공실률 아님), 사이클 단계, 영업 중 동종 점포 수(경쟁), "
            "반복 폐업 자리 수, 주력 업태. '어느 구가 나아?'에 사용. 주거지·학원가·고객층·유동인구 구성은 이 도구로 확인되지 않으며 표본/생존율 차이의 원인으로 추정하지 않는다. "
            "수치 차이만으로 근소함·중요성·통계적 유의성을 판정하거나 입지·밀도의 영향력 크기를 단정하지 않는다."
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
            "그리고 같은 동네의 인허가 기반 지표(생존율·인허가 공백 후보율·사이클). "
            "'이 동네 어떤 곳이야?', '주변에 사는 사람은?', '무슨 상권이야?' 같은 질문에 사용. "
            f"상가정보는 {C.POI_MONTH} 현재 영업 점포 단면이고, 시간 추세는 get_market_cycle 을 함께 보라."
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
            "역·출구 합집합/최근접 배정은 미지원. 정확한 점포 주소 필요. 카페는 cat_s 정확 일치. count_explanation의 원기록·동일행 제거·중심 건물 제외 수를 그대로 구분하며 고유 건물 수로 해석하지 않음. interpretation_limits의 수요·임대료 등 미측정 항목은 확인 필요. 특정 자리 반경(기본 300m) 안의 현황: 전 업종 점포 수와 업종 구성, 같은 업종 경쟁 점포 수와 사례, "
            "최근 공실 자리, 반복 폐업 자리, 주차장 규모, 1km 내 전통시장. "
            "'이 자리 주변 경쟁은?', '근처에 빈 가게 있어?' 같은 질문에 사용."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "중심이 될 주소, 상호, 또는 후보 목록의 자리 ID (예: '동성로5길 83'). 사용자가 명시한 구·건물번호·층을 생략하지 않는다. 건물이 여러 곳이면 후보 목록이 오류로 반환되니 사용자에게 고르게 한다."},
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
        "name": "get_competition_outlook",
        "description": (
            "구·군 × 업태의 앞으로 1년(기준일 다음 날부터 12개월) 폐업 신고 수 예측과 최근 3년 실제 개업·폐업 기록. "
            "'내년에 수성구 카페 몇 곳이나 문 닫을까?', '이 업종 경쟁이 줄어들까?', '어느 구에서 치킨집이 많이 닫을까?'처럼 "
            "앞으로의 경쟁 점포 변화를 물을 때 쓴다. 예측은 오프라인 포아송 회귀 모델의 저장값이며 구·군 단위뿐이다(동 단위 없음). "
            "개업 수는 예측하지 않는다. gu 를 생략하면 구·군별로 예상 폐업이 많은 순으로 반환한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": _CATEGORY_DESC},
                **_AREA,
                "top_n": {"type": "integer", "default": 10},
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_resident_outlook",
        "description": (
            "행정동 거주자(주민등록) 1년 뒤 추정과 최근 1년 연령대별 이사 인원. "
            "'성내1동 사는 사람 1년 뒤에 늘어?', '이 동네엔 어떤 연령대가 이사 와?', '배후 인구가 줄고 있어?'처럼 "
            "동네 거주 인구의 앞으로와 최근 이사 흐름을 물을 때 쓴다. 1년 뒤 인구는 오프라인 모델의 저장값(2026-10 → 2027-10)이고, "
            "이사 인원은 나이 드는 효과를 뺀 순이동(들어온 사람 − 나간 사람, 2025-10 → 2026-10)이다. "
            "'범어동'처럼 행정동 여러 곳에 걸친 이름은 각 행정동을 함께 반환한다. 업종·상권 정보는 get_area_profile 을 쓴다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dong": {"type": "string", "description": "행정동(성내1동, 범어3동, 다사읍) 또는 법정동(삼덕동1가). '범어동'처럼 쓰면 범어1~4동을 모두 반환."},
                "gu": {"type": "string", "description": "구·군. 같은 이름의 동이 여러 구에 있을 때 지정."},
            },
            "required": ["dong"],
        },
    },
    {
        "name": "find_similar_areas",
        "description": (
            "기준 동네와 업종·연령 구성이 비슷한 대구 행정동 5곳(비슷한 순서)과 각 동네의 상가 수·거주자 수·1년 뒤 거주자 추정 변화. "
            "'성내1동이랑 비슷한 동네 어디야?', '30대 비중이 비슷한 곳은?', '음식점 비중이 비슷한 동네는?'처럼 비교 후보를 찾을 때 쓴다. "
            "구성의 유사도 순서일 뿐 장사가 잘되는 곳을 고른 결과가 아니다. 상가 50곳 미만 동네는 비교하지 않는다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dong": {"type": "string", "description": "기준 행정동(성내1동, 범어3동). 행정동 여러 곳에 걸친 이름이면 하나를 고르라고 되묻는다."},
                "gu": {"type": "string", "description": "구·군. 같은 이름의 동이 여러 구에 있을 때 지정."},
                "criterion": {"type": "string", "description": "비교 기준. 생략하면 업종·연령 구성. 예: '상가·거주자 규모', '음식 업종 비중', '교육', '30대 비중', '0~9세'."},
            },
            "required": ["dong"],
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


TOOL_SPECS.append({
    "name": "get_franchise_outlook",
    "description": "대구 프랜차이즈 브랜드의 과거 가맹점 수와 2026년 말 감소 추정을 조회한다. 정확 이름·CU·BBQ·메가커피 별칭 지원. 후보가 여러 개면 선택을 묻는다. 기간·공식 수치 미확인·업종 과거 비교값을 함께 설명한다. 개별 가게 폐업확률이 아니며 확률순 추천·계약 판단을 하지 않는다. 2년 전망은 2024년 말 대비이며 2026년 한 해 변화로 말하지 않는다.",
    "input_schema": {"type":"object","properties":{"brand":{"type":"string","description":"브랜드 이름 또는 관리번호"}},"required":["brand"]}
})
