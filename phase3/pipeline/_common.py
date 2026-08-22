"""Shared environment loading and SSDSE metadata types for Phase 1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Try encodings in this order when the Phase 1 SSDSE loader reads a source file.
ENCODINGS = ("utf-8-sig", "cp932", "euc_jp")


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """`.env` を読んで os.environ に入れる（python-dotenv を使わない簡易版）。

    既に環境変数がある場合は**上書きしない**（CI やシェルの指定を尊重する）。
    """
    path = path or (PROJECT_ROOT / ".env")
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        loaded[key] = val
        os.environ.setdefault(key, val)
    return loaded


@dataclass
class Ssdse:
    """Hold SSDSE metadata after separating its three header rows."""

    path: Path
    codes: list[str]     # row0: 列コード
    years: list[str]     # row1: 年度
    labels: list[str]    # row2: 日本語の項目名
    data: pd.DataFrame   # row3 以降（列名は日本語ラベル）
    encoding: str

    @property
    def edition(self) -> str:
        parts = self.path.stem.split("-")
        return parts[2] if len(parts) > 2 else "?"

    def code_of(self, label: str) -> str | None:
        for c, l in zip(self.codes, self.labels):
            if l == label:
                return c
        return None
