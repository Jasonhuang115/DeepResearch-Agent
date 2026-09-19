# Deep Research Agent

Three processes:

- **Go** (`backend/`) — auth, tenant isolation, conversations, SSE, Kafka fan-out
- **Python** (`agent/`) — OpenAI-compatible Chat Completions loop (`research_engine`) plus this product's prompts and tools (`agent_service`)
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
cd agent && uv sync
export OPENAI_API_KEY=sk-...          # required for live Q&A
# export OPENAI_MODEL=gpt-4.1-mini    # optional
# export OPENAI_BASE_URL=...          # optional compatible proxy
# export AGENT_MAX_TURNS=8            # optional
PYTHONPATH=src uv run python -m agent_service

# terminal 3
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 — register, then ask a question. The model answers in the conversation; follow-ups reuse history from Go.

This round: `web_search` is mock (not real web). `Read` / `Write` / `Bash` are registered but not implemented (they return an error; the loop continues).

Agent tests: `cd agent && uv sync --extra dev && uv run pytest`.

Kafka UI: http://localhost:8088

## Layout

- `agent/src/research_engine/` — tool-calling loop, FinishKind, OpenAI client
- `agent/src/agent_service/` — Kafka consumer, prompt fragments, tool registry, runner

See `docs/contracts/` for HTTP, Kafka, and event types.
