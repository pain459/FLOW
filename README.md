# PulsePay — Synthetic Transaction Lab

Synthetic accounts and fake money only. PostgreSQL is the source of truth; an immutable double-entry ledger records transfers and explicit provisioning.

Prerequisites: Docker Engine/Desktop with Compose. No host Python, PostgreSQL or Redis required. Allow approximately 6 GiB of Docker VM memory for the complete lab. Run from this directory:

```sh
make bootstrap  # Generates private local .env, builds, initializes DB roles and migrates
make up         # Starts PulsePay, observability and idle Locust UI
make seed       # 200 deterministic accounts; ledger issuance, safe to repeat
make smoke
make verify     # Read-only snapshot; PASS=0, FAIL=1, UNKNOWN=2, DEGRADED=3
```

Dashboard: http://127.0.0.1:8080/. Locust: http://127.0.0.1:8089/ (idle until Start). API/OpenAPI: http://127.0.0.1:8080/docs. Grafana: http://127.0.0.1:3000 (`admin`, generated `GRAFANA_PASSWORD` in local `.env`). Prometheus: http://127.0.0.1:9090. Published ports bind to loopback; PostgreSQL, Redis and telemetry backends stay internal.

The [operator dashboard](docs/dashboard.md) connects directly to FastAPI. Overview shows real funds, transfers, an activity chart, asynchronous delivery and independent integrity checks. Accounts and Transfers expose ledger details and create/transfer dialogs. System explains each component and links to Grafana, Prometheus and OpenAPI. Missing or stale evidence is explicit; pending transfers retain their original idempotency key across tab reloads.

The API atomically commits balances, two ledger entries, a transfer and its outbox event. UUID-ordered row locks and unique idempotency keys handle concurrent retries. Redis summaries are non-authoritative. A leased relay publishes Redis Streams events; the consumer commits deduplicated receipts/projections before acknowledging. A separate SELECT-only verifier reconciles a consistent snapshot. Locust generates HTTP traffic only when started explicitly.

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
make test           # Disposable databases; never changes baseline financial data
make lint           # Ruff, formatting, mypy
make ui-test        # Real Chromium/HTTP workflows in Docker; isolated databases
make observe-test   # Real metrics/logs/traces and provisioned dashboard queries
make baseline       # Bounded workload qualification in a disposable project
make recovery-test  # Tests outages/restarts in this disposable lab
make status
make logs
make down           # Stop project; retain volumes
CONFIRM_RESET=chaosloop make reset-lab # DESTRUCTIVE: only this named lab's volumes
```

No automatic traffic client runs. Tune workload/seed/pool/TTL controls in `.env`. Keep `.env` private: bootstrap generates role-specific passwords at mode 0600 and never prints them. Changing an existing database's password requires updating its role as well as configuration. Existing labs must keep their recorded `SEED_VERSION` explicitly in `.env`; the new default is `pulsepay-v1`. A name change must never silently issue another seed's funds.

Controlled workloads are opt-in. `make load-preflight PROFILE=nominal`, `make load-smoke` and `make load-run PROFILE=write_heavy` issue real HTTP requests, independently verify integrity and export durable evidence. `make load-stop` cancels traffic without stopping PulsePay; `make load-report` shows the verdict. `make load-test` runs the isolated workload tests. The System page links to the provisioned Grafana **Load & Capacity** dashboard. See the [workload guide](docs/phase2-load-generator.md), [measurement methodology](docs/workload-methodology.md) and [acceptance evidence](docs/phase2-acceptance.md). `make load-qualify` uses a separately scoped disposable lab to repeat measurements from identical seed data.

Locust is part of normal `make up`: open **http://127.0.0.1:8089**, choose users/spawn rate and click Start. It stays available after Stop and is idle on startup. `make load-ui` ensures that service is running. `.env` settings `LOCUST_PROFILE`, `LOCUST_DURATION_SECONDS` (default 600), and `LOCUST_WARMUP_SECONDS` configure finite sessions. Manual sessions retain independent integrity checks but are not qualified headless benchmarks.

After an interruption, `make up` starts core services with existing volumes. Workers retry and reclaim pending messages. Use `make verify` before accepting recovery. No Docker socket, real payment integration, chaos operator or autonomous remediation is included.

Measured evidence: [Financial system acceptance](docs/phase1-acceptance.md), [baseline artifacts](artifacts/baseline/). Tested on macOS Docker Desktop/Linux arm64; native Linux/WSL2 remains unverified. This finite lab retains stream/quarantine evidence until an explicitly scoped reset.

Documentation: [architecture](docs/architecture.md), [data model](docs/data-model.md), [API contract](docs/api-contract.md), [invariants](docs/invariants.md), [observability](docs/observability.md), [operations](docs/operations.md).
