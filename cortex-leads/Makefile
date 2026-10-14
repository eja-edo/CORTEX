PY := .venv/bin/python

.PHONY: setup db-up db-down migrate test lint

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
