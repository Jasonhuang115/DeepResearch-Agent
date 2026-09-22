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
| `message.completed` | `content`, `truncated?` | insert assistant message. A `kind=subagent` run stores the event and does not insert a chat message. |
| `run.finished` | `status`, `error?` | update run. Clear `active_run_id` only when this run holds it. A subagent finish does not wake the main run. |
| `subagent.started` | `subagent_id`, `child_run_id`, `description`, `depth`, `parent_subagent_id?` | insert a `kind=subagent` run. Does not claim `active_run`. Grandchild events are emitted on the child run. |
| `error` | `message` | none |
| `source.added` | `source_id`, `url`, `title?` | none (store + forward) |
| `context.compacted` | `dropped_messages?`, `kept_messages?`, `tokens_before?` | none (store + forward) |

Agent must emit `message.completed` before `run.finished`, including cancel/fail (partial content).
Unknown types are stored and forwarded; clients ignore them.
