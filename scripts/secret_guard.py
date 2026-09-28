"""Shared checks for files and values that must not enter Git history."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

SECRET_PATH_PARTS = {
    ".mentee", "auth.json", "credentials.json", "service-account.json",
    "service_account.json", "secrets.toml", ".npmrc", ".pypirc",
}
SECRET_PATTERNS = (
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"gh[po]_[A-Za-z0-9]{20,}"),
    re.compile(rb"sk-(?:proj-|ant-)[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AIza[A-Za-z0-9_-]{35}"),
    re.compile(rb"(?:GH_TOKEN|GEMINI_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|SUPABASE_SERVICE_ROLE_KEY)\s*[:=]\s*['\"]?[A-Za-z0-9._-]{16,}"),
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
)


def is_secret_path(name: str) -> bool:
    return any(
        part in SECRET_PATH_PARTS or part == ".env" or
        (part.startswith(".env.") and part != ".env.example")
        for part in PurePosixPath(name).parts
    )


def contains_secret(data: bytes, local_token: str = "") -> bool:
    return bool(local_token and local_token.encode("utf-8") in data) or any(
        pattern.search(data) for pattern in SECRET_PATTERNS
    )
