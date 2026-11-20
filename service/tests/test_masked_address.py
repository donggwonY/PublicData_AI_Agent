"""번지가 가려진 주소 처리 (E-12, 2026-11-20 추가): 구·동은 읽고 자리 키는 만들지 않는다."""
import unittest

import pandas as pd

from core import address as A
from pipeline.check_data import Report, check_frames
from tests.test_check_data import _frames


class MaskedAddressTest(unittest.TestCase):
    def test_masked_jibun_gives_area_not_key(self):
        self.assertIsNone(A.parse_jibun("대구광역시 남구 대명동 ****-*"))
        self.assertEqual(A.parse_masked("대구광역시 남구 대명동 ****-*"),
                         {"gu": "남구", "eup": None, "dong": "대명동"})

    def test_masked_eup_ri(self):
        r = A.parse_masked("대구광역시 군위군 군위읍 동부리 ***-* ")
        self.assertEqual((r["gu"], r["eup"], r["dong"]), ("군위군", "군위읍", "동부리"))

    def test_masked_road_uses_paren_dong(self):
        r = A.parse_masked("대구광역시 달서구 진천로 **, *층 (진천동)")
        self.assertEqual((r["gu"], r["dong"]), ("달서구", "진천동"))

    def test_normal_address_is_not_masked(self):
        self.assertIsNone(A.parse_masked("대구광역시 중구 삼덕동1가 28-6"))
        self.assertIsNone(A.parse_masked("대구광역시 중구 동성로5길 83, 2층 (삼덕동1가)"))


class LooseAreaTest(unittest.TestCase):
    """정규 형식이 아닌 주소에서 구·동만 읽기 (E-12 후속). 이미 확인된 동 이름일 때만 받는다."""
    KNOWN = {"북구": {"태전동", "칠성동1가"}, "남구": {"대명동"}, "동구": {"신서동", "신암동"}, "달성군": {"다사읍"},
             "서구": {"내당동"}}
    AREA_GU = {"신서동": "동구", "다사읍": "달성군", "태전동": "북구"}

    def _p(self, addr):
        r = A.parse_area_loose(addr, self.KNOWN, self.AREA_GU)
        return (r["gu"], r["dong"]) if r else None

    def test_glued_lot_number(self):
        self.assertEqual(self._p("대구광역시 북구 태전동496-12"), ("북구", "태전동"))

    def test_admin_style_number_maps_to_legal(self):
        self.assertEqual(self._p("대구광역시 남구 대명06동1052-1"), ("남구", "대명동"))
        self.assertEqual(self._p("대구광역시 서구 내당 2.3동 1035-33"), ("서구", "내당동"))

    def test_glued_gu_and_missing_gu(self):
        self.assertEqual(self._p("대구광역시 동구신암1동 603-128"), ("동구", "신암동"))
        self.assertEqual(self._p("대구광역시 신서동 535-9"), ("동구", "신서동"))
        self.assertEqual(self._p("대구광역시  다사읍 대실역북로5길 6"), ("달성군", "다사읍"))

    def test_unknown_names_are_rejected(self):
        self.assertIsNone(self._p("대구광역시 팔공로53길 10 (이시아폴리스더샵1차 상가101호)"))
        self.assertIsNone(self._p("대구광역시 국채보상로159길 41, 107동 101호"))

    def test_masked_legal_dong_ending_ro(self):
        r = A.parse_masked("대구광역시 중구 남성로 **** *층")
        self.assertEqual((r["gu"], r["dong"]), ("중구", "남성로"))


class MaskedGaTest(unittest.TestCase):
    def test_masked_ga_takes_nearest_same_family_dong(self):
        from pipeline.build import resolve_masked_ga
        df = pd.DataFrame({
            "gu": ["수성구"] * 5,
            "dong": ["수성동1가", "수성동4가", "범어동", "수성동*가", "수성동*가"],
            "lat": [35.860, 35.850, 35.8575, 35.8598, None],
            "lon": [128.620, 128.620, 128.620, 128.620, None],
        })
        q = {}
        out = resolve_masked_ga(df, q)
        self.assertEqual(out.iloc[3], "수성동1가")   # 가장 가까운 가게는 범어동이지만 같은 '수성동N가'만 후보
        self.assertTrue(pd.isna(out.iloc[4]))         # 좌표가 없으면 비운다
        self.assertEqual(q["address_masked_ga_resolved"], {"total": 2, "resolved_by_coords": 1})


class MaskedCheckTest(unittest.TestCase):
    def _run(self, frames):
        rep = Report()
        check_frames(frames, {"reference_date": "2026-11-06"}, "t", rep)
        return {(r[1], r[2]) for r in rep.rows}, rep

    def test_masked_store_without_unit_is_ok(self):
        f = _frames()
        extra = f["stores"].iloc[:1].assign(mgmt_no="m", uid=None, addr_masked=True)
        f["stores"] = pd.concat([f["stores"].assign(addr_masked=False), extra], ignore_index=True)
        _, rep = self._run(f)
        self.assertFalse(rep.failed, [r for r in rep.rows if r[1] == "FAIL"])

    def test_unmasked_store_without_unit_fails(self):
        f = _frames()
        extra = f["stores"].iloc[:1].assign(mgmt_no="m", uid=None, addr_masked=False)
        f["stores"] = pd.concat([f["stores"].assign(addr_masked=False), extra], ignore_index=True)
        rows, _ = self._run(f)
        self.assertIn(("FAIL", "stores → units (uid)"), rows)

    def test_masked_unit_key_fails(self):
        f = _frames()
        f["units"] = pd.concat([f["units"], pd.DataFrame({"uid": ["대구광역시 남구 대명동 ****-*"]})])
        rows, _ = self._run(f)
        self.assertIn(("FAIL", "units 가려진 번지 자리 키 없음"), rows)


if __name__ == "__main__":
    unittest.main()
