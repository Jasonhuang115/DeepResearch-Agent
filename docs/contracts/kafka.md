# Go ↔ Agent Kafka

Topics:

- `research.run.commands` — Go produces, Agent consumes (group `agent`). Key = `conversation_id`.
- `research.run.events` — Agent produces, Go consumes twice: shared group `go-persist` (write once) and per-instance `go-sse-{instance_id}` (fan-out only).

Command types: `start`, `cancel`. Same topic so cancel reaches the instance holding the run.

Event `seq` is per-run, starting at 1, assigned by Agent. Go upserts on `(run_id, seq)`.
