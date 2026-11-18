"""동네·자리: A-07 1년 뒤 거주 인구·A-09 비슷한 동네 5곳 (조회 함수, 표시 규칙, 화면 흐름)."""
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
        text = " ".join(str(v) for i in out["items"] for v in i.values())
        self.assertNotIn("검증", text)
        self.assertNotIn("이사", text)

    def test_withheld_area_keeps_current_population(self):
        out = T.get_population_outlook("달성군", "구지면")   # 원자료 이름은 구지읍
        self.assertFalse(out["available"])
        self.assertTrue(all(i["forecast"] is None and i["change_kind"] == "withheld" for i in out["items"]))
        self.assertGreater(out["items"][0]["current"], 0)

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


class AreaOutlookScreenTests(unittest.TestCase):
    def test_cards_and_go_to_similar_area(self):
        if T.store().similar_areas is None:
            self.skipTest("similar_areas parquet 없음")
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=90)
        app.radio(key="dash_view").set_value("동네·자리").run(timeout=90)
        app.selectbox(key="dash_gu").select("중구").run(timeout=90)
        app.selectbox(key="dash_dong").select("성내1동").run(timeout=90)
        self.assertFalse(app.exception)
        labels = [m.label for m in app.metric]
        self.assertIn("전체 1년 뒤 추정", labels)
        self.assertIn("30대 1년 뒤 추정", labels)
        thirty = next(m for m in app.metric if m.label == "30대 1년 뒤 추정")
        self.assertIn("최근 1년", thirty.delta)
        self.assertIn("(실제)", thirty.delta)
        total = next(m for m in app.metric if m.label == "전체 1년 뒤 추정")
        self.assertTrue(total.delta.startswith("1년 뒤 "))
        first = T.get_similar_areas("중구", "성내1동")["items"][0]
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
