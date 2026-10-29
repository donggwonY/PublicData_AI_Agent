"""Regression checks against bundled snapshot; no DB or model calls."""
import os
os.environ["APP_DATA_SOURCE"] = "parquet"
import unittest
from core.tools import AmbiguousAddressError, find_nearby, get_unit_history, normalize_address, ToolError

class A03RegressionTest(unittest.TestCase):
    def test_building_number_is_not_prefix(self):
        r = normalize_address("동부로22길 9")
        self.assertGreater(r["matched"], 0)
        self.assertTrue(all("동부로22길 9" in x["address"] and "91-11" not in x["address"] for x in r["matches"]))
        short = find_nearby("동부로22길 9", category="카페")
        full = find_nearby("대구 동구 동부로22길 9", category="카페")
        self.assertEqual(short["center"], full["center"])
        c = short["same_category"]
        self.assertEqual((c["count"], c["exact_deduplicated_count"], c["same_address_deduplicated_count"], c["excluding_same_address_deduplicated_count"]), (39, 38, 1, 37))

    def test_excluding_center_preserves_other_building_records(self):
        # 같은 외부 건물의 서로 다른 카페 2건은 건물 하나로 합치지 않는다.
        from unittest.mock import patch
        import pandas as pd
        from core.tools import store
        s = store()
        center = find_nearby("대구 동구 동부로22길 9", category="카페")["center"]
        row = s.poi.iloc[0].copy()
        row["lat"], row["lon"] = center["lat"], center["lon"]
        row["cat_s"] = "카페"
        row["addr"], row["name"] = "대구광역시 동구 동부로22길 9", "중심카페"
        outside = row.copy()
        outside["addr"], outside["name"] = "대구광역시 동구 동부로22길 11", "외부카페A"
        outside2 = outside.copy()
        outside2["name"] = "외부카페B"
        fixture = pd.DataFrame([row, row.copy(), outside, outside2]).reset_index(drop=True)
        with patch.object(s, "poi", fixture):
            c = find_nearby("대구 동구 동부로22길 9", category="카페")["same_category"]
        self.assertEqual((c["count"], c["exact_deduplicated_count"],
                          c["same_address_deduplicated_count"],
                          c["excluding_same_address_deduplicated_count"]), (4, 3, 1, 2))
        self.assertIn("3 - 1 = 2건", c["count_explanation"])
        self.assertIsNone(c["unique_building_count"])

    def test_station_scope_is_not_silently_substituted(self):
        for a in ["동대구역", "동대구역 2번 출구"]:
            with self.assertRaises(ToolError):
                find_nearby(a, category="카페")

    def test_ambiguous_address_requires_clarification(self):
        # 같은 도로명·번호가 여러 구에 있으면 고르게 하고, 후보를 함께 돌려준다.
        with self.assertRaises(AmbiguousAddressError) as ctx:
            find_nearby("상화로 79", category="카페")
        self.assertEqual({c["gu"] for c in ctx.exception.candidates}, {"달서구", "수성구"})
        # 고른 후보의 자리 ID 로 다시 조회하면 그 자리가 중심이 된다.
        pick = ctx.exception.candidates[0]
        self.assertEqual(find_nearby(pick["unit_id"], category="카페")["center"]["unit_id"], pick["unit_id"])
        # 동부로 149: 다른 건물(동대구로 지하 530)이 과거 기록 하나로 섞여 나오지만, 도로명·번호가 정확히 같은
        # 후보만 남기면 한 건물이다. 층을 지정하지 않으면 이력이 가장 많은 층을 보여 주고 나머지 층은 후보로 준다.
        self.assertEqual(find_nearby("대구 동구 동부로 149", category="카페")["center"]["address"], "대구광역시 동구 동부로 149 지하1층")
        r = find_nearby("대구 동구 동부로 149 지하1층", category="카페")
        c = r["same_category"]
        self.assertEqual((c["exact_deduplicated_count"], c["same_address_deduplicated_count"], c["excluding_same_address_deduplicated_count"]), (43, 11, 32))
        self.assertEqual(c["definition"], "cat_s == 카페")

    def test_exact_full_address_is_not_ambiguous(self):
        # '대구 중구 동성로5길 83'은 도로명 검색에 다른 건물(동성로4길 58)이 섞여 나오지만 정확히 일치하는 건물이 있다.
        for a in ["대구 중구 동성로5길 83", "동성로5길 83", "삼덕동1가 61-3"]:
            self.assertEqual(get_unit_history(a)["unit"]["address"], "대구광역시 중구 동성로5길 83 1층")
        self.assertEqual(get_unit_history("대구 중구 동성로5길 83 2층")["unit"]["address"], "대구광역시 중구 동성로5길 83 2층")

    def test_floor_note_when_floor_not_given(self):
        # 층을 쓰지 않으면 기록이 가장 많은 층을 고르고, 그 사실을 알린다(A안).
        h = get_unit_history("대구 중구 동성로5길 83")
        self.assertIn("1층(6건)", h["floor_note"])
        self.assertIsNone(get_unit_history("대구 중구 동성로5길 83 2층")["floor_note"])
        self.assertIsNone(get_unit_history("대구 중구 동성로5길 83", whole_building=True)["floor_note"])
        self.assertIn("지하1층", find_nearby("대구 동구 동부로 149", category="카페")["floor_note"])

if __name__ == "__main__":
    unittest.main()
