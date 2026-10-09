# Phase 1 acceptance evidence

Status: **Local Phase 1 acceptance gates PASS on macOS Docker Desktop (Linux/arm64)**. Native Linux/WSL2 is unverified. No gate is assumed from container startup.

| Checkpoint | Status | Evidence |
|---|---|---|
| 0 Foundation | PASS | Docker build/migrations and repeated clean-source/empty-volume bootstrap passed |
| A Financial | Gate A tests pass | 18/18 tests, including 100 opposing transfers and 20 same-key requests; per-account SQL reconciliation passed |
| B Redis/events | PASS | TTL/fallback, duplicate publish, pending reclaim, quarantine, rollback-before-ACK; real Redis outage/drain and worker restart |
| C Observability | PASS | Real metrics/logs, HTTP/SQL/relay/consumer causal spans, 22 panel queries, provisioned dashboards/datasources and persistence |
| D Breathing/verifier | PASS | 1800.039 seconds, 3600 actual HTTP requests, 1396 transfers, zero client errors, 121 fresh PASS snapshots |
| E Hardening | PASS locally; unavailable platforms unverified | Final 46 tests, smoke, lint/types, verifier, live observability; scoped reset guard and clean isolated bootstrap |

Executed commands and measured results are appended at each checkpoint. Docker Desktop/WSL2 and other platforms are not claimed tested unless run.

## Checkpoint 0 — 2026-10-09

- RED: Docker pytest of foundation tests: 2 failures, missing modules as expected.
- `sh scripts/bootstrap.sh`: initial failure, Docker Desktop bind mount could not execute role init script; roles absent. Fixed by `Dockerfile.postgres` COPY with mode 0644. Ran role initialization in the empty lab cluster without deleting volumes.
- `docker compose build postgres`, `docker compose run --rm migrate`, `docker compose up -d api`, `docker compose run --rm tests`: exit 0; **2 passed**. Schema revision 0001.
- Pytest cache permissions warnings: will move cache to /tmp. One dependency deprecation warning, no test failure.

## Checkpoint A

- RED: 16 financial/concurrency tests failed against missing endpoints/services.
- `docker compose build api && docker compose run --rm migrate && docker compose up -d api && docker compose run --rm tests`: exit 0, **18 passed in 7.31s**.
- Migration 0002 applied. Tests cover exact two-entry/outbox atomicity; seed repeat; same-key replay/conflict; no-write rejection for funds, currency, inactive/missing accounts, bigint overflow, invalid amount/key; cursor history; ledger immutability and verifier privileges; forced outbox CHECK failure rollback.
- 20 simultaneous same-key HTTP calls: one created transfer, one logical debit; 100 opposing transfers: all committed and independent SQL account/global/transfer reconciliation had zero violations.

## Checkpoint B

- RED: 5 new cache/event tests failed for missing modules.
- Initial combined run: 5 failed / 18 passed. Root cause: test Redis client shared across isolated event loops. Fixed per-test dependency lifetime and namespace; baseline cache is not modified by tests.
- `docker compose run --rm -v "$PWD/tests:/app/tests:ro" tests`: **23 passed in 12.22s**.
- Actual Redis operations tested: duplicated XADD after simulated lost marker yields one projection/receipt; abandoned PEL recovered by XAUTOCLAIM; malformed message evidence committed before ACK; failed projection rolls receipt back and leaves PEL; unreachable Redis leaves outbox pending and later drains; cache TTL/fallback and post-commit invalidation do not affect financial state.
- Runtime relay/worker containers started. Full stop/restart scenarios will be executed in E.

## Checkpoint C

- Built instrumentation and started pinned Prometheus/Grafana/Loki/Tempo/OTel/Fluent Bit images.
- Regression suite **23 passed / 1 opt-in live test skipped**. Live test explicitly run separately.
- Initial live run failed on missing baseline seed; seeded 200 synthetic accounts. Next live run failed at Loki: Docker 29 omitted published ports for internal-only networks (inspect showed empty port bindings). Added edge network only for published services; DB/Redis remain internal.
- `docker compose run --rm -e OBSERVABILITY_TEST=true -v "$PWD/tests:/app/tests:ro" tests pytest -q tests/e2e/test_observability.py`: **1 passed in 1.10s**. Real transfer metrics, Loki request ID query, Tempo search and every provisioned Prometheus panel query returned data.
- Collector warns that metrics.address is deprecated at tested 0.123.0; works at this pin.
- Activity/verifier dashboards correctly show zero/UNKNOWN before those processes exist; they must be rechecked against D traffic. Causal SQL/worker trace assertions and persisted observability after restart remain E gates.

## Checkpoint D

- RED: 8 new verifier/activity tests failed for missing modules.
- `docker compose build api && docker compose run --rm tests`: **31 passed / 1 opt-in skipped in 15.55s**.
- Readonly consistent-snapshot checks passed during 30 concurrent transfers. Elevated corruption confined to throwaway test databases: imbalance, missing outbox, duplicate logical projection, invalid account status each produced FAIL. Unreachable DB produced UNKNOWN and exit-code mapping 2.
- `docker compose run --rm verifier python -m verifier.main --once`: PASS, 200 accounts, 20,000,000 issued/balance minor units, 2 committed transfers, 0 outbox pending, 0 overdue projections. Snapshot repeatable read/read only.
- Timed breathing observer records independent snapshots every 15 seconds and verifies actual HTTP request counters. Completion remains pending until 1800 seconds of evidence is saved.

