"""Regression checks for cross-platform snapshot verification."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from snapshot_hashes import snapshot_sha256, verify_snapshot_hash


class SnapshotHashTests(unittest.TestCase):
    def test_git_checkout_keeps_lf_with_autocrlf_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                subprocess.run(["git", "-c", "core.autocrlf=true", *args], cwd=root,
                               check=True, capture_output=True)

            git("init")
            (root / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
            text = b'{\n  "count": 42\n}\n'
            binary = b"PAR1\x00\xff\r\n"
            (root / "data.json").write_bytes(text.replace(b"\n", b"\r\n"))
            (root / "data.parquet").write_bytes(binary)
            git("add", ".gitattributes", "data.json", "data.parquet")
            (root / "data.json").unlink()
            (root / "data.parquet").unlink()
            git("checkout-index", "--all")
            self.assertEqual((root / "data.json").read_bytes(), text)
            self.assertEqual((root / "data.parquet").read_bytes(), binary)

    def test_lf_and_crlf_accept_new_and_legacy_hashes(self):
        lf = '{\n  "카페": 42\n}\n'.encode("utf-8")
        crlf = lf.replace(b"\n", b"\r\n")
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".json", ".py"):
                path = Path(directory) / ("snapshot" + suffix)
                for content in (lf, crlf, lf.replace(b"\n", b"\r\n", 1)):
                    path.write_bytes(content)
                    self.assertEqual(snapshot_sha256(path), hashlib.sha256(lf).hexdigest())
                    for old_content in (lf, crlf):
                        verify_snapshot_hash(path, hashlib.sha256(old_content).hexdigest())

    def test_value_whitespace_and_final_newline_changes_are_rejected(self):
        original = b'{\n  "count": 42\n}\n'
        expected = hashlib.sha256(original.replace(b"\n", b"\r\n")).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            for changed in (original.replace(b"42", b"41"), original.replace(b"  ", b" "),
                            original.rstrip(b"\n"), original.replace(b"\n", b"\r")):
                with self.subTest(content=changed):
                    path.write_bytes(changed)
                    with self.assertRaisesRegex(ValueError, "Snapshot hash mismatch"):
                        verify_snapshot_hash(path, expected)

    def test_binary_and_raw_csv_are_byte_exact(self):
        raw = b"PAR1\x00\xff\r\nexample\r\n"
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".parquet", ".xlsx", ".csv"):
                path = Path(directory) / ("source" + suffix)
                path.write_bytes(raw)
                self.assertEqual(snapshot_sha256(path), hashlib.sha256(raw).hexdigest())
                verify_snapshot_hash(path, hashlib.sha256(raw).hexdigest())
                with self.assertRaises(ValueError):
                    verify_snapshot_hash(path, hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest())

    def test_invalid_utf8_is_not_silently_reencoded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_bytes(b"\xff\r\n")
            with self.assertRaises(UnicodeDecodeError):
                snapshot_sha256(path)

    def test_existing_d01_manifest_and_a01_dependencies(self):
        manifest = json.loads((ROOT / "docs/d01/manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["sha256"].items():
            verify_snapshot_hash(ROOT / "service/data/snapshots/20260923_7services" / name, expected)
        references = [
            ("poi_join.json", "input_hashes", "station_locations.json"),
            ("hypothesis.json", "input_sha256", "poi_join.json"),
            ("time_slots.json", "input_hashes", "hypothesis.json"),
        ]
        for report, field, source in references:
            data = json.loads((ROOT / "docs/a01" / report).read_text(encoding="utf-8"))
            expected = data[field][source] if isinstance(data[field], dict) else data[field]
            verify_snapshot_hash(ROOT / "docs/a01" / source, expected)


if __name__ == "__main__":
    unittest.main()
