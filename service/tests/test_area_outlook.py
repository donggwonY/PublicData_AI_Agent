"""동네·자리: A-07 1년 뒤 거주 인구·최근 1년 연령대 이사 인원·A-09 비슷한 동네 5곳 (조회 함수, 표시 규칙, 화면 흐름)."""
import os
import unittest
from pathlib import Path

os.environ.setdefault("APP_DATA_SOURCE", "parquet")

from streamlit.testing.v1 import AppTest  # noqa: E402

from core import tools as T  # noqa: E402


class AreaOutlookToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = T.store()
        if s.population_forecast is None or s.similar_areas is None:
            raise unittest.SkipTest("population_forecast·similar_areas parquet 없음")
        cls.pf, cls.sa, cls.ctx = s.population_forecast, s.similar_areas, s.area_context

    def test_every_profile_area_links_to_population(self):
        keys = set(zip(self.ctx.gu, self.ctx.admin_dong))
        self.assertEqual(keys - set(zip(self.pf.gu, self.pf.admin_dong)), set())

    def test_stored_values_and_display_rule(self):
        out = T.get_population_outlook("중구", "성내1동")
        self.assertTrue(out["available"])
        self.assertEqual(len(out["items"]), 12)
        self.assertEqual(out["basis"], "행정안전부 주민등록 거주자 기준")
        rows = self.pf[(self.pf.gu == "중구") & (self.pf.admin_dong == "성내1동")].set_index("age_band")
        for i in out["items"]:
            r = rows.loc[i["age_band"]]
            self.assertEqual(i["current"], int(r.current_population))
            self.assertEqual(i["forecast"], int(r.forecast_population))
            if i["age_band"] in ("age_30_39", "age_00_09"):   # 예측 증감이 아니라 최근 1년 실제 기록
                self.assertEqual(i["change_kind"], "recent_actual")
                self.assertEqual(i["change_value"], int(r.recent_change_12m))
                self.assertTrue(i["change_text"].startswith("최근 1년 동안"))
            else:
                self.assertEqual(i["change_kind"], "forecast")
                self.assertEqual(i["change_value"], int(r.forecast_change))
            if i["age_band"] == "total":
                self.assertIsNone(i["net_move"])
            else:
                self.assertEqual(i["net_move"], int(r.net_move_12m))
        text = " ".join(str(v) for i in out["items"] for v in i.values())
        self.assertNotIn("검증", text)
        self.assertNotIn("이사", text)

    def test_net_move_top_bands(self):
        # 나이를 한 살씩 밀어 본 순이동: 성내1동 30대는 단순 증감 +103명이지만 이사로는 -12명
        out = T.get_population_outlook("중구", "성내1동")
        self.assertEqual(out["move_period"], "2025-10 → 2026-10")
        self.assertEqual(out["top_in"], {"age_band": "age_20_29", "label": "20대", "net_move": 213})
        self.assertEqual(out["top_out"], {"age_band": "age_30_39", "label": "30대", "net_move": -12})
        items = {i["age_band"]: i for i in out["items"]}
        self.assertEqual(items["age_80_89"]["net_move_text"], "-15명")   # 70대 이상은 순위에서 제외
        out = T.get_population_outlook("북구", "산격3동")
        self.assertEqual((out["top_in"]["label"], out["top_in"]["net_move"]), ("20대", 278))
        self.assertEqual((out["top_out"]["label"], out["top_out"]["net_move"]), ("30대", -122))
        # 모든 계산 지역에서 1~69세 순이동 + 나이 드는 효과 = 10세 구간 단순 증감은 net_move_2026.py 가 점검한다
        ok = self.pf[self.pf.status == "available"]
        self.assertEqual(ok["net_move_12m"].notna().sum(), 141 * 11)

    def test_withheld_area_keeps_current_population(self):
        out = T.get_population_outlook("달성군", "구지면")   # 원자료 이름은 구지읍
        self.assertFalse(out["available"])
        self.assertTrue(all(i["forecast"] is None and i["change_kind"] == "withheld" for i in out["items"]))
        self.assertGreater(out["items"][0]["current"], 0)
        self.assertIsNone(out["move_period"])
        self.assertIsNone(out["top_in"])
        self.assertIsNone(out["top_out"])

    def test_similar_areas_follow_stored_order(self):
        out = T.get_similar_areas("중구", "성내1동")
        stored = self.sa[(self.sa.gu == "중구") & (self.sa.admin_dong == "성내1동") & (self.sa.option == "combined")]
        self.assertEqual([i["dong"] for i in out["items"]], stored.sort_values("rank").rec_admin_dong.tolist())
        self.assertNotIn("성내1동", [i["dong"] for i in out["items"]])
        total = self.pf[self.pf.age_band == "total"].set_index(["gu", "admin_dong"])
        for i in out["items"]:   # 거주자 수는 1년 뒤 인구 카드와 같은 A-07 값
            self.assertEqual(i["residents"], int(total.loc[(i["gu"], i["dong"])].current_population))

    def test_priority_option_shows_share(self):
        out = T.get_similar_areas("중구", "성내1동", "population:age_30_39")
        self.assertEqual(out["option_label"], "30대 비중")
        self.assertIsNotNone(out["base_share_pct"])
        self.assertTrue(all("option_share_pct" in i for i in out["items"]))
        self.assertEqual(T.similar_option_label("children"), "0~9세 비중")
        self.assertEqual(T.similar_option_label("food"), "음식 업종 비중")

    def test_small_area_has_no_recommendation(self):
        out = T.get_similar_areas("군위군", "우보면")
        self.assertFalse(out["available"])
        self.assertIn("비교할 자료가 부족", out["reason"])


