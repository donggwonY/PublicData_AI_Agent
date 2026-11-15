"""E-03 공실 재입점 카드: 저장된 점수 읽기·단계·안전장치·표시 문구."""
import os
import unittest

os.environ.setdefault("APP_DATA_SOURCE", "parquet")

import config as C  # noqa: E402
from core import tools as T  # noqa: E402
from ui_vacancy import level_dots, pct_text, per100_text  # noqa: E402


class VacancyOutlookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = T.store()
        if cls.s.vacancy_scores is None:
            raise unittest.SkipTest("vacancy_scores.parquet 없음")
        vs = cls.s.vacancy_scores
        cls.uid = vs.sort_values("p_fill_1y").iloc[len(vs) // 2]["uid"]

    def test_level_boundaries(self):
        self.assertEqual([T.score_level(p) for p in (0.0, 0.0199, 0.02, 0.0349, 0.035, 0.0549, 0.055, 0.0799, 0.08, 0.3)],
                         [1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
        self.assertEqual(len(C.VACANCY_SCORE_LEVEL_OBS), 5)

    def test_scored_unit_reads_stored_value(self):
        h = T.get_unit_history(self.uid)
        v = h["vacancy_outlook"]
        r = self.s.vacancy_scores.loc[self.uid]
        self.assertIsNotNone(v)
        self.assertAlmostEqual(v["p_fill_1y"], float(r["p_fill_1y"]))
        self.assertEqual(v["level"], T.score_level(float(r["p_fill_1y"])))
        self.assertEqual(v["vacant_days"], int(self.s.units.loc[self.uid, "vacant_days"]))
        self.assertIn(v["compare_to_band"], {"높음", "비슷", "낮음"})
        self.assertEqual(v["reference_date"], str(self.s.ref.date()))

    def test_whole_building_and_unscored_units_have_no_card(self):
        self.assertIsNone(T.get_unit_history(self.uid, whole_building=True)["vacancy_outlook"])
        active = self.s.units[~self.s.units["vacant"]].iloc[0]
        self.assertIsNone(T.vacancy_outlook(active))

    def test_stale_or_mismatched_scores_are_hidden(self):
        s, orig = self.s, self.s.vacancy_scores
        try:
            stale = orig.copy(); stale["data_reference_date"] = "2000-01-01"
            s.vacancy_scores = stale
            self.assertIsNone(T.vacancy_outlook(s.units.loc[self.uid]))
            off = orig.copy(); off.loc[self.uid, "vacant_days"] = int(off.loc[self.uid, "vacant_days"]) + 1
            s.vacancy_scores = off
            self.assertIsNone(T.vacancy_outlook(s.units.loc[self.uid]))
        finally:
            s.vacancy_scores = orig
        self.assertIsNotNone(T.vacancy_outlook(s.units.loc[self.uid]))

    def test_ai_display_matches_card_and_has_no_decimals(self):
        import re
        v = T.get_unit_history(self.uid)["vacancy_outlook"]
        d = v["display"]
        self.assertTrue(d["probability_1y"].startswith(pct_text(v["p_fill_1y"])))
        self.assertIn(f"5단계 중 {v['level']}단계", d["level"])
        self.assertIn(pct_text(v["band_avg_p_fill_1y"]), d["compare_to_same_vacancy_period"])
        text = " ".join(x for x in d.values() if x)
        self.assertIsNone(re.search(r"\d+\.\d+\s*%", text))       # 소수점 확률 없음
        self.assertNotIn("p_fill", text)
        self.assertEqual(d["thin_evidence_note"] is not None, v["thin_evidence"])

    def test_level_name_on_card_and_ai_text(self):
        v = T.get_unit_history(self.uid)["vacancy_outlook"]
        self.assertEqual(v["level_name"], C.VACANCY_SCORE_LEVEL_NAMES[v["level"] - 1])
        self.assertIn(f"({v['level_name']})", v["display"]["level"])

    def test_unit_summary_by_state(self):
        from ui_vacancy import unit_summary
        h = T.get_unit_history(self.uid)
        s = unit_summary(h)
        self.assertTrue(s["title"].startswith("인허가 공백") and s["no_score_reason"] is None)
        self.assertTrue(s["detail"].startswith("마지막 가게:"))
        self.assertIn("건물 전체", unit_summary(T.get_unit_history(self.uid, whole_building=True), True)["title"])
        active_uid = self.s.units[~self.s.units["vacant"] & self.s.units["is_single_unit"]].iloc[0]["uid"]
        self.assertTrue(unit_summary(T.get_unit_history(active_uid))["title"].startswith("현재 영업 중"))
        # 물결표는 마크다운 취소선이 되므로 요약 문장에 쓰지 않는다(여러 가게가 나열되는 자리에서 발생)
        multi = unit_summary(T.get_unit_history("대구 중구 동성로5길 83 1층"))
        self.assertNotIn("~", multi["detail"] + multi["title"])

    def test_korean_table_columns(self):
        from ui_vacancy import BY_CATEGORY_COLS, TIMELINE_COLS, korean_table
        h = T.get_unit_history(self.uid)
        t = korean_table(h["timeline"], TIMELINE_COLS)
        self.assertEqual(list(t.columns), [n for k, n in TIMELINE_COLS.items() if k in h["timeline"][0]])
        self.assertFalse(any(c.isascii() for c in t.columns))
        self.assertTrue(t["개업일"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all())
        self.assertNotIn("None", t.astype(str).to_string())
        self.assertEqual(list(korean_table(h["by_category"], BY_CATEGORY_COLS).columns)[0], "업태")

    def test_tenure_vs_daegu(self):
        sv = self.s.survival
        r = sv[sv["level"] == "업태"].iloc[0]
        curve = __import__("json").loads(r["curve_json"])
        t0 = T.tenure_vs_daegu(r["service"], r["category"], 0.0)
        self.assertTrue(t0["basis"].startswith(f"대구 {r['category']}"))
        self.assertAlmostEqual(t0["pct_lasted_this_long"], curve[0]["survival_pct"], places=1)
        t_mid = T.tenure_vs_daegu(r["service"], r["category"], 1.5)   # 1·2년 사이 보간
        lo, hi = sorted((curve[1]["survival_pct"], curve[2]["survival_pct"]))
        self.assertTrue(lo - 0.1 <= t_mid["pct_lasted_this_long"] <= hi + 0.1)
        far = T.tenure_vs_daegu(r["service"], r["category"], curve[-1]["year"] + 3)
        self.assertIsNone(far["pct_lasted_this_long"])
        self.assertEqual(far["beyond_curve_years"], curve[-1]["year"])
        self.assertIsNone(T.tenure_vs_daegu(r["service"], r["category"], None)["pct_lasted_this_long"])
        self.assertIsNone(T.tenure_vs_daegu("없는업종", "없는업태", 1.0))

    def test_tenure_sentences(self):
        from ui_vacancy import _tenure_label, tenure_sentences
        h = T.get_unit_history("대구 중구 동성로5길 83 1층")
        lines = tenure_sentences(h)
        self.assertTrue(lines)
        opens = sorted((r for r in h["timeline"] if r.get("years") is not None),
                       key=lambda r: str(r["open"]), reverse=True)
        self.assertTrue(lines[0].startswith(f"**{opens[0]['name']}**"))      # 최근 개업 순
        for ln in lines:
            self.assertRegex(ln, r"· \*\*(짧은 편|중간|긴 편)\*\*")
            self.assertNotIn("~", ln)
            self.assertIsNone(__import__("re").search(r"\d+\.\d+\s*%", ln))
        self.assertTrue(any("(진행 중)" in ln for ln in lines))
        self.assertEqual([_tenure_label(p, None) for p in (80, 75, 50, 25, 10)],
                         ["짧은 편", "짧은 편", "중간", "중간", "긴 편"])
        self.assertEqual(_tenure_label(None, 10), "긴 편")

    def test_display_text(self):
        self.assertEqual(pct_text(0.0862), "약 9%")
        self.assertEqual(pct_text(0.004), "1% 미만")
        self.assertEqual(per100_text(0.0519), "100곳 중 약 5곳")
        self.assertEqual(level_dots(4), "●●●●○")


if __name__ == "__main__":
    unittest.main()
