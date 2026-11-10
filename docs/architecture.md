# Architecture

## Runtime

```text
React -> FastAPI -> MySQL
                  -> Redis
                  -> Aliyun OSS

MySQL -> Research Worker -> E2B / LLM / Search
Research Worker -> MySQL events -> Redis Pub/Sub -> FastAPI SSE -> React
```

FastAPI and the Research Worker use one Python codebase and run as separate processes. MySQL is
the durable source of truth. Redis contains only expiring or reconstructable state.

## Database

```text
users
  -> conversations
       -> runs
            -> messages -> attachments
            -> run_events
```

All IDs are 26-character ULIDs. Ownership is resolved through `conversations.user_id`; child tables
do not duplicate user or conversation ownership fields.

## Run execution

1. The API locks the conversation and creates a queued Run with its user message.
2. A Worker claims the Run using `FOR UPDATE SKIP LOCKED`.
3. The Worker increments `attempt_count` and sets a 30-second lease.
4. Every Worker write verifies attempt count and lease expiry.
5. Committed events are published to Redis; MySQL remains the replay source.
6. An expired first attempt is queued once more and restored from `checkpoint.json`.
7. A second expired attempt becomes failed.

## Storage

```text
users/{user_id}/conversations/{conversation_id}/
  attachments/{attachment_id}
  runs/{run_id}/
    sources/
    notes/
    tool-output/
    report.md
    checkpoint.json
```

Production uses Aliyun OSS and E2B. Local development uses filesystem object storage and a local
workspace only when explicitly configured.

## Events

Persisted event types are `run.started`, `run.progress`, `text.delta`, `tool.started`,
`tool.finished`, `source.added`, `subtask.started`, `subtask.finished`, `checkpoint.saved`,
`message.completed`, `run.finished`, and `error`. Raw model reasoning is not persisted.
