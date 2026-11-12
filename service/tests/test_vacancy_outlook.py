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

    def test_display_text(self):
        self.assertEqual(pct_text(0.0862), "약 9%")
        self.assertEqual(pct_text(0.004), "1% 미만")
        self.assertEqual(per100_text(0.0519), "100곳 중 약 5곳")
        self.assertEqual(level_dots(4), "●●●●○")


if __name__ == "__main__":
    unittest.main()
