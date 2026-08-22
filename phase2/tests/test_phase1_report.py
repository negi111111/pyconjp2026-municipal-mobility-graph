"""Tests for the self-contained Phase 1 HTML acceptance report."""

from __future__ import annotations

from pathlib import Path

from scripts.verify_phase1 import write_html


def sample_report() -> dict:
    return {
        "generated_at": "2026-08-21T00:00:00+00:00",
        "overall_status": "pass",
        "llm_mode": True,
        "queries": [
            {
                "id": "AC-1",
                "query": "<script>alert(1)</script>",
                "status": "pass",
                "evidence": {
                    "top_city": "廿日市市",
                    "hiroshima_to_city_people": 13_331,
                    "city_to_hiroshima_people": 20_804,
                    "bidirectional_people": 34_135,
                },
            },
            {
                "id": "AC-2",
                "query": "人流ハブ",
                "status": "pass",
                "evidence": {"weighted_pagerank": {"city": "広島市", "value": 0.185664}},
            },
            {
                "id": "AC-3",
                "query": "生活圏",
                "status": "pass",
                "evidence": {"cross_prefecture_community_count": 4},
            },
            {
                "id": "AC-4",
                "query": "都市類似度",
                "status": "pass",
                "evidence": {"top_city": "岡山市", "cosine_similarity": 0.8570},
            },
            {
                "id": "AC-5",
                "query": "空港アクセス",
                "status": "pass",
                "evidence": {
                    "top_city": "岩国市",
                    "top_airport": "岩国飛行場",
                    "top_distance_km": 3.5,
                    "reference_distance_km": 32.9,
                },
            },
            {
                "id": "AC-6",
                "query": "類似かつ空港",
                "status": "pass",
                "evidence": {
                    "top_city": "岡山市",
                    "cosine_similarity": 0.8570,
                    "distance_km": 12.8,
                },
            },
            {
                "id": "AC-7",
                "query": "医療類似度",
                "status": "pass",
                "evidence": {"top_city": "岡山市", "cosine_similarity": 0.8376},
            },
        ],
        "checks": [{"name": "quality", "status": "pass"}],
        "seed_review": [
            {
                "rank": 1,
                "candidate_prefecture": "広島県",
                "candidate_name": "府中町",
                "bidirectional_flow_with_seed": 31_980,
                "strongest_seed_name": "広島市",
                "strongest_seed_bidirectional_flow": 26_711,
            }
        ],
    }


def test_write_html_escapes_content_and_keeps_evidence(tmp_path: Path):
    output = tmp_path / "phase1_acceptance.html"

    write_html(sample_report(), output)

    content = output.read_text(encoding="utf-8")
    assert content.startswith("<!doctype html>")
    assert 'html lang="ja"' in content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "<script>" not in content
    assert "34,135" in content
    assert "Azure OpenAIのPlanner/Responseを使用" in content
    assert "acceptance_results.json" in content
    assert "|---" not in content
