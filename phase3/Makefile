.PHONY: help install download download-phase3 download-selection-od select-cities prepare prepare-phase2 prepare-phase3 query query-json query-llm query-llm-json compare-phases compare-phases-llm diagnose-similarity test lint acceptance acceptance-llm acceptance-phase3 acceptance-phase3-llm

PY ?= PYTHONPATH=. uv run --no-sync python
RUFF ?= uv run --no-sync ruff
JSON_REPORT ?= data/processed/phase3_acceptance_results.json
HTML_REPORT ?= docs/phase3_acceptance.html
COMPARE_OUTPUT_DIR ?= /tmp/pyconjp2026-mobility-kg-phase-comparison
SIMILARITY_DIAGNOSTIC_OUTPUT ?= /tmp/pyconjp2026-mobility-kg-similarity-diagnostic.json

help:
	@echo "Phase 3: national 100-city search plus climate/Shinkansen evidence"
	@echo "  make install       core + development dependencies"
	@echo "  make download      download/reuse fixed public source files and write hashes"
	@echo "  make download-phase3  download/reuse JMA and MLIT Phase 3 archives"
	@echo "  make download-selection-od  download 47 prefecture OD workbooks for city selection"
	@echo "  make select-cities  generate provisional national-city selection report"
	@echo "  make prepare       run the Phase 1 baseline preparation"
	@echo "  make prepare-phase2 build national analysis/search processed data"
	@echo "  make prepare-phase3 build climate and Shinkansen feature tables"
	@echo "  make query Q='...' ask one Japanese question"
	@echo "  make query-json Q='...' return Structured Evidence as JSON"
	@echo "  make query-llm Q='...' use Azure OpenAI for planning and explanation"
	@echo "  make query-llm-json Q='...' use Azure OpenAI and return JSON evidence"
	@echo "  make compare-phases Q='...' run the same query through Phase 1-3"
	@echo "  make compare-phases-llm Q='...' compare Phase 1-3 and ask the LLM to analyze differences"
	@echo "  make diagnose-similarity  decompose Phase 1 -> Phase 2 similarity population effects"
	@echo "  make test          run the regression suite"
	@echo "  make lint          lint the Phase 3 implementation and tests"
	@echo "  make acceptance    run Phase 3 preparation, tests, and acceptance"
	@echo "  make acceptance-llm run Phase 3 acceptance through Azure OpenAI (API usage)"
	@echo "  make acceptance-phase3-llm  run Phase 3 acceptance through Azure OpenAI"

install:
	uv sync --extra dev --no-install-project

download:
	$(PY) scripts/download_data.py

download-phase3:
	$(PY) scripts/download_phase3_data.py

download-selection-od:
	$(PY) scripts/download_national_selection_od.py

select-cities:
	$(PY) scripts/select_national_cities.py

prepare:
	$(PY) pipeline/06_prepare_phase1.py

prepare-phase2:
	$(PY) pipeline/06_prepare_phase2.py

prepare-phase3:
	$(PY) pipeline/07_prepare_phase3.py

query:
	@test -n "$(Q)" || (echo "usage: make query Q='広島市と人の行き来が最も多い都市は？'" >&2; exit 2)
	@$(PY) -m app.query --query "$(Q)"

query-json:
	@test -n "$(Q)" || (echo "usage: make query-json Q='広島市と似ている都市は？'" >&2; exit 2)
	@$(PY) -m app.query --query "$(Q)" --json

query-llm:
	@test -n "$(Q)" || (echo "usage: make query-llm Q='広島市と人の行き来が最も多い都市は？'" >&2; exit 2)
	@$(PY) -m app.query --query "$(Q)" --llm

query-llm-json:
	@test -n "$(Q)" || (echo "usage: make query-llm-json Q='福岡市に似ていて冬が比較的暖かい都市は？'" >&2; exit 2)
	@$(PY) -m app.query --query "$(Q)" --llm --json

compare-phases:
	@test -n "$(Q)" || (echo "usage: make compare-phases Q='広島市と都市特性が似ている都市は？'" >&2; exit 2)
	@$(PY) ../tools/compare_phases.py \
		--query "$(Q)" \
		--output-dir "$(COMPARE_OUTPUT_DIR)"

compare-phases-llm:
	@test -n "$(Q)" || (echo "usage: make compare-phases-llm Q='広島市と都市特性が似ている都市は？'" >&2; exit 2)
	@$(PY) ../tools/compare_phases.py \
		--query "$(Q)" \
		--llm-analysis \
		--output-dir "$(COMPARE_OUTPUT_DIR)"

diagnose-similarity:
	@$(PY) ../tools/diagnose_similarity.py \
		--output "$(SIMILARITY_DIAGNOSTIC_OUTPUT)"

test:
	$(PY) -m pytest -q

lint:
	$(RUFF) check \
		app \
		pipeline/06_prepare_phase1.py \
		pipeline/06_prepare_phase2.py \
		pipeline/07_prepare_phase3.py \
		scripts/download_data.py \
		scripts/download_national_selection_od.py \
		scripts/finalize_phase2_cities.py \
		scripts/select_national_cities.py \
		scripts/verify_phase3.py \
		scripts/download_phase3_data.py \
		scripts/benchmark_cross_phase.py \
		../tools/compare_phases.py \
		../tools/diagnose_similarity.py \
		tests/test_query_layer.py \
		tests/test_llm.py \
		tests/test_project_hygiene.py \
		tests/test_phase2_selection.py \
		tests/test_phase2_national.py \
		tests/test_phase3_data.py \
		tests/test_phase3_query.py

acceptance:
	$(MAKE) --no-print-directory acceptance-phase3

acceptance-llm:
	$(PY) scripts/verify_phase3.py --llm \
		--json-report "$(JSON_REPORT)" \
		--html-report "$(HTML_REPORT)"

acceptance-phase3:
	$(MAKE) --no-print-directory prepare-phase3
	$(MAKE) --no-print-directory test
	$(PY) scripts/verify_phase3.py \
		--json-report "data/processed/phase3_acceptance_results.json" \
		--html-report "docs/phase3_acceptance.html"

acceptance-phase3-llm:
	$(PY) scripts/verify_phase3.py --llm \
		--json-report "data/processed/phase3_acceptance_llm_results.json" \
		--html-report "docs/phase3_acceptance_llm.html"
