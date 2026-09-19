# Agent event types

Envelope on Kafka and SSE `data`:

```json
{
  "v": 1,
  "run_id": "run_…",
  "conversation_id": "conv_…",
  "tenant_id": "ten_…",
  "seq": 1,
  "type": "text_delta",
  "payload": {},
  "ts": "2026-09-19T03:46:02Z"
}
```

| type | payload | Go side effect |
|------|---------|----------------|
| `run.started` | `model?` | run → running |
| `run.progress` | `turn?`, `note?` | refresh last_event_at |
| `reasoning_delta` | `delta` | none |
| `text_delta` | `delta` | none |
| `tool_call.started` | `tool_call_id`, `name`, `args?` | none |
| `tool_call.finished` | `tool_call_id`, `ok`, `summary?` | none |
| `message.completed` | `content`, `truncated?` | insert assistant message |
| `run.finished` | `status`, `error?` | update run, clear active_run_id |
| `error` | `message` | none |

Agent must emit `message.completed` before `run.finished`, including cancel/fail (partial content).
Unknown types are stored and forwarded; clients ignore them.