class AreaOutlookAIToolTests(unittest.TestCase):
    """AI 상담 도구 get_resident_outlook·find_similar_areas: 화면과 같은 값, 이름 해석, 되묻기."""

    @classmethod
    def setUpClass(cls):
        s = T.store()
        if s.population_forecast is None or s.similar_areas is None:
            raise unittest.SkipTest("population_forecast·similar_areas parquet 없음")

    def test_registered_everywhere(self):
        from core.tool_specs import TOOL_SPECS
        from ui_visuals import TOOL_LABELS
        for name in ("get_resident_outlook", "find_similar_areas"):
            self.assertIn(name, T.TOOL_FUNCTIONS)
            self.assertIn(name, {t["name"] for t in TOOL_SPECS})
            self.assertIn(name, TOOL_LABELS)

    def test_resident_same_as_screen(self):
        out = T.get_resident_outlook("성내1동")
        self.assertEqual(len(out["areas"]), 1)
        a, screen = out["areas"][0], T.get_population_outlook("중구", "성내1동")
        self.assertEqual((a["top_in"], a["top_out"]), (screen["top_in"], screen["top_out"]))
        self.assertIn("5,512명 → 2027-10 추정 5,653명(+141명)", a["display"][0])
        self.assertIn("20대(+213명)", a["display"][1])
        self.assertIn("30대(-12명)", a["display"][2])
        ages = {r["age_band"]: r for r in a["by_age"]}
        self.assertIsNone(ages["30대"]["forecast_change"])     # 30대·0~9세는 증감 방향을 예측으로 주지 않는다
        self.assertIsNone(ages["0~9세"]["forecast_change"])
        self.assertEqual(ages["30대"]["forecast"], 1115)
        self.assertEqual(ages["80대"]["net_move_note"], "사망 포함")

    def test_resident_name_handling(self):
        out = T.get_resident_outlook("범어동")          # 행정동 여러 곳 → 모두
        self.assertEqual([a["area"] for a in out["areas"]], [f"수성구 범어{i}동" for i in range(1, 5)])
        self.assertIsNotNone(out["note"])
        self.assertNotIn("by_age", out["areas"][0])
        out = T.get_resident_outlook("대명동")          # 번호 순서
        self.assertEqual(out["areas"][0]["area"], "남구 대명1동")
        self.assertEqual(T.get_resident_outlook("삼덕동1가")["areas"][0]["area"], "중구 삼덕동")   # 법정동 → 행정동
        held = T.get_resident_outlook("구지면")
        self.assertFalse(held["available"])
        self.assertTrue(all(r["forecast"] is None for r in held["areas"][0]["by_age"]))
        with self.assertRaises(T.ToolError):
            T.get_resident_outlook("없는동")

    def test_similar_same_as_screen_and_criteria(self):
        out = T.find_similar_areas("성내1동")
        screen = T.get_similar_areas("중구", "성내1동")
        self.assertEqual(out["items"], screen["items"])
        self.assertEqual(len(out["display"]), 6)
        self.assertIn("1. 중구 성내2동", out["display"][1])
        # 기준 동네 자신의 값도 준다(없으면 AI 가 표 빈칸을 지어낸 사례가 있었음): 상가는 A-09, 거주자는 A-07
        self.assertEqual(out["base"], {"shops": 3377, "residents": 5512, "share_pct": None})
        self.assertIn("상가 3,377곳(2026-09) · 거주자 5,512명(2026-10)", out["display"][0])
        share = T.find_similar_areas("성내1동", criterion="30대 비중")
        self.assertIn("30대 비중 19.5%(2026-09)", share["display"][0])
        self.assertIn("(2026-09)", share["display"][1].split("30대 비중")[1])
        self.assertEqual(T.find_similar_areas("성내1동", criterion="30대 비중")["criterion"], "30대 비중")
        self.assertEqual(T.find_similar_areas("성내1동", criterion="식당 많은 곳")["criterion"], "음식 업종 비중")
        self.assertEqual(T.find_similar_areas("성내1동", criterion="상가 규모")["criterion"], "상가·거주자 규모")
        self.assertEqual(T.find_similar_areas("성내1동", criterion="어린이")["criterion"], "0~9세 비중")
        self.assertIn("창업 성과", " ".join(out["caveat"]))
        with self.assertRaises(T.ToolError):
            T.find_similar_areas("성내1동", criterion="날씨")
        with self.assertRaises(T.ToolError):                    # 행정동 여러 곳이면 되묻는다
            T.find_similar_areas("범어동")
        self.assertFalse(T.find_similar_areas("우보면")["available"])


