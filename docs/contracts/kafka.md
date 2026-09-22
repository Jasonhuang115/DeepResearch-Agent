# Go ↔ Agent Kafka

Topics:

- `research.run.commands` — Go produces, Agent consumes (group `agent`). Key = `conversation_id`.
- `research.run.events` — Agent produces, Go consumes twice: shared group `go-persist` (write once) and per-instance `go-sse-{instance_id}` (fan-out only).
- `research.subagent.wakes` — Agent produces, Go consumes (group `go-subagent-wakes`). Key = `conversation_id`.

Command types: `start`, `cancel`. Same topic so cancel reaches the instance holding the run.

A subagent wake is one JSON object: `v`, `conversation_id`, `tenant_id`, `user_id`, `id`, `status`, `report_path`. Go may coalesce several wakes for one conversation into a single `start`. That `start` has an empty `request.content` (no user message row) and `wake.reports[]` of `{id, status, report_path}`. The agent puts those paths in the system context for the main run.

`start.request` may include `attachments[]` with `id`, `filename`, `content_type`, `path` (absolute file on the shared upload dir), `size`. Bytes stay off Kafka.

Event `seq` is per-run, starting at 1, assigned by Agent. Go upserts on `(run_id, seq)`.
