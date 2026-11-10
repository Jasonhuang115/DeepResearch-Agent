# HTTP API

All application endpoints use the `/v1` prefix. Protected endpoints require
`Authorization: Bearer <access_token>`.

```text
POST   /v1/auth/register
POST   /v1/auth/login
POST   /v1/auth/refresh
POST   /v1/auth/logout
GET    /v1/auth/me

GET    /v1/conversations
POST   /v1/conversations
GET    /v1/conversations/{conversation_id}
DELETE /v1/conversations/{conversation_id}

GET    /v1/conversations/{conversation_id}/messages
POST   /v1/conversations/{conversation_id}/messages
GET    /v1/attachments/{attachment_id}/download

GET    /v1/runs/{run_id}
POST   /v1/runs/{run_id}/cancel
GET    /v1/runs/{run_id}/events

GET    /health/live
GET    /health/ready
```

Message submission uses `multipart/form-data` fields `content` and `files[]`, plus an
`Idempotency-Key` header. It returns HTTP 202 with `run_id`, `message_id`, and `status`.

The Run events endpoint returns Server-Sent Events. The SSE `id` is the Run-local event sequence.
Clients reconnect with `Last-Event-ID`; the API replays missing events from MySQL before forwarding
Redis notifications.
