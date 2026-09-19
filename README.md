# Deep Research Agent

Three processes:

- **Go** (`backend/`) — auth, tenant isolation, conversations, SSE, Kafka fan-out
- **Python** (`agent/`) — ReAct loop (mock in v1). Owns later subagents and context
- **TypeScript** (`frontend/`) — conversation UI

## Prerequisites

Go 1.23+, Docker (Colima is fine), Node 20+, uv.

```bash
colima start   # if using Colima
docker compose -f deploy/docker-compose.yml up -d
```

## Run

```bash
# terminal 1
cd backend && go run ./cmd/server

# terminal 2
cd agent && uv sync && PYTHONPATH=src uv run python -m agent_service

# terminal 3
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 — register, then send a research question.

Kafka UI: http://localhost:8088

## Layout

See `docs/contracts/` for HTTP, Kafka, and event types.
