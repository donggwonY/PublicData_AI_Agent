"""E-06 구×업종 앞으로 1년 폐업 예측 도구: 저장값 읽기·업태 합치기·안전장치·표시 문구."""
import os
import re
import unittest

os.environ.setdefault("APP_DATA_SOURCE", "parquet")

from core import tools as T  # noqa: E402


class CompetitionOutlookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = T.store()
        if cls.s.competition is None:
            raise unittest.SkipTest("competition_forecast.parquet 없음")
        cls.cf = cls.s.competition

    def test_reads_stored_value_and_range(self):
        out = T.get_competition_outlook("한식", gu="수성구")
        self.assertTrue(out["available"])
        it = out["items"][0]
        r = self.cf[(self.cf.gu == "수성구") & (self.cf.category == "한식")].iloc[0]
        self.assertAlmostEqual(it["closes_pred"], round(float(r.closes_pred), 1))
        self.assertEqual(it["closes_range"], [int(r.closes_lo), int(r.closes_hi)])
        self.assertLessEqual(it["closes_range"][0], it["closes_pred"])
        self.assertGreaterEqual(it["closes_range"][1], it["closes_pred"])
        self.assertEqual(out["range_note"], T.FORECAST_RANGE_NOTE)

    def test_cafe_alias_merges_renamed_category(self):
        out = T.get_competition_outlook("카페", gu="수성구")
        cats = [i["category"] for i in out["items"]]
        self.assertIn("커피숍", cats)
        self.assertNotIn("까페", cats)
        self.assertEqual(len(cats), len(set(cats)))

    def test_daegu_wide_lists_gus_sorted(self):
        out = T.get_competition_outlook("커피숍")
        preds = [i["closes_pred"] for i in out["items"]]
        self.assertEqual(preds, sorted(preds, reverse=True))
        self.assertEqual(len({i["gu"] for i in out["items"]}), len(out["items"]))
        self.assertTrue(any("합계" in n for n in out["notes"]))

    def test_dong_falls_back_to_gu(self):
        out = T.get_competition_outlook("한식", dong="범어동")
        self.assertEqual(out["area"], "수성구")
        self.assertTrue(any("동 단위 예측은 없어" in n for n in out["notes"]))

    def test_display_uses_period_and_no_decimals_or_80pct(self):
        d = T.get_competition_outlook("한식", gu="수성구")["items"][0]["display"]
        self.assertIn("앞으로 1년(2026.11.07~2027.11.06)", d["forecast"])
        self.assertIsNone(re.search(r"\d+\.\d+곳", d["forecast"]))
        self.assertNotIn("80%", d["forecast"] + T.FORECAST_RANGE_NOTE)

    def test_stale_or_missing_table_returns_unavailable(self):
        s, orig = self.s, self.s.competition
        try:
            stale = orig.copy(); stale["reference_date"] = "2000-01-01"
            s.competition = stale
            self.assertFalse(T.get_competition_outlook("한식", gu="수성구")["available"])
            s.competition = None
            self.assertFalse(T.get_competition_outlook("한식")["available"])
        finally:
            s.competition = orig
        self.assertTrue(T.get_competition_outlook("한식", gu="수성구")["available"])


if __name__ == "__main__":
    unittest.main()
