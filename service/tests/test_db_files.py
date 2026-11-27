"""DB 에 parquet 파일로 저장하는 무료 플랜 운영 경로(2026-11-27). 실제 DB 없이 순수 부분만 시험한다."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import config as C
from core import datasource as ds
from pipeline import load_parquet_files as L


class DbFilesTest(unittest.TestCase):
    def test_frames_from_files_round_trip(self):
        rows = [(t, (C.PROCESSED_DIR / f"{t}.parquet").read_bytes()) for t in ds.TABLES
                if (C.PROCESSED_DIR / f"{t}.parquet").exists()]
        frames = ds.frames_from_files(rows)
        local = ds.load_parquet(C.PROCESSED_DIR).frames
        for t in ds.TABLES:
            if local[t] is None:
                self.assertIsNone(frames[t])
            else:
                self.assertTrue(local[t].equals(frames[t]), t)

    def test_missing_required_table_fails(self):
        rows = [("units", (C.PROCESSED_DIR / "units.parquet").read_bytes())]
        with self.assertRaises(LookupError):
            ds.frames_from_files(rows)

    def test_layout_selects_reader_and_falls_back(self):
        env = {"APP_DATA_SOURCE": "auto", "APP_DATABASE_URL": "postgresql://x", "APP_DB_LAYOUT": "files"}
        with patch.dict(os.environ, env), \
                patch.object(ds, "load_db_files", side_effect=OSError("down")) as files, \
                patch.object(ds, "load_db") as tables:
            loaded = ds.load(C.PROCESSED_DIR)
        files.assert_called_once()
        tables.assert_not_called()
        self.assertEqual(loaded.source, "parquet")          # DB 실패 시 저장소 parquet 로 대체
        self.assertTrue(any("DB 읽기 실패" in n for n in loaded.notes))

    def test_default_layout_is_tables(self):
        env = {"APP_DATA_SOURCE": "auto", "APP_DATABASE_URL": "postgresql://x"}
        with patch.dict(os.environ, env), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APP_DB_LAYOUT", None)
            with patch.object(ds, "load_db", return_value="tables") as tables, patch.object(ds, "load_db_files") as files:
                self.assertEqual(ds.load(C.PROCESSED_DIR), "tables")
        tables.assert_called_once()
        files.assert_not_called()

    def test_loader_refuses_shared_db(self):
        with self.assertRaises(SystemExit):
            L.check_target("postgresql://postgres.uoiamnbkzlvlskngataq:pw@host:5432/postgres")
        with self.assertRaises(SystemExit):
            L.check_target("postgresql://postgres.other:pw@host:5432/postgres")
        L.check_target("postgresql://postgres.ihaypnmvrnvbjdbtgiaq:pw@host:5432/postgres")   # 통과


if __name__ == "__main__":
    unittest.main()
