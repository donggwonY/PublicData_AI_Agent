"""Tool 8종 스모크 테스트 (API 키 불필요).  실행: python -m tests.smoke_test"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tools import TOOL_FUNCTIONS, ToolError  # noqa: E402

CASES = [
    ("get_survival_curve", {"category": "카페"}),                       # "카페 열려는데 어때?"
    ("get_survival_curve", {"group_by": "category", "min_n": 300}),     # "뭐가 더 오래 가?"
    ("get_survival_curve", {"category": "커피숍", "gu": "수성구"}),
    ("compare_areas", {"areas": ["수성구", "중구", "달서구"], "category": "카페"}),  # "어느 구가 나아?"
    ("normalize_address", {"query": "군위군 중앙길 90"}),
    ("get_unit_history", {"address": "대구광역시 군위군 의흥면 읍내1길 14"}),       # "이 자리 이전엔 뭐였어?"
    ("find_vacant_units", {"gu": "중구", "limit": 3}),                  # "빈자리 있어?"
    ("get_market_cycle", {"gu": "수성구", "dong": "범어동"}),            # "이 동네 분위기는?"
    ("get_market_cycle", {}),
    ("get_market_cycle", {"dong": "삼덕동"}),
    ("find_risk_spots", {"gu": "달서구", "limit": 3}),
    ("transition_matrix", {"from_category": "한식", "gu": "중구"}),
    ("transition_matrix", {"to_category": "카페"}),
    ("get_survival_curve", {"gu": "없는구"}),                           # 오류 경로
    # 보조 데이터 Tool
    ("get_area_profile", {"gu": "중구", "dong": "삼덕동"}),              # "이 동네 어떤 곳이야?"
    ("get_area_profile", {"dong": "대신동"}),
    ("find_nearby", {"address": "대구 중구 동성로5길 83", "radius_m": 300, "category": "카페"}),
    ("get_station_traffic", {"station": "반월당"}),
    ("get_station_traffic", {}),
    ("find_nearby", {"address": "없는주소 999"}),                       # 오류 경로
]


def main():
    failed = 0
    for name, args in CASES:
        t = time.perf_counter()
        try:
            out = TOOL_FUNCTIONS[name](**args)
            text = json.dumps(out, ensure_ascii=False)
            status = "OK "
        except ToolError as e:
            text, status = f"ToolError: {e}", "ERR"
        except Exception as e:  # 예상치 못한 예외 = 실패
            text, status, failed = f"{type(e).__name__}: {e}", "FAIL", failed + 1
        ms = (time.perf_counter() - t) * 1000
        print(f"[{status}] {name}({args}) {ms:.0f}ms\n      {text[:700]}\n")
    print("FAILED" if failed else "ALL PASSED", failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
