# Browser ↔ Go HTTP / SSE

Envelope: success `{ "data": ... }`, error `{ "error": { "code", "message" } }`.
Auth: `Authorization: Bearer <access_token>`. Tenant comes from JWT `tid` only.
IDs are public strings (`ten_`, `usr_`, `conv_`, `msg_`, `run_`).

Write `POST /v1/conversations` and `POST /v1/conversations/:id/messages` accept `Idempotency-Key`.
JSON `{ "content" }` still works. Multipart `content` (optional) + repeated `files` is the upload path.
Allowed: pdf, docx, txt, md, csv; 20MB each, 5 per message. Content and files cannot both be empty (empty conversation create with `{}` is still allowed).
Content length at most 32000. One active `queued|running` run per conversation (`409 conflict`).
Message objects may include `attachments: [{ id, filename, content_type, size }]`.

See the implementation plan for the full route table and event types.
