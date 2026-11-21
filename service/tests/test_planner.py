"""내 후보지 저장·비교, 주변 같은 업종, 손익분기 계산기 (2026-11-21 추가)."""
import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("APP_DATA_SOURCE", "parquet")

from streamlit.testing.v1 import AppTest  # noqa: E402

import config as C  # noqa: E402
import ui_planner as P  # noqa: E402
from core import breakeven as B  # noqa: E402
from core import nearby as N  # noqa: E402
from core import tools as T  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")
ADDR = "대구 중구 삼덕동1가 28-6"


def base(**kw):
    v = dict(ticket=7000, cost_rate_pct=35, fee_rate_pct=3, rent=1_500_000, labor=0, other_fixed=300_000, days=26)
    return B.Inputs(**(v | kw))


class BreakevenTest(unittest.TestCase):
    def test_breakeven_rounds_up(self):
        r = B.calculate(base())
        self.assertEqual(r["margin_per_order"], 4340)              # 7,000 × (1 − 0.38)
        self.assertEqual(r["breakeven"]["monthly_orders"], 415)    # ceil(1,800,000 / 4,340)
        self.assertEqual(r["breakeven"]["daily_orders"], 16)       # ceil(415 / 26)
        self.assertIsNone(r["target"])
        self.assertIsNone(r["scenarios"])

    def test_target_and_scenarios(self):
        r = B.calculate(base(owner_pay=2_500_000, expected_daily=80, investment=30_000_000))
        self.assertEqual(r["target"]["monthly_orders"], 991)       # ceil(4,300,000 / 4,340)
        names = [x["name"] for x in r["scenarios"]]
        self.assertEqual(names, ["보수", "기준", "낙관"])
        mid = r["scenarios"][1]
        self.assertEqual(mid["monthly_profit"], round(7000 * 80 * 26 * 0.62 - 1_800_000))
        self.assertEqual(mid["payback_months"], 7)                 # ceil(30,000,000 / 4,727,200)

    def test_no_payback_when_losing(self):
        r = B.calculate(base(expected_daily=5, investment=10_000_000))
        self.assertTrue(all(x["payback_months"] is None for x in r["scenarios"]))
        self.assertLess(r["scenarios"][1]["monthly_profit"], 0)

    def test_zero_fixed_cost(self):
        r = B.calculate(base(rent=0, other_fixed=0))
        self.assertEqual(r["breakeven"]["daily_orders"], 0)

    def test_invalid_inputs(self):
        for kw in [dict(ticket=0), dict(cost_rate_pct=70, fee_rate_pct=30), dict(days=0), dict(rent=-1),
                   dict(expected_daily=-3)]:
            with self.subTest(kw=kw), self.assertRaises(B.BreakevenError):
                B.calculate(base(**kw))


