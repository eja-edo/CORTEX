PY := .venv/bin/python

.PHONY: setup db-up db-down migrate test lint web-install web-dev web-test web-build

setup:
	python3.12 -m venv .venv
	$(PY) -m pip install -q -e '.[dev]'

db-up:
	docker compose up -d --wait pg

db-down:
	docker compose down

migrate:
	set -a; . ./.env.test; set +a; $(PY) -m alembic upgrade head

test:
	set -a; . ./.env.test; set +a; $(PY) -m pytest

lint:
	.venv/bin/ruff check cortex_leads tests

# Console (web/): needs Node 22+ in PATH (e.g. `nvm use 22`). The build lands in web/dist, which the API serves at /app.
web-install:
	cd web && npm ci

web-dev:
	cd web && npm run dev   # http://localhost:5173/app/ , proxies /api to the core on :8200

web-test:
	cd web && npm run build && npm test

web-build:
	cd web && npm run build
