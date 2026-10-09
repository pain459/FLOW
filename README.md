# ChaosLoop — PulsePay Phase 1

Synthetic accounts and fake money only. PostgreSQL is the source of truth; an immutable double-entry ledger records transfers and explicit provisioning.

Prerequisites: Docker Engine/Desktop with Compose. No host Python, PostgreSQL or Redis required. Allow approximately 5 GiB of Docker VM memory for the complete lab. Run from this directory:

```sh
make bootstrap  # Generates private local .env, builds, initializes DB roles and migrates
make up         # Starts the core stack
make seed       # 200 deterministic accounts; ledger issuance, safe to repeat
make smoke
make verify     # Read-only snapshot; PASS=0, FAIL=1, UNKNOWN=2, DEGRADED=3
make breathe    # Enable 2 RPS HTTP activity, verifier and observability
```

API/OpenAPI: http://127.0.0.1:8080/docs. Grafana: http://127.0.0.1:3000 (`admin`, generated `GRAFANA_PASSWORD` in local `.env`). Prometheus: http://127.0.0.1:9090. Published ports bind to loopback; PostgreSQL, Redis and telemetry backends stay internal.

The API atomically commits balances, two ledger entries, a transfer and its outbox event. UUID-ordered row locks and unique idempotency keys handle concurrent retries. Redis summaries are non-authoritative. A leased relay publishes Redis Streams events; the consumer commits deduplicated receipts/projections before acknowledging. A separate SELECT-only verifier reconciles a consistent snapshot. The activity container only uses HTTP.

All business routes use `/api/v1`:

| Routes | Purpose |
|---|---|
| `POST /accounts`, `GET /accounts/{id}` | Create zero-balance accounts and inspect metadata |
| `GET /accounts/{id}/balance` | Authoritative PostgreSQL balance |
| `GET /accounts/{id}/transactions` | Bounded cursor-paginated ledger history |
| `GET /accounts/{id}/summary` | TTL-cached summary with freshness metadata and fallback |
| `POST /transfers`, `GET /transfers/{id}` | Atomic transfer with mandatory `Idempotency-Key`; replay returns original ID |

Operational routes: `/health/live`, `/health/ready`, `/health/dependencies`, `/metrics`. Redis failure degrades cache/events while core transfers stay ready. Database failure makes readiness return 503 and verification return UNKNOWN.

```sh
make stop-breathe   # Idle/verify mode; no background client writes
make test           # Disposable databases; never changes baseline financial data
make lint           # Ruff, formatting, mypy
make observe-test   # Real metrics/logs/traces and provisioned dashboard queries
make baseline       # 30-minute observer; requires make breathe first
make recovery-test  # Stops activity; tests outages/restarts in this disposable lab
make status
make logs
make down           # Stop project; retain volumes
CONFIRM_RESET=chaosloop make reset-lab # DESTRUCTIVE: only this named lab's volumes
```

Default configuration disables activity. `make breathe` explicitly enables the activity and observability profiles. Tune traffic/seed/pool/TTL controls in `.env`; total activity HTTP rate is capped at 5 RPS. Keep `.env` private: bootstrap generates role-specific passwords at mode 0600 and never prints them. Changing an existing database's password requires updating its role as well as configuration.

After an interruption, `make up` starts core services with existing volumes; `make breathe` also starts observability/activity. Workers retry and reclaim pending messages. Use `make verify` before accepting recovery. No Docker socket, real payment integration, chaos operator or autonomous remediation is included.

Measured evidence: [Phase 1 acceptance](docs/phase1-acceptance.md), [baseline artifacts](artifacts/baseline/). Tested on macOS Docker Desktop/Linux arm64; native Linux/WSL2 remains unverified. This finite lab retains stream/quarantine evidence until an explicitly scoped reset.

Documentation: [architecture](docs/architecture.md), [data model](docs/data-model.md), [API contract](docs/api-contract.md), [invariants](docs/invariants.md), [observability](docs/observability.md), [operations](docs/operations.md).
