# Phase 2 proposal: review-gated expansion to 100 cities

## Status

Phase 2 is a proposal only. It is not implemented, and no final list of 100 cities is
claimed here. Work may begin only after the Phase 1 acceptance gate in
`docs/phase1_design.md` passes in the current project environment and the user approves
expansion.

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

After the entry gate passes, create `docs/city_selection.md` containing:

- the exact data editions and candidate-universe date;
- selection criteria and any hard constraints;
- the proposed, not-yet-final 100 cities;
- counts by region, prefecture, formal role, and population band;
- one or more evidence-backed inclusion reasons per candidate;
- excluded near-misses and their reasons;
- ambiguous cases and alternative compositions;
- the impact of threshold or regional-balance changes;
- an explicit reviewer decision section.

The candidate list becomes final only after review. Until then it must not be written
into the production configuration or described as the nationwide benchmark.

## Proposed engineering expansion

Once the 100-city list is approved:

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
   regression tests.
8. Update `sources.yml`, the data-license summary, download manifest, and answer
   evidence before publishing a Phase 2 result.

## Deferred data proposals

Rent, climate, nature, forest, hot springs, disaster risk, rail, Shinkansen, route
counts, commercial facilities, and tourism remain separate proposals. Each requires a
documented user need, official-or-open source, license/redistribution review, temporal
definition, normalization design, and tests. None is silently added to rankings.

If future unstructured policy, planning, tourism, culture, or long-document questions
are added, implement them as separately reviewed components. Their output must remain
separate from hard-fact ranking inputs and must not be stored as verified municipal facts
without an independent source and validation policy.

## Phase 2 completion gate

Phase 2 completion would require the reviewed city list, reproducible nationwide
inputs, evidence-equivalent answers for the Phase 1 query families, explicit universe
labels, data-license compliance, and scaling tests. This document intentionally does
not assert that those conditions are satisfied.
