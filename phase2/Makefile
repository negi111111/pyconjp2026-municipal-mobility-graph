.PHONY: help install download download-selection-od select-cities prepare prepare-phase2 query query-json query-llm query-llm-json visualize test lint acceptance acceptance-phase1-baseline acceptance-llm acceptance-phase2

PY ?= PYTHONPATH=. uv run --no-sync python
RUFF ?= uv run --no-sync ruff
JSON_REPORT ?= data/processed/phase2_acceptance_llm_results.json
HTML_REPORT ?= docs/phase2_acceptance_llm.html

help:
	@echo "Phase 2: national analysis universe -> 100-city search evidence"
	@echo "  make install       core + development dependencies"
	@echo "  make download      download/reuse fixed public source files and write hashes"
	@echo "  make download-selection-od  download 47 prefecture OD workbooks for city selection"
	@echo "  make select-cities  generate provisional national-city selection report"
	@echo "  make prepare       run the Phase 1 baseline preparation"
	@echo "  make prepare-phase2 build national analysis/search processed data"
	@echo "  make query Q='...' ask one Japanese question"
	@echo "  make query-json Q='...' return Structured Evidence as JSON"
	@echo "  make query-llm Q='...' use Azure OpenAI for planning and explanation"
	@echo "  make query-llm-json Q='...' use Azure OpenAI and return JSON evidence"
	@echo "  make visualize     rebuild the four evidence SVGs"
	@echo "  make test          run the regression suite"
	@echo "  make lint          lint the Phase 1 core"
	@echo "  make acceptance    run Phase 2 national preparation and acceptance"
	@echo "  make acceptance-phase1-baseline  run Phase 1 regression acceptance"
	@echo "  make acceptance-llm run acceptance through Azure OpenAI too (API usage)"

install:
	uv sync --extra dev --no-install-project

download:
	$(PY) scripts/download_data.py

download-selection-od:
	$(PY) scripts/download_national_selection_od.py

select-cities:
	$(PY) scripts/select_national_cities.py

prepare:
	$(PY) pipeline/06_prepare_phase1.py

prepare-phase2:
	$(PY) pipeline/06_prepare_phase2.py

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
	@test -n "$(Q)" || (echo "usage: make query-llm-json Q='福岡市に似ている都市は？'" >&2; exit 2)
	@$(PY) -m app.query --query "$(Q)" --llm --json

visualize:
	$(PY) scripts/visualize_phase1.py \
		--data-dir data/processed \
		--output-dir docs/figures

test:
	$(PY) -m pytest -q

lint:
	$(RUFF) check \
		app \
		pipeline/06_prepare_phase1.py \
		pipeline/06_prepare_phase2.py \
		scripts/download_data.py \
		scripts/download_national_selection_od.py \
		scripts/finalize_phase2_cities.py \
		scripts/select_national_cities.py \
		scripts/verify_phase1.py \
		scripts/verify_phase2.py \
		scripts/visualize_phase1.py \
		tests/test_query_layer.py \
		tests/test_visualize_phase1.py \
		tests/test_llm.py \
		tests/test_phase1_report.py \
		tests/test_project_hygiene.py \
		tests/test_phase2_selection.py \
		tests/test_phase2_national.py

acceptance:
	$(MAKE) --no-print-directory acceptance-phase2

acceptance-phase1-baseline:
	$(MAKE) --no-print-directory download
	$(MAKE) --no-print-directory prepare
	$(MAKE) --no-print-directory visualize
	$(MAKE) --no-print-directory test
	$(PY) scripts/verify_phase1.py

acceptance-llm:
	$(PY) scripts/verify_phase2.py --llm \
		--json-report "$(JSON_REPORT)" \
		--html-report "$(HTML_REPORT)"

acceptance-phase2:
	$(MAKE) --no-print-directory prepare-phase2
	$(MAKE) --no-print-directory test
	$(PY) scripts/verify_phase2.py
