# Deep Research Agent

Python/FastAPI deep-research service with a MySQL-backed worker queue and resumable SSE output.

## Architecture

- `agent/src/app/main_api.py`: HTTP API, authentication, uploads, SSE.
- `agent/src/app/main_worker.py`: recoverable background research worker.
- MySQL: users, conversations, runs, messages, attachments, run events.
- Redis: refresh tokens, sandbox bindings, live event and cancel notifications.
- Aliyun OSS: attachments, sources, notes, reports, checkpoints.
- E2B: production research sandbox, one sandbox per conversation.
- `frontend/`: React and TypeScript UI.

The Go backend, tenant records and WebSockets are not used.

## Local development without a full Docker stack

Start MySQL and Redis:

```bash
docker compose -f deploy/compose.infra.yml up -d
```

Create the environment file and database schema:

```bash
cp .env.example .env
cd agent
uv sync --extra dev
uv run alembic upgrade head
```

Run each process in a separate terminal:

```bash
cd agent && uv run uvicorn app.main_api:app --reload --port 8000
cd agent && uv run python -m app.main_worker
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>.

Local development uses `OBJECT_STORE=local` and `SANDBOX_MODE=local`. Production must use
`OBJECT_STORE=oss` and `SANDBOX_MODE=e2b`.

## Full Docker development environment

```bash
cp .env.example .env
docker compose -f deploy/compose.dev.yml up --build
```

Open <http://localhost:8080>.

Docker Desktop is not required. Docker Engine, Colima or OrbStack can run the same Compose files.

## Verification

```bash
cd agent
source .venv/bin/activate
ruff check src/app alembic tests/test_app_core.py
pytest -q

cd ../frontend
npm run build
npm run lint
```
