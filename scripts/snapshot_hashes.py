"""Portable hashes for repository analysis snapshots, not downloaded raw sources.

JSON/Python snapshots use SHA-256 after CRLF -> LF normalization. Everything
else (including Parquet) is hashed byte-for-byte. No JSON parsing, whitespace
stripping, key sorting, encoding conversion or trailing-newline changes occur.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


TEXT_SUFFIXES = {".json", ".py"}


def _snapshot_bytes(path: Path) -> tuple[bytes, bytes]:
    raw = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        raw.decode("utf-8")  # Reject unexpected encodings instead of repairing them.
        return raw, raw.replace(b"\r\n", b"\n")
    return raw, raw


def snapshot_sha256(path: Path) -> str:
    """Write new snapshot hashes in the portable LF form."""
    _, canonical = _snapshot_bytes(path)
    return hashlib.sha256(canonical).hexdigest()


def verify_snapshot_hash(path: Path, expected: str) -> None:
    """Verify current content, accepting historic LF/CRLF text byte hashes.

    Legacy manifests remain evidence of their original files. Only newline
    variants of the current content are accepted; changed values still fail.
    Raw-source provenance must keep using an exact byte hash instead.
    """
    raw, canonical = _snapshot_bytes(path)
    candidates = {hashlib.sha256(canonical).hexdigest()}
    if path.suffix.lower() in TEXT_SUFFIXES:
        candidates.add(hashlib.sha256(raw).hexdigest())
        candidates.add(hashlib.sha256(canonical.replace(b"\n", b"\r\n")).hexdigest())
    if expected not in candidates:
        raise ValueError(f"Snapshot hash mismatch: {path}")