### Completed breathing evidence

- The first short run was stopped after discovering an extra balance request before each transfer skewed the actual traffic mix. Its partial run is not accepted evidence. A failing wire-mix regression drove a paced HTTP client fix; the accepted run started afresh.
- `sh scripts/baseline.sh`: exit 0. [steady-state.json](../artifacts/baseline/steady-state.json) records **1800.039 seconds**, **121 fresh consistent-snapshot PASS reports**, **3600 HTTP requests**: 1396 transfers, 730 summaries, 753 history requests, 721 balances; zero client failures. Actual writes were 38.78% of requests at 2 RPS.
- All snapshots reconciled 200 accounts and **20,000,000 synthetic minor units**. No growing integrity violations or overdue delivery accumulated. Seed, before/after verification and dependency health JSON are retained alongside the timed report.
- Subsequent cache-payload, trace-log and metric-method hardening received regression/live checks; the timed run precedes these final small guards. No performance benchmark is claimed.

## Checkpoint E — executed 2026-10-09

- Read-only review found five defects: chunked body bounds, connection-refusal classification, per-entry provisioning reconciliation, durable-event validation and Linux bootstrap file ownership. Fixed all; financial/verifier/body/dependency cases have RED-to-GREEN tests. Further review found arbitrary HTTP method labels; reproduced three unbounded series, normalized unknown methods to `OTHER`, regression passed.
- Malformed Redis JSON array reproduced a summary HTTP 500. Typed cache validation now bypasses invalid payloads and serves PostgreSQL; regression passed.
- Stronger trace gate initially found an empty trace ID on outer HTTP completion logs. The server-request hook captures the span ID in ASGI scope; correlated logs and cross-process causal span assertions now pass.
- `make test`: **46 passed, 1 opt-in skipped, 1 dependency deprecation warning, 21.11s**. Includes concurrent same-key races across both shared and disjoint account pairs, opposing transfers, atomic rollback, forged events, readonly verification and negative fixtures. The opt-in live test was explicitly executed separately.
- `make lint`: Ruff check PASS; **64 files formatted**; mypy **46 source files PASS**. First normal-image lint failed on an unwritable `/app` cache; tool caches now use `/tmp`, and the same command passed without source mounts.
- `make smoke`, `make verify`: exit 0 / PASS. `make observe-test`: **1 passed in 3.20s**. The strengthened live test verifies API/relay/worker request IDs, HTTP and PostgreSQL spans, relay trace continuity, worker causal links, three provisioned datasources, five provisioned dashboards and 22 real PromQL panel queries. [observability.json](../artifacts/baseline/observability.json) retains safe sample trace IDs.
- `sh scripts/recovery-test.sh`: exit 0. Real stopped Redis: transfer commits, core readiness remains 200, cache degrades, outbox remains pending. Restart drains events; same-key retry returns 200. Stopped worker: abandoned delivery enters PEL; restart reclaims it and projections reconcile. Stopped PostgreSQL: liveness 200, readiness and balance 503, verifier UNKNOWN; one-off verifier exit **2**. DB restore returns PASS.
- Restarted API, relay, worker, Redis, Prometheus, Grafana, Loki and Tempo: transfer still exists, historical Prometheus value unchanged, stored trace readable, request log searchable and Grafana healthy. Per-stage JSON evidence is retained under `artifacts/baseline/recovery-*`.
- Repeated fresh source-copy bootstrap with separate `chaosloop-bootstrap-check` project, empty named volumes and port 18080: generated private configuration, built images, initialized roles, migrated, `docker compose up --build -d`, seeded, smoke and readonly verifier all PASS. Removed only that disposable project's volumes. Normal lab was retained. Final run uses digest-pinned infrastructure/base images.
- Reset guard tests: no acknowledgement refuses; wrong project refuses; exact acknowledgement/project invokes only project-scoped `down --volumes --remove-orphans`; no prune. The baseline lab itself was not wiped.
- Runtime Python services run as UID 10001; no host Docker socket mounts, no external PostgreSQL/Redis bindings. Runtime/migrator/verifier roles are distinct; ledger mutation and verifier write privilege tests pass. Local secrets remain ignored, mode 0600. Diagnostic credential representations were redacted and affected local credentials rotated.

## Readiness and limits

**Ready for Phase 2 on the tested local platform.** Continuous HTTP breathing, durable financial/event state, independent correctness checks and operational signals have measured evidence. Native Linux and WSL2 were unavailable; their bootstrap/runtime tests are not claimed. The UID ownership fix is reviewed, not a native-Linux execution claim.

- Telemetry is best effort with bounded buffers; it does not control money commits. One Starlette/AnyIO deprecation warning remains. The collector's pinned metrics setting is deprecated but functional.
- Full ledger scans are appropriate for this finite lab, not a high-volume scalability guarantee. Streams/quarantine persist until scoped reset; deleting Redis persistence is outside the retained-volume restart guarantee. No manual replay tool is supplied.
- Grafana provisioning and live data queries were checked through APIs; no visual browser audit was executed. No real authentication/payments, high-volume generator, chaos operator, decision maker, approximator or autonomous recovery was built.
- The baseline files contain synthetic IDs and measured reports only. Checkpoint descriptions above preserve actual failures and fixes; historical pending notes document the sequence rather than current unresolved gates.
