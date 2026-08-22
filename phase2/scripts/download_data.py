"""Download the fixed public datasets used by Phase 1.

No API key or paid contract is required.  Binary source files are intentionally
not required to live in Git: this command recreates them, verifies every file
against the reviewed Phase 1 SHA-256 digest, and writes a run manifest to
``data/provenance/download_manifest.json``.

Examples
--------
    python scripts/download_data.py
    python scripts/download_data.py --only geography
    python scripts/download_data.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROVENANCE = ROOT / "data" / "provenance"
USER_AGENT = (
    "pyconjp2026-mobility-kg/1.0 (academic public-data reproducibility; see the project README)"
)

DOWNLOADS: dict[str, tuple[str, Path]] = {
    "ssdse": (
        "https://www.nstac.go.jp/files/SSDSE-A-2026.csv",
        RAW / "SSDSE-A-2026.csv",
    ),
    "census_shimane": (
        "https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000032214257",
        RAW / "census_od" / "table3_shimane.xlsx",
    ),
    "census_okayama": (
        "https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000032214260",
        RAW / "census_od" / "table3_okayama.xlsx",
    ),
    "census_hiroshima": (
        "https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000032214263",
        RAW / "census_od" / "table3_hiroshima.xlsx",
    ),
    "census_yamaguchi": (
        "https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000032214266",
        RAW / "census_od" / "table3_yamaguchi.xlsx",
    ),
    "census_kagawa": (
        "https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000032214272",
        RAW / "census_od" / "table3_kagawa.xlsx",
    ),
    "census_ehime": (
        "https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId=000032214275",
        RAW / "census_od" / "table3_ehime.xlsx",
    ),
    "airports": (
        "https://nlftp.mlit.go.jp/ksj/gml/data/C28/C28-21/C28-21_GML.zip",
        RAW / "airports" / "C28-21_GML.zip",
    ),
    "airport_passengers": (
        "https://www.mlit.go.jp/koku/content/002016480.xlsx",
        RAW / "airports" / "airport_management_2025.xlsx",
    ),
    "municipality_facilities": (
        "https://nlftp.mlit.go.jp/ksj/gml/data/P05/P05-22/P05-22_GML.zip",
        RAW / "geography" / "P05-22_GML.zip",
    ),
}

# Reviewed on 2026-08-21.  A source changing at the same URL must stop the
# reproducible build instead of silently changing an analysis result.  Updating
# a digest is therefore an explicit source-review change, not a runtime option.
EXPECTED_SHA256: dict[str, str] = {
    "ssdse": "471ad23bd8f9a7cc01f0c684b9762934e855d2400e3a77608a12171018fc655a",
    "census_shimane": "009ebb89b29310abd34eb4f794142f1b0084371976fbe0fcdcb6b52e0ff722b4",
    "census_okayama": "bfb427a41937f31c0ca54459ea78b586806efda808896eb68bc907b1ea164eae",
    "census_hiroshima": "32cd55b6b7c93af403c7b0909e8838e4fbc0acc75495cf32ce03be83e8d75dc7",
    "census_yamaguchi": "0fc5c7b48d4c1ebaf099b8b7afa5e6731e85a0ecd8415b585f5d098f468174f8",
    "census_kagawa": "ad8257c82a80b1167a24f1b3ae9f9f3ba29a2120dbd53b7f8d470ebe2d9b2705",
    "census_ehime": "296f78dcd740938d442ecf7a8cc838b5eb0763b4941955205d41d30d0cef8ef4",
    "airports": "07d69353a34558d7ebd21d4b5f62b685d4f9b9d0e55c6eed6ce05aefcc6b7b35",
    "airport_passengers": "0cd693d9b7dcc8b4c279608f6bb21468ededc8013a62754a3530b46bd34e988e",
    "municipality_facilities": ("3056d3e0d02248143f1f2c9a5e62fd37717eb761a7257106b5d252415aef4cdc"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(url: str) -> Request:
    return Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})


def download(
    url: str,
    target: Path,
    *,
    force: bool = False,
    expected_sha256: str | None = None,
) -> str:
    """Atomically download *url* to *target* and return its status."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size and not force:
        return "reused"

    temporary = target.with_suffix(target.suffix + ".part")
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urlopen(request(url), timeout=120) as response, temporary.open("wb") as fh:
                shutil.copyfileobj(response, fh)
            if not temporary.stat().st_size:
                raise OSError("downloaded file is empty")
            if expected_sha256 is not None:
                observed = sha256(temporary)
                if observed != expected_sha256:
                    raise OSError(
                        f"download checksum mismatch: expected {expected_sha256}, "
                        f"observed {observed}"
                    )
            temporary.replace(target)
            return "downloaded"
        except Exception as exc:  # pragma: no cover - depends on the network
            last = exc
            temporary.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError(f"failed to download {url}: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        choices=["all", "ssdse", "census", "airports", "geography"],
        default="all",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    selected: dict[str, tuple[str, Path]] = {}
    for key, value in DOWNLOADS.items():
        if key.startswith("census_"):
            group = "census"
        elif key.startswith("airport") or key == "airports":
            group = "airports"
        elif key == "municipality_facilities":
            group = "geography"
        else:
            group = key
        if args.only in ("all", group):
            selected[key] = value

    manifest: dict[str, Any] = {
        "generated_at": utc_now(),
        "generator": "scripts/download_data.py",
        "files": {},
    }
    for key, (url, path) in selected.items():
        expected_sha256 = EXPECTED_SHA256[key]
        status = download(
            url,
            path,
            force=args.force,
            expected_sha256=expected_sha256,
        )
        observed_sha256 = sha256(path)
        if observed_sha256 != expected_sha256:
            raise RuntimeError(
                f"checksum mismatch for {path.relative_to(ROOT)}: "
                f"expected {expected_sha256}, observed {observed_sha256}. "
                "The source must be reviewed before updating the pinned digest."
            )
        manifest["files"][key] = {
            "path": str(path.relative_to(ROOT)),
            "url": url,
            "status": status,
            "bytes": path.stat().st_size,
            "sha256": observed_sha256,
            "expected_sha256": expected_sha256,
            "checksum_verified": True,
        }
        print(f"[{status:10}] {path.relative_to(ROOT)} (SHA-256 verified)")

    PROVENANCE.mkdir(parents=True, exist_ok=True)
    manifest_path = PROVENANCE / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nchecksum manifest: {manifest_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
