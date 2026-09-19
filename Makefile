.PHONY: infra up backend agent frontend test

infra:
	docker compose -f deploy/docker-compose.yml up -d

backend:
	cd backend && go run ./cmd/server

agent:
	cd agent && PYTHONPATH=src uv run python -m agent_service

frontend:
	cd frontend && npm run dev

test:
	cd backend && go test ./...
