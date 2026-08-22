"""Tests for repository hygiene that does not require reading secrets."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_env_is_gitignored():
    """The local dotenv file must remain outside version control."""

    lines = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in {line.strip() for line in lines}
