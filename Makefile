SHELL := /bin/bash
.PHONY: setup test test-all dev backend frontend lint clean help install

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-15s %s\n", $$1, $$2}'

setup: $(VENV) install   ## Create venv and install all dependencies

$(VENV):
	python3 -m venv $(VENV)

install: $(VENV)
	$(PIP) install -e ".[dev]"

test:           ## Run unit tests
	$(PY) -m pytest tests/unit/ -v

test-all:       ## Run all tests including integration
	$(PY) -m pytest tests/ -v

dev: backend    ## Start backend dev server

backend:        ## Start backend with hot reload
	source $(VENV)/bin/activate && set -a && source .env && set +a && \
		mkdir -p logs && \
		uvicorn backend.main:app --reload --app-dir src --port 8000 2>&1 | tee logs/backend-stdout.log

frontend:       ## Start frontend dev server
	cd src/frontend && npm run dev 2>&1 | tee ../../logs/frontend.log

lint:           ## Run linter
	$(PY) -m ruff check src/ tests/ || true

clean:          ## Remove venv, caches, build artifacts
	rm -rf $(VENV) __pycache__ .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
