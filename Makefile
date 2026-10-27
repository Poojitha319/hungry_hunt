.DEFAULT_GOAL := help
PY ?= .venv/bin/python
UV ?= uv

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## create .venv and install with dev extras (uv if present, else pip)
	@if command -v $(UV) >/dev/null 2>&1; then $(UV) sync --extra dev; else python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"; fi
	@.venv/bin/pre-commit install >/dev/null 2>&1 || true

lock: ## refresh uv.lock
	$(UV) lock

lint: ## ruff check
	.venv/bin/ruff check src tests migrations

fmt: ## ruff format + autofix
	.venv/bin/ruff format src tests migrations && .venv/bin/ruff check --fix src tests migrations

typecheck: ## mypy over src
	.venv/bin/mypy

test: ## pytest
	$(PY) -m pytest -q

check: lint typecheck test ## everything CI runs for Python
	.venv/bin/ruff format --check src tests migrations

migrate: ## alembic upgrade head against DATABASE_URL
	.venv/bin/alembic upgrade head

run: ## one full daily run (fetch → track → assess → send → prune)
	.venv/bin/hunt run

digest-preview: ## render today's digest to digest.html without sending
	.venv/bin/hunt digest --preview digest.html && open digest.html

api: ## review API on :8000
	.venv/bin/uvicorn hungry_hunt.api.app:app --reload

ui: ## review app on :5173
	cd frontend && npm run dev

openapi: ## regenerate frontend/openapi.json and the TypeScript client from the app
	$(PY) -c "import json,pathlib; from hungry_hunt.api.app import create_app; from hungry_hunt.config import Settings; pathlib.Path('frontend/openapi.json').write_text(json.dumps(create_app(Settings(database_url='sqlite://')).openapi(), indent=1) + '\n')"
	cd frontend && npm run gen

docker: ## build the API image
	docker build -t hungry-hunt .

.PHONY: help install lock lint fmt typecheck test check migrate run digest-preview api ui openapi docker
