"""D-06 프랜차이즈 가맹점 조회의 AI 상담 연결 (2026-11-24). 저장소 docs/d06 자료를 읽는 읽기 전용 도구."""
import json
import unittest
from pathlib import Path

from core import tools as T
from core.tool_specs import TOOL_SPECS

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "docs/d06/delivery/revised/brand_registry.json"
SCOPE = ROOT / "docs/d06/delivery/revised/industry_scope.json"


@unittest.skipUnless(REG.exists(), "D-06 전달 자료 없음")
class FranchiseOutlookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = json.loads(REG.read_text(encoding="utf-8-sig"))

    def test_registered_as_consult_tool(self):
        self.assertIn("get_franchise_outlook", T.TOOL_FUNCTIONS)
        self.assertIn("get_franchise_outlook", [s["name"] for s in TOOL_SPECS])

    def test_mcp_tool_registered_before_run(self):
        src = (ROOT / "service/mcp_server.py").read_text(encoding="utf-8")
        self.assertLess(src.index("def get_franchise_outlook"), src.index('if __name__ == "__main__":'))

    def test_taxi_brands_excluded(self):
        ids = {r["brand"] for r in self.reg}
        excluded = set(json.loads(SCOPE.read_text(encoding="utf-8"))["excluded_brand_ids"])
        self.assertFalse(ids & excluded)
        self.assertEqual(T.get_franchise_outlook("세큐T")["status"], "not_found")
        names = " ".join(r.get("brand_name") or "" for r in self.reg)
        self.assertNotIn("택시", names)

    def test_search_aliases_and_short_queries(self):
        for q, name in [("CU", "씨유(CU)"), ("BBQ", "비비큐(BBQ)"), ("bhc", "비에이치씨(BHC)"),
                        ("메가커피", "메가엠지씨커피(MEGA MGC COFFEE)"), ("GS25", "GS25"), ("교촌치킨", "교촌치킨")]:
            r = T.get_franchise_outlook(q)
            self.assertEqual((r["status"], r.get("brand_name")), ("ok", name), q)
        gs = T.get_franchise_outlook("GS")                     # 2글자는 한 브랜드로 바로 정하지 않는다
        self.assertEqual(gs["status"], "choose_brand")
        self.assertIn("GS25", [c["brand_name"] for c in gs["candidates"]])
        self.assertEqual(T.get_franchise_outlook("")["status"], "needs_brand")

    def test_one_year_period_text(self):
        r = T.get_franchise_outlook("교촌치킨")
        f = r["forecast"]
        self.assertEqual((f["horizon_years"], f["baseline_accounting_year"], f["target_accounting_year"]), (1, 2025, 2026))
        self.assertIn("2025년 말 대비 2026년 말", f["period_text"])
        self.assertIn("공식 수치", r["message"])
        self.assertTrue(0 <= f["decline_probability"] <= 1)
        self.assertIn("2026년 실측", f["industry_reference"]["meaning"])

    def test_two_year_not_called_one_year_change(self):
        r = next(T.get_franchise_outlook(x["brand"]) for x in self.reg if x["status"] == "two_year_projection")
        f = r["forecast"]
        self.assertEqual((f["horizon_years"], f["baseline_accounting_year"]), (2, 2024))
        self.assertIn("2024년 말 대비 2026년 말", r["message"])
        self.assertIn("2년", r["message"])

    def test_no_forecast_states_have_no_probability(self):
        for st in ("latest_count_unavailable", "below_three_stores", "prior_year_unavailable"):
            rec = next(x for x in self.reg if x["status"] == st)
            r = T.get_franchise_outlook(rec["brand"])
            self.assertEqual(r["data_status"], st)
            self.assertIsNone(r["forecast"])
            self.assertNotIn("%", r["message"])

    def test_registry_consistency(self):
        self.assertEqual(len({r["brand"] for r in self.reg}), len(self.reg))
        for r in self.reg:
            has = r["status"] in ("current_projection", "two_year_projection")
            self.assertEqual(r.get("decline_probability") is not None, has, r["brand"])

    def test_consult_rules_in_system_prompt(self):
        from agent import build_system_prompt
        p = build_system_prompt()
        self.assertIn("get_franchise_outlook", p)
        self.assertIn("industry_reference", p)


if __name__ == "__main__":
    unittest.main()
