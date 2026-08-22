"""Promote the reviewed provisional selection to the Phase 2 city-set config."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "national_city_candidates.csv"
DEFAULT_OUTPUT = ROOT / "configs" / "phase2_cities.yml"


def run(input_csv: Path = DEFAULT_INPUT, output_yaml: Path = DEFAULT_OUTPUT) -> None:
    candidates = pd.read_csv(input_csv, dtype={"municipality_code": str})
    selected = candidates[candidates["provisional_selected"].astype(bool)].copy()
    if len(selected) != 100:
        raise ValueError(f"expected exactly 100 reviewed candidates; found {len(selected)}")
    if not selected["municipality_code"].is_unique:
        raise ValueError("selected municipality codes are not unique")
    cities = []
    for row in selected.sort_values(["region", "selection_score", "municipality_code"]).to_dict(
        orient="records"
    ):
        cities.append(
            {
                "municipality_id": row["地域コード"],
                "municipality_code": row["municipality_code"],
                "prefecture": row["都道府県"],
                "name": row["name"],
                "region": row["region"],
                "population_2020": int(row["population"]),
                "prefectural_capital": bool(row["prefectural_capital"]),
                "designated_city": bool(row["designated_city"]),
                "core_city": bool(row["core_city"]),
                "phase1_member": bool(row["phase1_member"]),
                "selection_score": float(row["selection_score"]),
                "selection_reason": row["reason"],
            }
        )
    document = {
        "phase": 2,
        "name": "national_major_100",
        "status": "approved_by_user",
        "description": (
            "Reviewed Phase 2 search universe. Analysis metrics use the national "
            "municipality universe; this set controls displayed/search candidates."
        ),
        "source_selection_report": "docs/city_selection.md",
        "analysis_universe": "national_municipalities",
        "search_universe_count": 100,
        "cities": cities,
    }
    output_yaml.parent.mkdir(parents=True, exist_ok=True)
    output_yaml.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-yaml", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.input_csv, args.output_yaml)
    print(args.output_yaml)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
