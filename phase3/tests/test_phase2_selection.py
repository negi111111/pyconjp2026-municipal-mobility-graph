"""Regression checks for the provisional Phase 2 city-selection artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_role_master_has_required_anchor_and_region_contract():
    config = yaml.safe_load(
        (ROOT / "configs" / "phase2_city_roles.yml").read_text(encoding="utf-8")
    )

    assert len(config["prefectural_capitals"]) == 47
    assert len(config["designated_cities"]) == 20
    assert len(set(config["designated_cities"])) == 20
    assert sum(config["region_targets"].values()) == 100
    assert config["synthetic_cities"]["東京都区部"]["municipality_code"] == "13000"


def test_provisional_selection_has_100_unique_candidates():
    candidates = pd.read_csv(
        ROOT / "data" / "processed" / "national_city_candidates.csv",
        dtype={"municipality_code": str},
    )
    summary = json.loads(
        (ROOT / "data" / "processed" / "national_city_selection_summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(candidates) == 793
    assert candidates["municipality_code"].is_unique
    assert int(candidates["provisional_selected"].sum()) == 100
    assert summary["status"] == "approved_by_user"
    assert summary["final_city_set_confirmed"] is True
    config = yaml.safe_load(
        (ROOT / "configs" / "phase2_cities.yml").read_text(encoding="utf-8")
    )
    assert config["status"] == "approved_by_user"
    assert config["search_universe_count"] == 100
    assert len(config["cities"]) == 100


def test_national_selection_od_manifest_covers_all_prefectures():
    manifest = json.loads(
        (
            ROOT / "data" / "provenance" / "national_selection_od_manifest.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["status"] == "selection_bootstrap_unpinned"
    assert len(manifest["files"]) == 47
    assert all(item["sha256"] for item in manifest["files"])
    assert all(item["edition"] == "2020 Population Census Table 3" for item in manifest["files"])
