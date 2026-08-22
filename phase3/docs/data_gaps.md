# Phase 3 data gaps

Phase 3 adds climate normals and nearest Shinkansen-station distance to the
approved national 100-city search universe. The following conditions remain
outside the structured ranking boundary.

| condition | status | reason | next gate |
|---|---|---|---|
| 住居費・家賃 | not adopted | A single official table with the same definition and a non-missing value for all 100 cities was not verified. | Verify one e-Stat table, definition, year, coverage, and redistribution terms before implementation. |
| 災害リスク | feasibility deferred | A city-hall point is not a city-wide risk value; a defensible area/population aggregation has not been fixed. | Choose hazard layers and a reproducible aggregation denominator. |
| 自然環境 | feasibility deferred | “Nature” is not a single auditable metric and no city-wide aggregation has been approved. | Define explicit categories such as protected area or forest share. |
| 鉄道所要時間・乗換 | out of scope | N02-20 provides station/line geometry, not timetable or journey-time evidence. | Adopt an official timetable/GTFS source and define a date-specific travel-time query. |
| 空港便数・就航都市数 | out of scope | Phase 3 does not change the Phase 2 airport contract. | Add a separately versioned route dataset and metric definition. |

## Non-adoption rules

- Missing values are not replaced with national or regional averages.
- An LLM cannot infer a missing value, rank, or threshold.
- A partial source is returned as `missing_structured_conditions`; it is not
  silently included in a composite ranking.
- Phase 3 climate values are station normals, not municipality-wide climate
  estimates.
- Shinkansen access means straight-line distance to the nearest selected
  station only. It does not mean travel time, station service frequency, or
  station-in-municipality membership.

Source details, checksums, and redistribution notes are in
[`data/provenance/phase3_sources.yml`](../data/provenance/phase3_sources.yml) and
[`data/provenance/phase3_download_manifest.json`](../data/provenance/phase3_download_manifest.json).
