.PHONY: infra up migrate api worker frontend test lint

infra:
	docker compose -f deploy/compose.infra.yml up -d

up:
	docker compose -f deploy/compose.dev.yml up --build

migrate:
	cd agent && uv run alembic upgrade head

api:
	cd agent && uv run uvicorn app.main_api:app --reload --port 8000

worker:
	cd agent && uv run python -m app.main_worker

frontend:
	cd frontend && npm run dev

test:
	cd agent && uv run pytest -q
	cd frontend && npm run build

lint:
	cd agent && uv run ruff check src/app alembic tests/test_app_core.py
	cd frontend && npm run lint
