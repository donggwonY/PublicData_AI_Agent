"""인허가 API 수집기 (E-04, 2026-11-24). 네트워크 없이 변환·재시도·파일 이름 규칙만 확인한다."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import config as C
from pipeline import fetch_license as F
from pipeline.build import USECOLS


class FetchLicenseTest(unittest.TestCase):
    def test_field_map_covers_batch_columns(self):
        self.assertEqual(set(F.FIELD_MAP), set(USECOLS))

    def test_api_list_matches_services(self):
        apis = F.load_apis()
        self.assertEqual(sorted(a["service"] for a in apis), sorted(C.SERVICES))
        self.assertTrue(all(a["endpoint"].startswith("https://apis.data.go.kr/1741000/") for a in apis))

    def test_file_name_keeps_service_in_second_part(self):
        for a in F.load_apis():
            parts = F.file_name(a).removesuffix(".csv").split("_")
            self.assertEqual(parts[1], a["service"])           # build.load_raw 가 두 번째 칸을 업종으로 읽는다
            self.assertIn("_api", F.file_name(a))              # build.load_raw 가 UTF-8 로 읽는 표시

    def test_items_of_shapes(self):
        self.assertEqual(F.items_of({"items": [{"a": 1}]}), [{"a": 1}])
        self.assertEqual(F.items_of({"items": {"item": {"a": 1}}}), [{"a": 1}])
        self.assertEqual(F.items_of({"items": ""}), [])

    def test_retries_timeout_then_succeeds(self):
        body = {"response": {"header": {"resultCode": "0"}, "body": {"totalCount": 1, "items": []}}}
        ok = io.BytesIO(json.dumps(body).encode())
        ok.__enter__ = lambda s=ok: s
        ok.__exit__ = lambda *a: None
        calls = iter([TimeoutError(), urllib.error.HTTPError("u", 504, "gw", None, None), ok])

        def fake(*a, **k):
            x = next(calls)
            if isinstance(x, Exception):
                raise x
            return x
        with patch.object(F.urllib.request, "urlopen", fake), patch.object(F.time, "sleep", lambda s: None):
            self.assertEqual(F.request("k", "https://x/y", 1, {})["totalCount"], 1)

    def test_auth_error_stops(self):
        def fake(*a, **k):
            raise urllib.error.HTTPError("u", 403, "forbidden", None, None)
        with patch.object(F.urllib.request, "urlopen", fake):
            with self.assertRaises(F.AuthError):
                F.request("k", "https://x/y", 1, {})

    def test_resume_from_saved_page(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            part = Path(d) / "p.json"
            part.write_text(json.dumps({"total": 250, "rows": [{"i": n} for n in range(200)], "next": 3}), encoding="utf-8")
            asked = []

            def fake(key, endpoint, page, cond):
                asked.append(page)
                return {"totalCount": 250, "items": [{"i": n} for n in range(200, 250)]}
            with patch.object(F, "request", fake):
                rows, total = F.fetch_code("k", {"endpoint": "e"}, "3410000", None, part)
            self.assertEqual(asked, [3])                        # 저장된 다음 페이지만 받는다
            self.assertEqual((len(rows), total), (250, 250))

    def test_parallel_pages_keep_order(self):
        import random
        import tempfile
        from pathlib import Path

        def fake(key, endpoint, page, cond):
            F.time.sleep(random.random() / 100)              # 끝나는 순서를 섞는다
            return {"totalCount": 450, "items": [{"p": page, "i": n} for n in range(100 if page < 5 else 50)]}
        with tempfile.TemporaryDirectory() as d, patch.object(F, "request", fake):
            part = Path(d) / "p.json"
            rows, total = F.fetch_code("k", {"endpoint": "e"}, "3410000", None, part, page_workers=3)
            self.assertEqual(total, 450)
            self.assertEqual([r["p"] for r in rows], sorted(r["p"] for r in rows))
            self.assertEqual(len(rows), 450)
            self.assertEqual(json.loads(part.read_text(encoding="utf-8"))["extra"], {})


if __name__ == "__main__":
    unittest.main()
