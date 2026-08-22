.PHONY: help install run visualize

help:
	@echo "PyCon JP 2026 municipal mobility graph"
	@echo "  make install    install visualizer dependencies"
	@echo "  make run        start the local Phase 1-3 visualizer"
	@echo "  make visualize  alias for make run"

install:
	$(MAKE) --no-print-directory -C visualizer install

run:
	$(MAKE) --no-print-directory -C visualizer run

visualize: run
