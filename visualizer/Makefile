.PHONY: help install run test lint

PY ?= uv run --no-sync python
RUFF ?= uv run --no-sync ruff

help:
	@echo "Phase 1-3 local visual audit UI"
	@echo "  make install  sync visualizer dependencies"
	@echo "  make run      start Streamlit locally without an API key"
	@echo "  make test     run adapter tests"
	@echo "  make lint     lint visualizer code"

install:
	uv sync --extra dev --no-install-project

run:
	@$(PY) -m streamlit run app.py

test:
	@$(PY) -m pytest -q

lint:
	@$(RUFF) check app.py adapters.py tests
