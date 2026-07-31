.PHONY: help install dev test lint format typecheck migrate revision worker up down logs

help:
	@echo "install    Install dev dependencies"
	@echo "dev        Run the API with autoreload"
	@echo "worker     Run the Celery worker"
	@echo "test       Run the test suite with coverage"
	@echo "lint       Ruff lint + format check"
	@echo "format     Apply Ruff formatting and autofixes"
	@echo "typecheck  Run mypy"
	@echo "migrate    Apply migrations"
	@echo "revision   Autogenerate a migration (m=\"message\")"
	@echo "up/down    Start/stop the full docker-compose stack"

install:
	pip install -r requirements-dev.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Zero-dependency run: SQLite instead of Postgres, no worker, no Redis.
# The analysis falls back to an in-process background task.
dev-sqlite:
	DATABASE_URL=sqlite+aiosqlite:///./dev.db uvicorn app.main:app --reload --port 8000

worker:
	celery -A app.workers.celery_app worker --loglevel=info -Q analysis

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff check . --fix
	ruff format .

typecheck:
	mypy app

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

up:
	docker compose -f ../docker-compose.yml up --build

down:
	docker compose -f ../docker-compose.yml down -v