class AreaOutlookScreenTests(unittest.TestCase):
    def test_cards_and_go_to_similar_area(self):
        if T.store().similar_areas is None:
            self.skipTest("similar_areas parquet 없음")
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=90)
        app.radio(key="dash_view").set_value("동네·자리").run(timeout=90)
        app.selectbox(key="dash_gu").select("중구").run(timeout=90)
        app.selectbox(key="dash_dong").select("성내1동").run(timeout=90)
        self.assertFalse(app.exception)
        cards = {m.label: m for m in app.metric}
        self.assertNotIn("30대 1년 뒤 추정", cards)   # 특정 연령대만 따로 카드로 보여 주지 않는다
        self.assertEqual(cards["전체 1년 뒤 추정"].value, "5,653명")
        self.assertEqual(cards["전체 1년 뒤 추정"].delta, "1년 뒤 +141명")
        self.assertEqual((cards["많이 들어온 연령대"].value, cards["많이 들어온 연령대"].delta),
                         ("20대", "최근 1년 +213명"))
        self.assertEqual((cards["많이 나간 연령대"].value, cards["많이 나간 연령대"].delta),
                         ("30대", "최근 1년 -12명"))
        captions = " ".join(c.value for c in app.caption)
        self.assertIn("나이 드는 효과를 빼고", captions)
        self.assertNotIn("30대·0~9세는", captions)
        self.assertIn("같은 사람들과 비교한 증감", captions)
        table = app.dataframe[0].value
        self.assertIn("최근 1년 인구 변화", table.columns)
        self.assertFalse(table["최근 1년 인구 변화"].str.contains("사망").any())
        first =T.get_similar_areas("중구", "성내1동")["items"][0]
        app.button(key="dash_similar_go_combined_1").click().run(timeout=90)
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="dash_dong").value, first["dong"])
        # 다른 구의 추천으로 이동하면 지역 선택도 그 구로 바뀐다
        other = next(i for i in T.get_similar_areas("중구", first["dong"])["items"] if i["gu"] != "중구")
        rank = other["rank"]
        app.button(key=f"dash_similar_go_combined_{rank}").click().run(timeout=90)
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="dash_gu").value, other["gu"])
        self.assertEqual(app.selectbox(key="dash_dong").value, other["dong"])


if __name__ == "__main__":
    unittest.main()
