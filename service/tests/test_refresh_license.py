"""인허가 주간·월간 갱신 (E-04, 2026-11-24). 네트워크 없이 파일 이름·기준 시점 규칙만 확인한다."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import config as C
from pipeline import compare_license as CL
from pipeline import refresh_license as R


class RefreshLicenseTest(unittest.TestCase):
    def test_target_name_is_read_by_batch(self):
        n = R.target_name("식품_일반음식점_api.csv", "delta20261130")
        self.assertEqual(n, "식품_일반음식점_api_delta20261130.csv")
        stem = Path(n).stem
        self.assertEqual(stem.split("_")[1], "일반음식점")      # build.load_raw 업종 칸
        self.assertIn("_api", stem)                          # build.load_raw UTF-8 표시
        self.assertIn("일반음식점", C.SERVICES)

    def test_latest_update_point_across_files(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "식품_일반음식점.csv", Path(d) / "식품_일반음식점_api_delta20261130.csv"
            a.write_bytes("데이터갱신시점\n2026-11-05 22:00:00\n".encode("cp949"))
            b.write_bytes("데이터갱신시점\n2026-11-29 10:00:00\n".encode("utf-8-sig"))
            with patch.object(CL, "raw_files", lambda: {"일반음식점": [a, b]}):
                self.assertEqual(R.latest_update_point(), datetime(2026, 11, 29, 10, 0))

    def test_combined_keeps_latest_row(self):
        with tempfile.TemporaryDirectory() as d:
            head = "개방자치단체코드,관리번호,사업장명,최종수정시점,데이터갱신시점\n"
            a, b = Path(d) / "식품_일반음식점.csv", Path(d) / "식품_일반음식점_api_delta1.csv"
            a.write_bytes((head + "3410000,X,옛이름,2026-01-01 00:00:00,2026-01-02 00:00:00\n").encode("cp949"))
            b.write_bytes((head + "3410000,X,새이름,2026-11-20 00:00:00,2026-11-21 00:00:00\n").encode("utf-8-sig"))
            df = CL._combined([a, b])
            self.assertEqual(df["사업장명"].tolist(), ["새이름"])


if __name__ == "__main__":
    unittest.main()
