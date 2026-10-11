"""core 순수 함수 단위 테스트 (데이터·API 키 불필요).  실행: python -m unittest tests.test_core_units"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as C  # noqa: E402
from core import address as A  # noqa: E402
from core.cycle import STAGE_DESC, classify_stage  # noqa: E402


class ParseJibunTest(unittest.TestCase):
    def test_basic_with_sub_number(self):
        r = A.parse_jibun("대구광역시 중구 삼덕동1가 28-6")
        self.assertEqual(r["key"], "대구광역시 중구 삼덕동1가 28-6")
        self.assertEqual((r["gu"], r["dong"]), ("중구", "삼덕동1가"))

    def test_zero_sub_and_leading_zero_dropped(self):
        self.assertEqual(A.parse_jibun("대구광역시 수성구 범어동 012-0")["key"], "대구광역시 수성구 범어동 12")

    def test_san_and_eup(self):
        r = A.parse_jibun("대구광역시 달성군 화원읍 천내리 산 3-1")
        self.assertEqual(r["key"], "대구광역시 달성군 화원읍 천내리 산3-1")
        self.assertEqual(r["eup"], "화원읍")

    def test_abbreviated_sido_and_whitespace(self):
        self.assertEqual(A.parse_jibun("대구  수성구　범어동 1")["key"], "대구광역시 수성구 범어동 1")

    def test_non_daegu_or_empty(self):
        self.assertIsNone(A.parse_jibun("서울특별시 중구 명동 1"))
        self.assertIsNone(A.parse_jibun(None))


class ParseRoadTest(unittest.TestCase):
    def test_road_with_paren_dong(self):
        r = A.parse_road("대구광역시 중구 동성로5길 83, 2층 (삼덕동1가)")
        self.assertEqual(r["key"], "대구광역시 중구 동성로5길 83")
        self.assertEqual((r["road"], r["dong"]), ("동성로5길", "삼덕동1가"))

    def test_underground(self):
        self.assertEqual(A.parse_road("대구광역시 중구 국채보상로 지하 100")["key"], "대구광역시 중구 국채보상로 지하 100")


class FloorAndGuTest(unittest.TestCase):
    def test_extract_floor(self):
        self.assertEqual(A.extract_floor(None, "대구광역시 중구 삼덕동1가 28-6 2 층"), "2층")
        self.assertEqual(A.extract_floor("대구광역시 중구 동성로 1, 지하 1층"), "지하1층")
        self.assertIsNone(A.extract_floor("대구광역시 중구 동성로 1", None))

    def test_normalize_gu(self):
        for text in ("수성", "수성구", "대구 수성구", "대구광역시 수성구 범어동"):
            self.assertEqual(A.normalize_gu(text), "수성구", text)
        self.assertEqual(A.normalize_gu("달성"), "달성군")
        self.assertIsNone(A.normalize_gu("강남구"))
        self.assertIsNone(A.normalize_gu(""))

    def test_is_daegu(self):
        self.assertTrue(A.is_daegu("대구 중구 동성로 1"))
        self.assertFalse(A.is_daegu("경상북도 경산시"))
        self.assertFalse(A.is_daegu(None))


class ClassifyStageTest(unittest.TestCase):
    def stage(self, o, c, op, cp):
        return classify_stage(o, c, op, cp, active_now=110, active_then=100)["stage"]

    def test_stages(self):
        self.assertEqual(self.stage(60, 40, 50, 40), "성장기")        # r=1.5, rp=1.25
        self.assertEqual(self.stage(60, 40, 30, 40), "회복기")        # r=1.5, rp=0.75
        self.assertEqual(self.stage(50, 50, 30, 40), "성숙기")        # r=1.0
        self.assertEqual(self.stage(30, 50, 50, 50), "쇠퇴 진입기")   # r=0.6, rp=1.0
        self.assertEqual(self.stage(30, 50, 30, 50), "쇠퇴기")        # r=0.6, rp=0.6

    def test_boundaries(self):
        self.assertEqual(self.stage(55, 50, 50, 50), "성장기")        # r=1.1 은 성장 쪽
        self.assertEqual(self.stage(45, 50, 50, 50), "성숙기")        # r=0.9 는 성숙 쪽

    def test_on_hold(self):
        half = C.CYCLE_MIN_EVENTS // 2
        self.assertEqual(self.stage(half - 1, half, 50, 50), "판정 보류")  # 이벤트 부족
        self.assertEqual(self.stage(40, 0, 50, 50), "판정 보류")            # 폐업 0 → 비율 없음

    def test_output_fields(self):
        out = classify_stage(60, 40, 30, 40, active_now=110, active_then=100)
        self.assertEqual(out["open_close_ratio_recent"], 1.5)
        self.assertEqual(out["open_close_ratio_prev"], 0.75)
        self.assertEqual(out["active_change_pct"], 10.0)
        self.assertEqual(out["stage_desc"], STAGE_DESC["회복기"])
        self.assertIsNone(classify_stage(40, 0, 50, 50, 1, 0)["active_change_pct"])


if __name__ == "__main__":
    unittest.main()
