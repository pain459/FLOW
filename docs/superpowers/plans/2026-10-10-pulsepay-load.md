# PulsePay workload integration plan

> Implement inline with superpowers:executing-plans and test-driven development. A fresh-context reviewer checks the full change at completion.

**Goal:** Integrate finite, observable, repeatable HTTP workloads and independently qualified healthy baselines into PulsePay on the current branch.
**Architecture:** Strict YAML profiles and deterministic HTTP account selection feed bounded Locust execution. A controller owns preflight, locking, lifecycle, resources, metrics, independent verification and immutable reports. Persistent Locust UI belongs to the normal stack; headless workloads are operator-selected. Automatic activity was removed by later user direction.
**Spec:** User's full workload specification plus `docs/phase2-integration-inventory.md`; naming correction treats all runtime components as one PulsePay application.

## Constraints and review focus

- Docker-only tools/tests; non-root, internal network, no socket/privileges/external targets. HTTP-only workload financial operations. Retain all existing routes/data and current branch.
- Unexpected HTTP schemas, ambiguous committed timeouts, unavailable/stale telemetry, mid-transfer cancellation and concurrent controllers cannot become successful baselines.
- Warmup is separate; target operation ceiling is not achieved HTTP RPS. Exact canonical keys/bodies persist during retries. Resource limits and raw evidence must support bottleneck claims.
- Baseline repetitions keep immutable workload, funded account set, image and limits; record growing ledger volume explicitly and reject comparison when dataset identity/funding/environment differs. Qualification uses bounded durations selected intentionally; starter durations remain available.

## Checkpoint 0 — Audit and freeze

- [x] Inspect real code/contracts/metrics/seed/runtime and write inventory before generator code.
- [x] Preserve current branch and existing committed dashboard; identify product naming cleanup and seed compatibility.

## Checkpoint A — Real Docker smoke

- [x] RED tests in Docker: strict profiles, target allowlist, deterministic pairs, canonical retry, response validation.
- [x] Implement `controller/schemas.py`, `clients/contracts.py`, `clients/pulsepay.py`, `workloads/account_pool.py`, `workloads/idempotency.py`, `locustfile.py`; pin dependencies and create opt-in Docker overlay.
- [x] Execute real smoke: at least 100 valid reads and 100 transfer commits, status lookups, exact independent pre/post PASS. Retain CSV/JSON evidence.

## Checkpoint B — Suite and lifecycle

- [x] RED tests: exclusive run lock, state transitions, cancellation, finite child timeout, same-key replay, response-loss ambiguity, depleted accounts, absent dependencies and unwritable reports.
- [x] Implement strict eight standard profiles plus low/combined; warmup, burst/step schedules, bounded pacing, contention, journeys and rejection tasks. Controller `preflight/run/stop/report/export` with durable state and partial reports.
- [x] Exercise normal completion and explicit mid-run stop; no generator traffic remains. Record/restores activity.

## Checkpoint C — Evidence and Grafana

- [x] RED reporting tests: null missing observations, warmup exclusion, comparable fingerprints, latency histograms, incomplete evidence; resource/Prometheus capture validation.
- [x] Implement measured counters/windows, manifests, summaries/CSV, exact verifier artifacts, redacted bounded errors and baseline comparisons. Add Load & Capacity Grafana dashboard and scrape target.
- [x] Verify actual data in every operational panel, server/generator HTTP agreement, image/config ceilings and generator resource observations. Document gaps honestly.

## Checkpoint D — Qualification

- [x] Freeze a bounded nominal qualification profile and execute three repetitions; report median/range and independent integrity.
- [x] Run read-heavy, write-heavy, burst, hot-account trials; report contention/capacity envelope and queue cooldown. Exercise configured step/soak safely without asserting unexecuted long-duration results.
- [x] Export all durable evidence; retain curated versioned baseline metadata while keeping runtime output gitignored. No source commit requested or created.

## Checkpoint E — Regression/documentation

- [x] Run full existing and load tests, browser/smoke/verification/live Grafana gates, optional-profile startup/stop and clean disposable Docker startup/migration/seed checks on available Docker Desktop host. Unavailable platforms remain unverified.
- [x] Remove runtime phase labels; preserve historical data/version identifiers and document compatibility. Update README and required workload/acceptance/methodology docs.
- [x] Fresh read-only final review; reproduce/fix material findings with regression evidence. Record PASS/FAIL/INCOMPLETE and platform limits; no future chaos code.

## Execution ledger

- Initial repository clean on `feat/pulsepay-dashboard` at `bdffebd`. User explicitly requested no new branch; native execution remains here.
- Ruling: architectural direction is already authorized by the detailed user specification; proceed with the audit and implementation plan without redundant design permission gates, following developer autonomy instructions.
- Ruling: multi-hour workloads require explicit CLI flag; qualification may shorten starter timings because the specification allows configurable scale/duration and sets no universal capacity target. Actual timing is retained in immutable profile snapshots.
- Ruling: replace runtime phase branding and default new seed label; never mutate existing seed-run identifiers, ledger or `.env` seed value behind the provisioning service.
- Added by user: an optional separate Locust UI. Implemented localhost-only manual controls with capped users/host, finite traffic/web shutdown and retained independent verification. Real manual UI trial passed integrity; it is intentionally ineligible for benchmark qualification.
- Qualification preserved failed/incomplete attempts; ANSI-prefixed Docker stats were fixed from reproduced evidence. Cached Docker rebuilds changed exact image IDs, correctly rejecting comparison. Final qualification builds once and pins one retained image for every repetition/trial.

## Latest user-directed scope

- [x] Remove automatic breathing/activity subsystem and combined profile, keeping actual transaction history/charts.
- [x] Make Locust an ordinary resource-capped persistent stack service: idle startup, real browser Start, Stop/finite expiry retain web UI, repeated sessions, shared lock with headless runs.
- [x] Tighten helper CPU/memory, process/tmpfs/report admission budgets; document whole-stack totals.
- [x] Focused read-only review; reproduce/fix reporting failures, abandoned pointers, unsafe swarm options and finite watchdog errors with tests.
- [x] Current Docker tests: 35 workload, 52 application, seven Chromium, one live Locust plus real native form, smoke/verifier/lint/type all pass.
- [x] Requalify current on-demand configuration; export reference/evidence and stop temporary second deployment without deleting volumes. Upper burst FAILED its cooldown; bounded reference PASS. Final main verifier PASS and persistent Locust idle/healthy.
