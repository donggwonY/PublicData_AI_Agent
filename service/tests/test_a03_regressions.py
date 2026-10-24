"""Regression checks against bundled snapshot; no DB or model calls."""
import os
os.environ["APP_DATA_SOURCE"] = "parquet"
import unittest
from core.tools import find_nearby, normalize_address, ToolError

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

    def test_station_scope_is_not_silently_substituted(self):
        for a in ["동대구역", "동대구역 2번 출구"]:
            with self.assertRaises(ToolError):
                find_nearby(a, category="카페")

    def test_ambiguous_address_requires_clarification(self):
        with self.assertRaises(ToolError):
            find_nearby("대구 동구 동부로 149", category="카페")
        r = find_nearby("대구 동구 동부로 149 지하1층", category="카페")
        c = r["same_category"]
        self.assertEqual((c["exact_deduplicated_count"], c["same_address_deduplicated_count"], c["excluding_same_address_deduplicated_count"]), (43, 11, 32))
        self.assertEqual(c["definition"], "cat_s == 카페")

if __name__ == "__main__":
    unittest.main()
