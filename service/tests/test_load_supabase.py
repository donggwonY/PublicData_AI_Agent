"""적재 스크립트 규칙 검사: 사전 점검·권한 정책·retired 버전 삭제 보호 (E-04 2단계, 2026-11-20 추가). DB 불필요."""
import unittest

from pipeline.load_supabase import deletable, precheck, reader_grants
from tests.test_check_data import _frames

META = {"reference_date": "2026-11-06"}


class LoadSupabaseRulesTest(unittest.TestCase):
    def test_precheck_passes_clean_frames(self):
        self.assertFalse(precheck(_frames(), META).failed)

    def test_precheck_blocks_duplicate_keys(self):
        import pandas as pd
        f = _frames()
        f["units"] = pd.DataFrame({"uid": ["A 1층", "A 1층", "B 1층"]})
        self.assertTrue(precheck(f, META).failed)

    def test_reader_grants_never_drop_policies(self):
        sql = "\n".join(reader_grants()).lower()
        self.assertNotIn("drop policy", sql)
        self.assertIn("if not exists (select 1 from pg_policies", sql)

    def test_deletable_protects_current_and_latest_retired(self):
        st = {3: "retired", 5: "retired", 6: "retired", 9: "retired", 10: "current", 4: "failed"}
        ok, refused = deletable(st, [3, 4, 9, 10, 11])
        self.assertEqual(ok, [3, 4])          # failed 버전(행 0)도 지울 수 있다
        self.assertEqual(set(refused), {9, 10, 11})
        self.assertIn("되돌릴", refused[9])


if __name__ == "__main__":
    unittest.main()
