# Browser ↔ Go HTTP / SSE

Envelope: success `{ "data": ... }`, error `{ "error": { "code", "message" } }`.
Auth: `Authorization: Bearer <access_token>`. Tenant comes from JWT `tid` only.
IDs are public strings (`ten_`, `usr_`, `conv_`, `msg_`, `run_`).

Write `POST /v1/conversations` and `POST /v1/conversations/:id/messages` accept `Idempotency-Key`.
Content length 1–32000. One active `queued|running` run per conversation (`409 conflict`).

See the implementation plan for the full route table and event types.
