"""행정동 이름으로 적힌 지번 처리 (E-12 8절 A, 2026-11-20 추가)."""
import os
import unittest

import pandas as pd

from core import address as A
from pipeline.build import normalize_admin_jibun


class AdminDongTest(unittest.TestCase):
    def test_admin_to_legal_name(self):
        self.assertEqual(A.admin_to_legal_dong("대명10동"), "대명동")
        self.assertEqual(A.admin_to_legal_dong("내당2.3동"), "내당동")
        self.assertEqual(A.admin_to_legal_dong("신천1,2동"), "신천동")
        self.assertIsNone(A.admin_to_legal_dong("대명동"))
        self.assertIsNone(A.admin_to_legal_dong("동성로2가"))   # 법정동 '…N가'는 그대로

    def test_normalize_only_when_legal_dong_is_known(self):
        legal = [A.parse_jibun(f"대구광역시 남구 대명동 {i}") for i in range(1, 21)]   # 법정동 20건
        rows = legal + [A.parse_jibun("대구광역시 남구 대명10동 1225"),
                        A.parse_jibun("대구광역시 중구 성내1동 10"),            # 같은 이름의 법정동 없음
                        A.parse_jibun("대구광역시 군위군 군위읍 동부리 5")]
        q = {}
        out = normalize_admin_jibun(pd.Series(rows), q)
        self.assertEqual(out.iloc[20]["key"], "대구광역시 남구 대명동 1225")
        self.assertEqual(out.iloc[20]["dong"], "대명동")
        self.assertEqual(out.iloc[21]["key"], "대구광역시 중구 성내1동 10")
        self.assertEqual(out.iloc[22]["key"], "대구광역시 군위군 군위읍 동부리 5")
        self.assertEqual(q["address_admin_dong_to_legal"], 1)

    def test_admin_style_query_finds_legal_unit(self):
        os.environ.setdefault("APP_DATA_SOURCE", "parquet")
        from core import tools as T
        r = T.normalize_address("남구 대명10동 1225")
        self.assertGreater(r["matched"], 0)
        self.assertIn("행정동 이름", r["method"])


if __name__ == "__main__":
    unittest.main()
