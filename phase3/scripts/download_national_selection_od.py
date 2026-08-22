"""Download all prefecture-resident Census Table 3 workbooks for city selection.

This bootstrap download is intentionally separate from the production Phase 2
pipeline. It records URLs, retrieval times, sizes, and digests so the national
candidate-selection review can be reproduced before the final city set is
approved and the digests are promoted into the production downloader.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "census_od_national"
PROVENANCE = ROOT / "data" / "provenance"
BASE_URL = "https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId="

PREFECTURE_FILES: tuple[tuple[str, str, str], ...] = (
    ("01", "北海道", "000032214148"),
    ("02", "青森県", "000032214156"),
    ("03", "岩手県", "000032214151"),
    ("04", "宮城県", "000032214174"),
    ("05", "秋田県", "000032214177"),
    ("06", "山形県", "000032214180"),
    ("07", "福島県", "000032214159"),
    ("08", "茨城県", "000032214162"),
    ("09", "栃木県", "000032214165"),
    ("10", "群馬県", "000032214182"),
    ("11", "埼玉県", "000032214185"),
    ("12", "千葉県", "000032214188"),
    ("13", "東京都", "000032214196"),
    ("14", "神奈川県", "000032214199"),
    ("15", "新潟県", "000032214168"),
    ("16", "富山県", "000032214171"),
    ("17", "石川県", "000032214214"),
    ("18", "福井県", "000032214217"),
    ("19", "山梨県", "000032214220"),
    ("20", "長野県", "000032214201"),
    ("21", "岐阜県", "000032214204"),
    ("22", "静岡県", "000032214207"),
    ("23", "愛知県", "000032214210"),
    ("24", "三重県", "000032214213"),
    ("25", "滋賀県", "000032214236"),
    ("26", "京都府", "000032214239"),
    ("27", "大阪府", "000032214242"),
    ("28", "兵庫県", "000032214245"),
    ("29", "奈良県", "000032214248"),
    ("30", "和歌山県", "000032214251"),
    ("31", "鳥取県", "000032214254"),
    ("32", "島根県", "000032214257"),
    ("33", "岡山県", "000032214260"),
    ("34", "広島県", "000032214263"),
    ("35", "山口県", "000032214266"),
    ("36", "徳島県", "000032214269"),
    ("37", "香川県", "000032214272"),
    ("38", "愛媛県", "000032214275"),
    ("39", "高知県", "000032214278"),
    ("40", "福岡県", "000032214281"),
    ("41", "佐賀県", "000032214284"),
    ("42", "長崎県", "000032214287"),
    ("43", "熊本県", "000032214290"),
    ("44", "大分県", "000032214293"),
    ("45", "宮崎県", "000032214296"),
    ("46", "鹿児島県", "000032214299"),
    ("47", "沖縄県", "000032214302"),
)


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
    request = Request(url, headers={"User-Agent": "pyconjp2026-mobility-kg/phase2"})
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

    records: list[dict[str, object]] = []
    for code, prefecture, stat_inf_id in PREFECTURE_FILES:
        filename = f"table3_{code}.xlsx"
        path = RAW / filename
        url = BASE_URL + stat_inf_id
        status = download(url, path, force=args.force)
        record = {
            "prefecture_code": code,
            "prefecture": prefecture,
            "stat_inf_id": stat_inf_id,
            "path": str(path.relative_to(ROOT)),
            "url": url,
            "status": status,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "retrieved_at": utc_now(),
            "edition": "2020 Population Census Table 3",
        }
        records.append(record)
        print(f"[{status:10}] {prefecture} {path.name} (SHA-256 recorded)")
        time.sleep(0.1)

    manifest = {
        "generated_at": utc_now(),
        "generator": "scripts/download_national_selection_od.py",
        "status": "selection_bootstrap_unpinned",
        "purpose": "Candidate city selection review only; not the final Phase 2 production input.",
        "files": records,
    }
    PROVENANCE.mkdir(parents=True, exist_ok=True)
    output = PROVENANCE / "national_selection_od_manifest.json"
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nmanifest: {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
