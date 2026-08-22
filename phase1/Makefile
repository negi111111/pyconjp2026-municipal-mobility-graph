.PHONY: help install download prepare query query-json query-llm query-llm-json visualize test lint acceptance acceptance-llm

PY ?= PYTHONPATH=. uv run --no-sync python
RUFF ?= uv run --no-sync ruff

help:
	@echo "Phase 1: public data -> structured evidence"
	@echo "  make install       core + development dependencies"
	@echo "  make download      download/reuse fixed public source files and write hashes"
	@echo "  make prepare       normalize data, run quality gates, and build the graph"
	@echo "  make query Q='...' ask one Japanese question"
	@echo "  make query-json Q='...' return Structured Evidence as JSON"
	@echo "  make query-llm Q='...' use Azure OpenAI for planning and explanation"
	@echo "  make query-llm-json Q='...' use Azure OpenAI and return JSON evidence"
	@echo "  make visualize     rebuild the four evidence SVGs"
	@echo "  make test          run the regression suite"
	@echo "  make lint          lint the Phase 1 core"
	@echo "  make acceptance    run the end-to-end Phase 1 acceptance verifier"
	@echo "  make acceptance-llm run acceptance through Azure OpenAI too (API usage)"

install:
	uv sync --extra dev --no-install-project

download:
	$(PY) scripts/download_data.py

prepare:
	$(PY) pipeline/06_prepare_phase1.py

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
	@test -n "$(Q)" || (echo "usage: make query-llm-json Q='広島市と似ている都市は？'" >&2; exit 2)
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
		scripts/download_data.py \
		scripts/verify_phase1.py \
		scripts/visualize_phase1.py \
		tests/test_query_layer.py \
		tests/test_visualize_phase1.py \
		tests/test_llm.py \
		tests/test_phase1_report.py \
		tests/test_project_hygiene.py

acceptance:
	$(MAKE) --no-print-directory download
	$(MAKE) --no-print-directory prepare
	$(MAKE) --no-print-directory visualize
	$(MAKE) --no-print-directory test
	$(PY) scripts/verify_phase1.py

acceptance-llm:
	$(PY) scripts/verify_phase1.py --llm
