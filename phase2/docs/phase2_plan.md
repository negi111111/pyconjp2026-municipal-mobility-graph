# Phase 2 proposal: review-gated expansion to 100 cities

## Status

Phase 2 national production implementation is complete for the approved 100-city
search universe. National processing uses 1,719 municipalities with Tokyo's 23 wards
aggregated as R13000. Performance/memory benchmarking was completed in the Phase 1-3
cross-phase audit after the Phase 3 implementation.

## Entry gate

Before selecting or processing a Phase 2 city, record evidence that:

- all nine Phase 1 acceptance criteria pass;
- downloads, checksums, normalization, graph construction, analysis, and natural-
  language queries reproduce without paid or contract-only data;
- provenance and attribution survive raw-to-answer processing;
- metric definitions, missing-data behavior, and reference years are frozen or
  versioned;
- performance and memory measurements identify the actual scaling constraints;
- Phase 1 limitations are understood, especially induced-subgraph centrality and
  city-hall-to-airport straight-line distance.

Any schema or metric change discovered during this review returns to Phase 1 tests
before nationwide selection proceeds.

## Proposed selection process

The target is not the 100 most populous cities. The review set should balance formal
role, observed mobility role, transport role, urban scale, and regional
representativeness.

1. Build a versioned candidate universe from the same municipality-code master used
   by SSDSE and the Census. Resolve designated-city/ward double-counting first.
2. Tag formal anchors: prefectural capitals, ordinance-designated cities, and core
   cities. A tag is evidence, not automatic final inclusion when roles overlap.
3. Compute nationwide OD hub measures on the candidate universe before subsetting.
   This avoids using a 100-city induced graph to decide who the hubs are.
4. Add transparent wide-area transport evidence only from license-reviewed,
   reproducible sources. Airport status/scale can reuse the Phase 1 pipeline;
   Shinkansen or other rail-hub evidence requires a separate source and license review.
5. Stratify by geographic region and urban scale so Tokyo, Osaka, and other very large
   cities do not crowd out regional centres.
6. Produce a candidate table with inclusion reason, conflicting evidence, exclusions,
   missing data, and sensitivity to thresholds.
7. Review the proposed 100 before changing the production city configuration.

No opaque combined "importance" or "livability" score should decide membership.
If a numeric selection aid is used, every component, threshold, normalization, and
regional constraint must be visible, and sensitivity alternatives must be shown.

## Required review artifact

The Stage A/B selection creates `docs/city_selection.md` containing:

- the exact data editions and candidate-universe date;
- selection criteria and any hard constraints;
- the proposed, not-yet-final 100 cities;
- counts by region, prefecture, formal role, and population band;
- one or more evidence-backed inclusion reasons per candidate;
- excluded near-misses and their reasons;
- ambiguous cases and alternative compositions;
- the impact of threshold or regional-balance changes;
- an explicit reviewer decision section.

The candidate list was reviewed and promoted to `configs/phase2_cities.yml`. Any future
change to the 100-city set must regenerate the report and rerun the Phase 2 acceptance.

## Proposed engineering expansion

The approved 100-city list is implemented as follows:

1. Add a versioned Phase 2 configuration without altering the Phase 1 seed.
2. Reuse the same download, normalization, graph, query-plan, evidence, and response
   interfaces; add batching/caching only where measurements justify it.
3. Download the nationwide OD inputs needed to capture all flows among the approved
   cities, retaining cross-prefecture flows and the same field semantics.
4. Compute centrality and selection diagnostics on the declared graph universe, and
   label any 100-city-only analysis as an induced-subgraph result.
5. Refit similarity preprocessing for the declared Phase 2 comparison universe and
   version the feature matrix; Phase 1 similarity scores must not be silently reused.
6. Recalculate municipal-office-to-airport distance with the same point definitions.
7. Add regional and scale-stratified tests, missing-source tests, and performance
   regression tests. These gates are now covered by the Phase 2/3 test suites and
   cross-phase benchmark.
8. Update `sources.yml`, the data-license summary, download manifest, and answer
   evidence before publishing a Phase 2 result.

## Deferred data proposals

Climate and nearest Shinkansen distance were adopted in Phase 3 after coverage and
provenance review. Rent, nature, forest, hot springs, disaster risk, route counts,
commercial facilities, and tourism remain separate proposals. Each requires a
documented user need, official-or-open source, license/redistribution review, temporal
definition, normalization design, and tests. None is silently added to rankings.

If future unstructured policy, planning, tourism, culture, or long-document questions
are added, implement them as separately reviewed components. Their output must remain
separate from hard-fact ranking inputs and must not be stored as verified municipal facts
without an independent source and validation policy.

## Phase 2 completion gate

Phase 2 is complete for the functional, reproducibility, and performance gates:
reviewed city list, national inputs, evidence-equivalent queries, explicit universe
labels, provenance, data-gap handling, and cross-phase benchmark are implemented and
tested. The current next-stage decision is whether a fully covered housing, disaster,
or nature dataset can pass its own adoption gate.

## Reporting status

- Phase 1 detailed report: `../../phase1/docs/phase1_implementation_report.html`
- Phase 2 detailed report: `docs/phase2_implementation_report.html`
- Phase 3 detailed report: `../phase3/docs/phase3_implementation_report.html`
- Cross-phase audit: `../phase3/docs/cross_phase_audit.html`
- Per-phase LLM query commands: each phase `README.md` and `Makefile`
- Same-query comparison: `../../tools/compare_phases.py` via Phase 3 `make compare-phases-llm`
- Local visual audit UI: `../../visualizer/` (Streamlit, Graph Explorer, Query Comparison, Node Inspector)
- LLM latency optimization: Planner high/4096, Response medium/4096, comparison xhigh/8192