class SavedStoreTest(unittest.TestCase):
    def test_parse_keeps_known_and_reports_missing(self):
        uid = T.store().units["uid"].iloc[0]
        raw = json.dumps({"version": 1, "units": [{"unit_id": uid, "label": "가", "whole": False},
                                                  {"unit_id": uid, "label": "가 중복", "whole": False},
                                                  {"unit_id": "없는 자리", "label": "나"}]})
        ok, missing = P.parse_stored(raw)
        self.assertEqual([r["unit_id"] for r in ok], [uid])
        self.assertEqual(missing, ["나"])

    def test_parse_empty_and_broken(self):
        self.assertEqual(P.parse_stored(None), ([], []))
        self.assertEqual(P.parse_stored(""), ([], []))
        for raw in ["not json", '{"a": 1}', "[1, 2]"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                P.parse_stored(raw)


class NearbyTest(unittest.TestCase):
    def test_poi_month_from_file_name(self):
        self.assertRegex(C.POI_MONTH, r"^\d{4}-\d{2}$")
        self.assertIn(C.POI_MONTH.replace("-", ""), C.EXTERNAL_FILES["poi"])

    def test_poi_map_rules(self):
        pm = N.poi_category_map()
        use = pm[pm["usable"]]
        self.assertGreaterEqual(len(use), 30)                       # 손으로 맞춘 17개보다 넓다
        self.assertTrue((use["share"] >= N.POI_MAP_MIN_SHARE).all())
        self.assertTrue((use["linked"] >= N.POI_MAP_MIN_LINKED).all())
        mid = use[use["level"] == "cat_m"]
        self.assertFalse(mid["poi_class"].duplicated().any())        # 중분류는 가장 큰 업태 하나에만
        m = pm.set_index("category")
        self.assertEqual(m.loc["약국", "poi_class"], "약국")
        self.assertTrue(m.loc["한식", "usable"])
        self.assertFalse(m.loc["식육(숯불구이)", "usable"] and m.loc["식육(숯불구이)", "level"] == "cat_m")

    def test_choices_cover_all_active_categories(self):
        ch = N.category_choices()
        self.assertEqual(ch[0], "카페")
        act = set(N.active_stores()["category"])
        self.assertTrue(act <= set(ch) | {"카페"})
        self.assertEqual(N.category_label("한식"), "한식 (일반음식점)")

    def test_nearby_counts(self):
        uid = T.normalize_address(ADDR)["matches"][0]["unit_id"]
        n = N.nearby_same_category(uid, "카페")
        self.assertGreater(n["permit"]["count"], 0)
        self.assertIn("카페", n["poi"]["poi_class"])
        self.assertIn(C.POI_MONTH, n["poi"]["basis"])
        d = [e["dist_m"] for e in n["permit"]["examples"]]
        self.assertEqual(d, sorted(d))
        self.assertTrue(all(x <= C.NEARBY_RADIUS_M for x in d))
        # 상가정보 대응이 없는 업태는 인허가 기준만
        n2 = N.nearby_same_category(uid, "기타")
        self.assertIsNone(n2["poi"])
        self.assertTrue(n2["poi_note"])

    def test_unknown_unit(self):
        with self.assertRaises(T.ToolError):
            N.nearby_same_category("없는 자리", "한식")


class PlannerAppTest(unittest.TestCase):
    def test_save_compare_and_calculate(self):
        app = AppTest.from_file(APP).run(timeout=120)
        self.assertFalse(app.exception)
        app.session_state["main_tab"] = "🔎 자리 이력"
        app.text_input(key="unit_addr").set_value(ADDR).run(timeout=120)
        self.assertFalse(app.exception)
        save = [b for b in app.button if b.label == "내 후보지에 저장"]
        self.assertEqual(len(save), 1)
        app.session_state["main_tab"] = "🔎 자리 이력"
        save[0].click().run(timeout=120)
        self.assertEqual(len(app.session_state["saved_units"]), 1)
        self.assertTrue(any(b.label == "후보지에서 빼기" for b in app.button))
        self.assertTrue(any(b.key == "saved-0" for b in app.sidebar.button))   # 사이드바 '내 후보지'

        app.session_state["main_tab"] = "⭐ 내 후보지"
        app.selectbox(key="plan_category").set_value("카페").run(timeout=120)
        self.assertFalse(app.exception)
        self.assertTrue(any("3년 생존율" in " ".join(map(str, d.value.index)) for d in app.dataframe))

        nums = app.number_input
        vals = {"결제 1건 평균 금액(원)": 7000, "원가율(%)": 35.0, "카드·배달 수수료율(%)": 3.0, "월세+관리비(만 원)": 150,
                "기타 고정비(만 원)": 30}
        for n in nums:
            if n.label in vals:
                n.set_value(vals[n.label])
        app.session_state["main_tab"] = "⭐ 내 후보지"
        next(b for b in app.button if b.label == "계산하기").click().run(timeout=120)
        self.assertFalse(app.exception)
        self.assertTrue(any(m.label == "본전 하루 결제" and m.value == "16건" for m in app.metric))


if __name__ == "__main__":
    unittest.main()
