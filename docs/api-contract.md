# HTTP API contract

OpenAPI and schemas: http://127.0.0.1:8080/docs. JSON request bodies are limited to 16 KiB by counting actual bytes, including chunked bodies. Account external references and idempotency keys are bounded ASCII identifiers; history is at most 100 records per response. Connection concurrency, DB pools, statements and requests are bounded.

| Method | Route | Result |
|---|---|---|
| POST | `/api/v1/accounts` | Zero-balance account, 201 |
| GET | `/api/v1/accounts/{id}` | Metadata and current stored balance |
| GET | `/api/v1/accounts/{id}/balance` | Authoritative PostgreSQL balance |
| GET | `/api/v1/accounts/{id}/transactions?limit=50&cursor=...` | Ledger history, descending timestamp/UUID cursor |
| GET | `/api/v1/accounts/{id}/summary` | Non-authoritative TTL summary with freshness/cache metadata |
| POST | `/api/v1/transfers` | 201 committed, 200 idempotent replay |
| GET | `/api/v1/transfers/{id}` | Committed transfer |
| GET | `/health/live` | Process only, 200 |
| GET | `/health/ready` | PostgreSQL/schema ready: 200 or 503 |
| GET | `/health/dependencies` | Per-dependency states/freshness, core readiness |
| GET | `/metrics` | Prometheus exposition |

```http
POST /api/v1/transfers
Idempotency-Key: demo-transfer-001
X-Request-ID: demo-request-001
Content-Type: application/json

{"source_account_id":"<uuid>","destination_account_id":"<uuid>","amount_minor":10000,"currency":"INR"}
```

Transfer results include `id`, source/destination IDs, amount, currency, `committed` status, committed timestamp, and request ID. Mandatory `Idempotency-Key` is 1–128 ASCII identifier characters. Only committed successes reserve keys; rejected requests can be retried after conditions change. Use the same key and exact payload after network/HTTP timeouts, including when a commit may have succeeded before the connection failed.

Error envelope: `code`, safe `message`, `request_id` (optional safe details reserved). Account absence 404 `ACCOUNT_NOT_FOUND`; inactive account 409 `ACCOUNT_INACTIVE`; insufficient funds 422 `INSUFFICIENT_FUNDS` (syntactically valid request cannot be executed); invalid amount/currency/cursor 422 `INVALID_TRANSFER`; reused key/different payload 409 `IDEMPOTENCY_CONFLICT`; DB unavailability 503 `DATABASE_UNAVAILABLE`; internal constraint/implementation failure 500 `INTERNAL_ERROR`. Duplicate account references are 409 `ACCOUNT_EXISTS`; missing transfers are 404 `TRANSFER_NOT_FOUND`. Oversize requests are 413. Validation responses do not echo supplied input or database exceptions.

`X-Request-ID` is accepted if safe and at most 64 characters, otherwise regenerated. W3C `traceparent` propagation is independent. Summary exposes `authoritative:false`, `source_updated_at`, `cached_at`, `max_staleness_seconds`, `cache_hit`, `cache_status`. Redis failure bypasses cache and returns a PostgreSQL-backed summary marked DEGRADED; transfers do not depend on cached balances.

Provisioning is available only through the container seed job. Authentication and real financial integrations are outside this synthetic lab's scope; bind the operator ports only to loopback.
