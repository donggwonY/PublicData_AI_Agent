"""앱 주소 입력 예외 처리 (E-12 10절, 2026-11-20 추가). 저장소 가공 데이터로 확인한다."""
import os
import unittest

os.environ.setdefault("APP_DATA_SOURCE", "parquet")

from core import address as A  # noqa: E402
from core import tools as T  # noqa: E402
from core.tools import ToolError  # noqa: E402


def top(q):
    r = T.normalize_address(q)
    return (r["matches"][0]["unit_id"] if r["matches"] else None), r.get("method")


class AddressInputTest(unittest.TestCase):
    def test_dash_variants_keep_sub_number(self):
        self.assertEqual(A.clean("28–6 28—6 28−6 28－6"), "28-6 28-6 28-6 28-6")
        self.assertEqual(top("대구 중구 삼덕동1가 28–6")[0], top("대구 중구 삼덕동1가 28-6")[0])

    def test_missing_gu_prefers_exact_jibun(self):
        uid, method = top("군위읍 동부리 142")
        self.assertEqual(uid, "대구광역시 군위군 군위읍 동부리 142")
        self.assertIn("구 추정", method)

    def test_jibun_like_query_does_not_match_road_number(self):
        uid, _ = top("범어동 123")   # 없는 지번: 도로명 번호 123으로 다른 자리를 주지 않는다
        self.assertIsNone(uid)

    def test_short_ga_and_beonji(self):
        self.assertEqual(A.short_ga_to_full("삼덕1가"), "삼덕동1가")
        self.assertIsNone(A.short_ga_to_full("동성로2가"))
        self.assertEqual(top("삼덕1가 28-6")[0], top("중구 삼덕동1가 28-6")[0])
        self.assertEqual(top("수성구 범어동 산103번지")[0], "대구광역시 수성구 범어동 산103")

    def test_profile_does_not_pick_silently(self):
        r = T.get_area_profile(gu="수성구")
        self.assertIn("candidates", r)
        r = T.get_area_profile(dong="대명동")       # 법정동이 행정동 여러 곳에 걸침
        self.assertGreater(r["matched"], 1)
        with self.assertRaises(ToolError):
            T.get_area_profile(gu="대구")
        self.assertEqual(T.get_area_profile(dong="대명3동")["area"], "남구 대명3동")


if __name__ == "__main__":
    unittest.main()
