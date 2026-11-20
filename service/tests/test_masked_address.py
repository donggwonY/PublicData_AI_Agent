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
