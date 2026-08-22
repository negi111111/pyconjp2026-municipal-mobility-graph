"""Download the public Phase 3 climate and railway source archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROVENANCE = ROOT / "data" / "provenance"

DOWNLOADS = {
    "jma_normal_surface": (
        "https://www.data.jma.go.jp/obd/stats/data/mdrr/normal/2020/data/normal_surface.zip",
        RAW / "climate" / "jma_normal_surface.zip",
    ),
    "mlit_railway_n02_20": (
        "https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-20/N02-20_GML.zip",
        RAW / "rail" / "N02-20_GML.zip",
    ),
}

# Filled after the source archives were reviewed and downloaded.
EXPECTED_SHA256 = {
    "jma_normal_surface": "29bccfa59bd3d0c681dae51bbda54ee5b7beda82596bd924693decc14d939127",
    "mlit_railway_n02_20": "12fadde339dfbe3088e99dbd53da19447cd7c4bb8ba4af540e2a73c86a0458c7",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path, *, force: bool) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0 and not force:
        return "reused"
    temporary = target.with_suffix(target.suffix + ".part")
    request = Request(url, headers={"User-Agent": "pyconjp2026-mobility-kg/phase3"})
    try:
        with urlopen(request, timeout=180) as response, temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        if temporary.stat().st_size == 0:
            raise OSError("downloaded file is empty")
        temporary.replace(target)
        return "downloaded"
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    records = []
    for key, (url, path) in DOWNLOADS.items():
        status = download(url, path, force=args.force)
        observed = sha256(path)
        expected = EXPECTED_SHA256[key]
        if expected and observed != expected:
            raise RuntimeError(f"checksum mismatch for {key}: {observed} != {expected}")
        records.append(
            {
                "dataset_key": key,
                "url": url,
                "path": str(path.relative_to(ROOT)),
                "status": status,
                "bytes": path.stat().st_size,
                "sha256": observed,
                "retrieved_at": utc_now(),
                "checksum_verified": bool(expected and observed == expected),
            }
        )
        print(f"[{status:10}] {key} (SHA-256 recorded)")
    manifest = {
        "generated_at": utc_now(),
        "phase": 3,
        "status": "reviewed_source_archives",
        "files": records,
    }
    PROVENANCE.mkdir(parents=True, exist_ok=True)
    output = PROVENANCE / "phase3_download_manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
