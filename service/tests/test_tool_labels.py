"""AI 상담 도구 기록의 사람이 읽는 이름(2026-11-15)."""
import unittest

from core.tool_specs import TOOL_SPECS as TOOLS
from ui_visuals import TOOL_LABELS, tool_label


class ToolLabelTests(unittest.TestCase):
    def test_every_tool_has_korean_label(self):
        names = {t["name"] for t in TOOLS}
        self.assertEqual(names - set(TOOL_LABELS), set())

    def test_label_shows_conditions_not_internals(self):
        self.assertEqual(tool_label("get_survival_curve", {"category": "휴게음식점", "gu": "수성구", "min_n": 100}),
                         "업종 생존 기간 조회 · 휴게음식점 · 수성구")
        self.assertEqual(tool_label("compare_areas", {"areas": ["수성구", "중구"]}), "지역 비교 · 수성구 vs 중구")
        self.assertEqual(tool_label("find_nearby", {"address": "동성로5길 83", "radius_m": 300}),
                         "주변 가게 찾기 · 동성로5길 83 · 반경 300m")
        self.assertEqual(tool_label("get_survival_curve", {"group_by": "gu", "since_year": 2015}),
                         "업종 생존 기간 조회 · 구·군별 · 2015년 이후 개업")
        self.assertEqual(tool_label("get_unit_history", {"address": "x", "whole_building": False}), "자리 이력 조회 · x")
        self.assertEqual(tool_label("unknown_tool", None), "unknown_tool")


if __name__ == "__main__":
    unittest.main()
