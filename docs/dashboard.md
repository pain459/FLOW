# PulsePay operator dashboard

Open http://127.0.0.1:8080/ after `make up`. Use `make seed` for deterministic fake accounts. `make up` includes observability; Locust traffic starts only on demand. Missing verifier evidence is UNKNOWN. The dashboard runs in the existing non-root API image, with same-origin HTML, CSS and native JavaScript modules; no host Node, external scripts, frontend server or additional published port is needed.

## Views and behavior

- **Overview:** funds and provisioning totals, account and transfer counts, pending outbox age, actual per-minute committed transfers, latest transfers, independent checks and a clickable architecture diagram.
- **Accounts:** bounded reference search and cursor pages, authoritative metadata and paginated immutable ledger entries. Create account writes through the existing API and starts at zero balance.
- **Transfers:** cursor-paginated commits, source/destination references, event delivery state, exact debit/credit entries and request/event/trace correlation. Queued publication and pending processing are distinguished from committed financial state.
- **System:** API, PostgreSQL, Redis, relay, worker, on-demand Locust and verifier observations, reason codes, observation age and last progress where available. Links open Grafana, Prometheus and OpenAPI.

Overview SQL reads run in one REPEATABLE READ, READ ONLY snapshot. They are observations, not independent proofs of correctness. Verification comes exclusively from the separate SELECT-only verifier's report. Optional report URLs are fixed server configuration, never browser-supplied targets; intake has a two-second deadline, a 64 KiB bound and typed validation. Missing, malformed, contradictory or more-than-30-second-old evidence is UNKNOWN. Genuine UNKNOWN checks keep unavailable counts null and display a dash.

Polling occurs every ten seconds while visible, with no overlapping refresh. Pause and manual refresh controls are available. A failed database read retains the last values with an explicit stale banner; retained values cannot imply a fresh healthy snapshot. Dependency and verification freshness expires independently after thirty seconds. Paginated lists do not auto-reset after multiple pages have been loaded; manual refresh resets them.

All money in dashboard read models uses decimal strings, and JavaScript BigInt formats it. The transfer dialog accepts integer minor units up to PostgreSQL BIGINT, preserves exact JSON integer digits and never uses a cached balance to approve a transfer. Account references or UUIDs select source and destination; the directory is bounded to 1,000 suggestions and UUID input remains available.

Before sending a transfer, the browser saves and reads back its exact payload and generated idempotency key in sessionStorage. Submission is blocked if persistence fails. An interrupted or ambiguous response locks that intent for **Retry same transfer**; reload displays **Resolve pending transfer**. Replays return the original ID. Do not close the tab before resolving an uncertain outcome: sessionStorage belongs to that tab, and a fresh tab does not inherit its intent. Definitive validation/conflict responses are displayed with the safe error envelope. Inputs, returned references and errors render as escaped text. Native dialogs support keyboard focus and Escape.

## Dashboard read API

All routes below are under `/api/v1/dashboard` and have typed OpenAPI responses. Existing account/transfer write contracts are unchanged.

| GET route | Response |
|---|---|
| root | currency, snapshot timestamp, totals, thirty minute bins, twelve latest transfers |
| `/signals` | separately observed verification; missing evidence UNKNOWN |
| `/accounts` | items, next_cursor; limit 1–100, reference search up to 128 characters |
| `/accounts/{id}` | authoritative account metadata with string balance |
| `/accounts/{id}/ledger` | string-money ledger page; limit 1–100 |
| `/transfers` | transfer/event rows, next_cursor; limit 1–100 |
| `/transfers/{id}` | committed transfer, ledger pair and recorded correlation context |

List order uses timestamp and UUID tie-breakers. Cursors are bounded and validated. The dashboard provides no provisioning, destructive reset, chaos or remediation controls. This remains a loopback-bound synthetic lab without authentication.

## Browser gate and evidence

`make ui-test` builds the pinned official Playwright Python image with its matching browser package, runs Chromium against real Uvicorn HTTP endpoints and generated disposable databases, and retains output/screenshots in `artifacts/dashboard/`. Financial fixtures use the same isolation boundary as backend tests; the baseline lab's financial data is untouched. Browser report fixtures invoke real independent verification of each throwaway database while replacing only the optional report-fetch boundary.

The gate covers create/read/transfer/ledger, precision beyond JavaScript's safe integer range, lost committed response plus reload/retry, blocked writes when intent persistence fails, delayed account creation after changing dialogs, stale retained values/UNKNOWN evidence, HTML-like reference text, narrow layouts and keyboard focus. Standard `make test` skips browser cases; `make ui-test` executes them. See [acceptance evidence](phase1-acceptance.md) for actual results and platform limits. Browser images need extra disk space and memory; the runner has a 1 GiB limit and 256 MiB shared memory.
