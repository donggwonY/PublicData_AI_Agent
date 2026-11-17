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

    def test_dashboard_sub_categories_and_scope(self):
        from ui_forecast import scoped_stores, sub_category_choices, sub_label
        food = sub_category_choices(self.s.stores, "일반음식점")
        self.assertEqual(food[0], "한식")
        self.assertIn("호프/통닭", food)
        self.assertNotIn("통닭(치킨)", food)
        self.assertNotIn("기타", food)
        cafe = sub_category_choices(self.s.stores, "휴게음식점")
        self.assertIn("커피숍", cafe)
        self.assertNotIn("까페", cafe)
        scope = scoped_stores(self.s.stores, "커피숍")
        m = scope["service"].eq(sub_label("커피숍"))
        # 인허가 종류와 관계없이 커피숍(옛 이름 까페 포함)을 모두 묶고, 다른 기록은 그대로 둔다
        self.assertEqual(int(m.sum()), int(self.s.stores["category"].isin(["커피숍", "까페"]).sum()))
        self.assertEqual(len(scope), len(self.s.stores))
        self.assertTrue(scope.loc[~m, "service"].equals(self.s.stores.loc[~m, "service"].astype(object)))
        self.assertEqual(sub_category_choices(self.s.stores.drop(columns=["category"]), "일반음식점"), [])

    def test_forecast_area_shows_all_gu_table_for_selected_gu(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string(
            "from ui_forecast import render_flow_with_forecast\n"
            "render_flow_with_forecast('커피숍', '수성구')\n", default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertTrue(any(e.label.startswith("구·군별 예측") for e in app.expander))
        table = app.dataframe[0].value
        self.assertEqual(len(table), 9)
        self.assertIn("수성구 (선택)", set(table["구·군"]))

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
