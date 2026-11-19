"""E-09 다음 가게 업종 확률: 저장된 점수 읽기·상위 3개·비교 문턱·좌표 없음·안전장치·표시 문구·화면 블록."""
import os
import re
import unittest

os.environ.setdefault("APP_DATA_SOURCE", "parquet")

import config as C  # noqa: E402
from core import tools as T  # noqa: E402
from ui_vacancy import next_tenant_bars_html  # noqa: E402


class NextTenantOutlookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = T.store()
        if cls.s.next_tenant_scores is None:
            raise unittest.SkipTest("next_tenant_scores.parquet 없음")
        nt = cls.s.next_tenant_scores
        cls.uid = nt[~nt.no_coords].iloc[len(nt) // 2]["uid"]
        cls.uid_nc = nt[nt.no_coords].iloc[0]["uid"]

    def test_same_candidates_as_vacancy_scores(self):
        self.assertEqual(set(self.s.next_tenant_scores.index), set(self.s.vacancy_scores.index))
        p = self.s.next_tenant_scores[[f"p_{k}" for k, _ in C.NEXT_TENANT_GROUPS]].sum(axis=1)
        self.assertTrue(((p - 1).abs() < 1e-3).all())

    def test_reads_stored_values_and_top3(self):
        v = T.get_unit_history(self.uid)["next_tenant_outlook"]
        r = self.s.next_tenant_scores.loc[self.uid]
        self.assertIsNotNone(v)
        ps = sorted((float(r[f"p_{k}"]) for k, _ in C.NEXT_TENANT_GROUPS), reverse=True)
        self.assertEqual([round(x["p"], 6) for x in v["top3"]], [round(x, 6) for x in ps[:3]])
        self.assertAlmostEqual(v["rest_p"], sum(ps[3:]), places=6)
        self.assertEqual(v["vacant_days"], int(self.s.units.loc[self.uid, "vacant_days"]))

    def test_compare_threshold(self):
        v = T.get_unit_history(self.uid)["next_tenant_outlook"]
        lead = v["top3"][0]
        diff = lead["p"] - lead["typical"]
        expect = None if abs(diff) < C.NEXT_TENANT_COMPARE_PP else ("높은 편" if diff > 0 else "낮은 편")
        self.assertEqual(v["compare"], expect)
        self.assertEqual(v["display"]["compare"] is None, expect is None)

    def test_no_coords_uses_typical_only(self):
        v = T.get_unit_history(self.uid_nc)["next_tenant_outlook"]
        self.assertTrue(v["no_coords"])
        self.assertIsNone(v["compare"])
        r = self.s.next_tenant_scores.loc[self.uid_nc]
        best = max(C.NEXT_TENANT_GROUPS, key=lambda g: float(r[f"typical_{g[0]}"]))
        self.assertEqual(v["top3"][0]["group"], best[1])
        self.assertIn("위치 정보가 없어", v["display"]["if_next_store_opens"])
        self.assertNotIn("left:", next_tenant_bars_html(v))       # 비교선 없음

    def test_hidden_when_stale_mismatched_or_whole_building(self):
        self.assertIsNone(T.get_unit_history(self.uid, whole_building=True)["next_tenant_outlook"])
        active = self.s.units[~self.s.units["vacant"]].iloc[0]
        self.assertIsNone(T.next_tenant_outlook(active))
        s, orig = self.s, self.s.next_tenant_scores
        try:
            stale = orig.copy(); stale["data_reference_date"] = "2000-01-01"
            s.next_tenant_scores = stale
            self.assertIsNone(T.next_tenant_outlook(s.units.loc[self.uid]))
            off = orig.copy(); off.loc[self.uid, "vacant_days"] = int(off.loc[self.uid, "vacant_days"]) + 1
            s.next_tenant_scores = off
            self.assertIsNone(T.next_tenant_outlook(s.units.loc[self.uid]))
        finally:
            s.next_tenant_scores = orig
        self.assertIsNotNone(T.next_tenant_outlook(s.units.loc[self.uid]))

    def test_display_text_rules(self):
        v = T.get_unit_history(self.uid)["next_tenant_outlook"]
        d = v["display"]
        self.assertIn("들어온다면", d["if_next_store_opens"])
        for x in v["top3"]:
            self.assertIn(f"{x['group']} {T.pct_text(x['p'])}", d["if_next_store_opens"])
        text = " ".join(x for x in d.values() if x)
        self.assertIsNone(re.search(r"\d+\.\d+\s*%", text))       # 소수점 확률 없음
        self.assertNotIn("p_", text)
        self.assertIn(v["prev_group"], d["typical_after_same_previous"])

    def test_josa(self):
        self.assertEqual(T._josa("음식점", ("이", "가")), "음식점이")
        self.assertEqual(T._josa("카페·제과", ("이", "가")), "카페·제과가")
        self.assertEqual(T._josa("담배", ("이", "가")), "담배가")

    def test_block_renders(self):
        from streamlit.testing.v1 import AppTest

        def page(uid):
            from core import tools as T
            from ui_vacancy import render_next_tenant
            render_next_tenant(T.get_unit_history(uid)["next_tenant_outlook"])

        app = AppTest.from_function(page, args=(self.uid,)).run(timeout=60)
        self.assertFalse(app.exception)
        md = " ".join(m.value for m in app.markdown)
        self.assertIn("다음 가게가 들어온다면", md)
        v = T.get_unit_history(self.uid)["next_tenant_outlook"]
        self.assertIn(v["top3"][0]["group"], md)
        caps = " ".join(c.value for c in app.caption)
        self.assertIn("세로선은", caps)


if __name__ == "__main__":
    unittest.main()
