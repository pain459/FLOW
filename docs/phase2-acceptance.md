# PulsePay workload acceptance evidence

Current verdict: **PASS for the implemented, bounded on-demand workload system and qualified nominal reference**. The larger burst is a **FAILED capacity trial**, retained unchanged. Follow-up framework integration closed the full-hour soak, database lock/deadlock/query timing and generator network observation gaps; [current v3 evidence](../artifacts/baseline/workload-v3/README.md) contains the executed results. Unavailable host platforms remain unverified. Entries below preserve actual execution history and the limitations that applied to those historical images; this is not a claim that every starter workload fits this machine.

## Audit

2026-10-10: inspected existing API/schema, Compose services, metrics, seed commands, readonly verifier and dashboard contracts. [Integration inventory](phase2-integration-inventory.md) freezes assumptions. Current branch `feat/pulsepay-dashboard` is retained. Runtime phase labels will be replaced with PulsePay names; historical dataset identifiers are preserved.

Checkpoint outcomes, actual failed/passed commands, qualification measurements and remaining gaps are appended here during execution.

## Docker smoke and contracts

- RED: five missing-module contract tests failed. Strict YAML schema, internal target allowlist, deterministic distinct/funded pairs, canonical BIGINT intent and response classifier implemented; five tests passed in the pinned load image.
- Lifecycle/report RED: five absent-feature tests failed; exclusive file lock, bounded shaped schedule, atomic safe paths, pooled percentiles and warmup/UNKNOWN semantics implemented; ten tests passed.
- First real smoke stopped on sustained classified errors. Financial pre/post verifier both PASS. Found Locust's HttpSession copies user context before response classification; callback retained the initial contract_error. Real HTTP regression reproduced valid response misclassification, then passed after updating the response's event context. Unexpected read 422 was also reproduced as incorrectly accepted business rejection and corrected.
- Corrected `make load-smoke`: **PASS**, 120 measured seconds, **833 valid reads**, **362 confirmed logical transfers**, **10.0167 achieved HTTP RPS**; warmup excluded; zero unresolved outcomes. Independent pre/post PASS, backlog cooldown, activity pause/restore and durable CSV/JSON export succeeded. Failed and passing runs are retained under gitignored `artifacts/load-runs/` and the scoped reports volume.
- Initial sanitized Docker metadata template failed on services without a healthcheck. Replaced missing-field access with safe map lookup; manifests now retain their image/ceiling observations too.

## Workload profiles and workers

- Added smoke, low, nominal, read-heavy, write-heavy, burst, hot-account, step-ramp, soak, combined and journey/rejection profiles. Profile scaling preserves stage durations and caps shaped users explicitly. **15 load tests passed** including strict schema, deterministic selection, valid real HTTP classification, canonical retries, warmup separation, finite schedules, lock/path guards and every profile.
- `PROFILE=nominal DURATION=90 WARMUP=10 USERS=10 RATE=10 WORKERS=2 sh scripts/load-run.sh`: **PASS**, **534 valid reads**, **366 confirmed logical commits**, **10.1111 achieved HTTP RPS** over 90 measured seconds; independent pre/post PASS. Two worker evidence files aggregate actual samples; generated keys remain distinct and retries preserve identity.
- Added operator reservation before activity pause, plus controller file lock: a concurrent workflow cannot silently change a combined workload's activity. New-run and report lifecycle remain independent of core application startup.

## Regression, review and live instrumentation

- Docker backend regression: **53 passed, 8 skipped** (opt-in browser/observability tests excluded from this invocation). Docker Chromium UI suite: **7 passed**. Main lab smoke and independent verifier PASS after explicitly retaining its recorded legacy seed version in private configuration. Existing seed runs and balances were not renamed or reprovisioned.
- Real resource capture initially failed qualification: nominal run `load-20261010T123359Z-0487948f` was **INCOMPLETE**, with financial pre/post PASS. Docker's live statistics stream includes terminal ANSI prefixes; a regression reproduced the missing resource evidence, then passed after stripping those prefixes. Corrected short live run `load-20261010T124359Z-7f20ac11` PASS with fresh CPU/memory observations for every required service. The earlier failed observability gate and all partial runs remain retained.
- Final review reproduced two evidence bugs: absent manifests could qualify, and partial worker measurements could imply zero failures. RED tests failed; fixes require complete paired provenance and reconciled HTTP/outcome/latency counters. Missing failure evidence is null and cannot PASS. Latest containerized workload suite: **29 passed**; Ruff check/format passed.
- Live readonly Grafana validation during measured traffic: **31 queries across 20 Load & Capacity panels PASS**, including actual resource metrics, configured weights, throughput, latency, transfer outcomes, backlog and verifier age. This probe performed no financial writes.

## Optional manual Locust UI

- User-requested `make load-ui` exposes localhost:8089 only for explicitly selected manual sessions. Normal startup/headless runs do not publish that UI. Host allowlist, user/spawn caps, fixed user definitions, finite session timer and independent verification remain enforced.
- First timer trial exposed users stopping while the web process stayed alive; retained as failed evidence. Added a regression and shutdown of both runner and web server.
- Corrected live trial `load-20261010T133140Z-4e42acbc`: UI controls generated **100 measured HTTP requests**, **25 confirmed logical commits**, zero HTTP infrastructure failures/unknown transfers; independent pre/post **PASS**. Automatic web shutdown was observed. External target and 151-user requests were rejected. Report is deliberately **INCOMPLETE for benchmark qualification**, solely `MANUAL_UI_SESSION_NOT_A_QUALIFIED_BENCHMARK`; operator-controlled sessions are not repeated headless baselines.

## Qualification in progress

The separately scoped `chaosloop-load-baseline` project restores only its own supported-seed snapshot before each repetition. It does not change the main lab. Previous stopped/incomplete attempts are retained; only complete matching repetitions will qualify. Final run IDs, timings and median/range will be appended after execution, and this temporary deployment will then be stopped while retaining volumes/reports.

- Three individually PASS nominal runs (`load-20261010T133349Z-44b1c35a`, `load-20261010T133634Z-8fdac2a6`, `load-20261010T133919Z-ac6defd2`) were **not qualified**: repeated Docker builds produced different generator image IDs despite identical workload-source hashes. The comparison correctly rejected them. Qualification now builds once, pins a timestamped image for all runs, and never substitutes source equality for image equality. Their observed RPS/latencies remain unqualified measurements.
- Follow-up review reproduced missing allowlisted runtime configuration as a provenance gap. RED test failed, then API and applicable worker settings became mandatory. **30 workload tests passed** after that change. Actual earlier manifests already contained those settings; no historical evidence was filled in.
- `LOAD_REPORTS=/unwritable-reports` negative container invocation exited **1**, before any traffic, with safe `OSError` output rather than silently running without reports.
- Main lab live observability regression: **1 passed** (real HTTP/SQL spans, correlated API/relay/worker logs, Tempo causality and Grafana provisioning). Application Ruff/format/type checks passed.
- Excessive-user CLI validation (`--users 151`) exited **1** before traffic. A second operator workflow against an actively guarded qualified lab exited **1** on the existing named execution reservation, before pausing activity or creating another traffic generator.

### Qualified nominal baseline

Pinned-image invocation `20261010T134503Z`: **PASS**, three distinct comparable runs from identical initial seed volume. Independent pre/post PASS for each; 120 measured seconds after 30-second warmup, 20 users, pacing ceiling 20 logical ops/sec. Median/range: **20.2167 HTTP RPS (20.1750–20.2167)**, **p50 28 ms (27–30)**, **p95 50 ms (48–52)**, **p99 65 ms (63–67)**. See [baseline results](baseline-results.md) and [versioned qualification JSON](../artifacts/baseline/workload-v1/baseline.json). Remaining trials and final cleanup/regression are still pending at this entry.

## Current on-demand stack (supersedes earlier breathing/UI setup)

The user removed automatic breathing and requested Locust as an ordinary stack service. Deleted background activity code/service/settings/metrics/commands and `combined`. Kept the transaction-activity chart, which displays real financial records. `make up` now includes observability and a persistent Locust UI at localhost:8089, idle until Start. Headless profiles remain repeatable and share the exclusive traffic lock with UI sessions. No branch change.

Current executed evidence:

- Docker workload suite: **35 passed**, including report-budget refusal, disk-failure lock release/recovery, unsupported swarm arguments, safe targets, finite watchdog and UI persistence.
- Docker application regression: **52 passed, 9 skipped** in 24.97 seconds. Skips are explicit browser/live-observability/live-Locust opt-ins, run separately. One existing Starlette deprecation warning remains.
- Docker Chromium application suite: **7 passed** in 8.90 seconds. Locust link included.
- Live stack UI acceptance: **1 passed** in 37.71 seconds: idle produced no transfers, real requests/transfers after Start, Stop halted financial traffic while retaining UI, second session succeeded.
- Native Chromium Locust form: Start succeeded, finite 20-second measured/5-second warmup session automatically stopped, web UI remained available. Normal 600/30 settings restored afterward. Screenshot: `artifacts/dashboard/locust-stack-ui.png`.
- Current HTTP smoke **PASS**; independent read-only verifier **PASS** with zero financial/event violations. Ruff, formatting and mypy **PASS** (68 formatted files, 47 checked sources).
- Sanitized Compose resource audit: every service has a finite CPU/memory ceiling. Normal persistent stack including UI totals 5,248 MiB / 9.25 CPU ceilings. Headless plus helpers adds 928 MiB / 1.35 CPUs. See [resources](resources.md); disk admission is an explicit 512 MiB budget, not a portable volume quota.
- A concurrent invocation during UI traffic exited 1 on the execution lock. After UI stopped, `LOAD_REPORT_BUDGET_MIB=1` invocation exited **1** with `REPORT_STORAGE_BUDGET_EXCEEDED` before traffic, preserving historical reports.
- Current read-only Load & Capacity validation: **31 queries across 20 panels PASS** during measured traffic, with actual values.

The old qualified v1 nominal reference is retained as historical evidence; it predates these user-directed changes. Current images/profile hashes/resources are being requalified from the same disposable seed snapshot. No superseded measurement is presented as the current baseline.

Bootstrap/reset helper `docker run` invocations were capped too (128 MiB, 0.5 CPU, 32 processes, no network); they are local configuration/scope parsers, not application workload or benchmark processes. No reset was performed on the normal lab.

### Current qualified nominal reference v2

Invocation `20261010T142752Z`: **PASS**, three comparable distinct nominal runs on the on-demand stack, each 120 measured seconds after 30-second warmup, 20 users, logical pacing ceiling 20 ops/sec. Run IDs `load-20261010T142802Z-4e7c8c3c`, `load-20261010T143047Z-98732486`, `load-20261010T143332Z-08f6e69c`. Each independent pre/post verifier PASS; zero unresolved outcomes. Median/range: **20.2167 HTTP RPS (20.1750–20.2167)**, **p50 28 ms (28–28)**, **p95 50 ms (45–52)**, **p99 63 ms (58–69)**. Exact qualification key, profiles/images/settings and full evidence are retained under `artifacts/baseline/workload-v2/`. Additional profile trials and cleanup follow.

### Burst capacity finding

`load-20261010T144434Z-beb7778f` (20→60→20 users, uncapped closed-loop, 120 measured seconds plus 30 warmup): **FAILED**, **148.175 HTTP RPS**, **10,540 valid reads**, **7,089 confirmed transfers**. Financial checks passed; asynchronous delivery remained DEGRADED after the declared 180-second cooldown (`Backlog did not settle within cooldown`). The failed report is preserved; no resource limit or cooldown rule was loosened to mark it healthy. This pressure exceeds the configured event-delivery recovery envelope. Subsequent read-only recovery evidence and a smaller burst will be recorded separately.

Independent follow-up verifier after the saturated burst drained: **PASS** (`2026-10-10T14:52:05Z`), including delivery and all fund/ledger checks. The system recovered with its original resource ceilings. The separate failed burst report was not altered. A lower 20→30→20-user 60-second burst is being tested from the original disposable seed snapshot; duration/shape differences will remain explicit.

## Final current-configuration results

All commands below executed in Docker on this machine. Full manifests, exact verifier outputs, measured CSVs, phase events, and compressed raw evidence are retained in [workload-v2](../artifacts/baseline/workload-v2/README.md). The shortened tests are deliberately identified by their actual duration.

| Trial | Measured / warmup seconds | Achieved HTTP RPS | Valid reads / confirmed commits | Result |
|---|---:|---:|---:|---|
| Read-heavy, 50 users, logical ceiling 40/s | 120 / 30 | 39.5917 | 4,280 / 466 | PASS |
| Write-heavy, 50 users, logical ceiling 30/s | 120 / 30 | 30.3083 | 737 / 2,833 | PASS |
| Hot accounts, 50 users, logical ceiling 30/s | 120 / 30 | 30.1083 | 1,429 / 2,142 | PASS |
| Burst, 20→60→20 users, uncapped | 120 / 30 | 148.1750 | 10,540 / 7,089 | FAILED: cooldown backlog |
| Bounded burst, 20→30→20 users, uncapped | 60 / 30 | 120.4000 | 4,313 / 2,852 | PASS |
| Short step-ramp, capped at 40 users, logical ceiling 20/s | 30 / 5 | 20.1667 | 364 / 236 | PASS |
| Short soak functionality, 20 users, logical ceiling 10/s | 30 / 5 | 10.1000 | 179 / 121 | PASS |
| Journeys and deliberate rejections, 5 users, logical ceiling 5/s | 30 / 5 | 16.4333 | 316 / 124 | PASS |
| Two local workers, 10 users, logical ceiling 20/s | 30 / 5 | 20.2000 | 364 / 236 | PASS |

Each PASS trial has independent pre/post **PASS**, zero unresolved logical transfer outcomes, and drained event delivery. Nominal and the first four trials each restored the same disposable initial seed snapshot. The bounded burst and subsequent short trials shared a dataset that grew across runs; their manifests retain the actual before/after volume, and they are not nominal baseline repetitions. A journey performs several HTTP requests per offered logical operation. Burst durations differ, so these two observations do not establish a precise saturation knee.

- `make recovery-test`: **PASS**. Redis outage preserved committed transfers, pending stream messages recovered after worker restart, PostgreSQL outage returned readiness 503 and verifier UNKNOWN/exit 2, and restarted persistent stores retained state. Exact reports are under `workload-v2/evidence/`.
- `make observe-test`: **1 passed in 3.13 seconds**, with real HTTP/SQL spans and correlated API/relay/consumer logs.
- `make load-stop` during `load-20261010T153512Z-07e1739e`: controller **INTERRUPTED**, wrapper exit **130**, independent pre/post **PASS**. Partial evidence is retained and is not a successful benchmark.
- Final idle check: API ready 200, dependencies HEALTHY, Locust HTTP 200/state ready, and transfer count unchanged at **15,484** across five seconds. Final read-only verifier **PASS**, zero violations, at `2026-10-10T15:37:20Z`.
- Temporary project `chaosloop-load-baseline` stopped with Compose `down` **without `-v`**. Its reports/data volumes remain. `docker ps` showed only the main `chaosloop` services, including healthy Locust on localhost:8089; no activity or headless generator remains.
- Scoped reset guards: **3 passed** using fake Docker responses; the normal lab was never wiped. Read-only final code review found no remaining blocking issues after reproduced UI/report failure fixes.

### Acceptance boundaries

Contracts/determinism, real reads/writes and retries, profile scheduling/cancellation, evidence qualification, and application regression gates passed at the documented bounded scale. The qualified reference contains three distinct matching runs and measured median/range, not a fastest-run assertion. Fixed CPU/memory ceilings remain enabled throughout; the normal persistent stack including Locust totals **5,248 MiB / 9.25 CPUs** of configured ceilings, not measured consumption.

The 30-second soak proves execution/reporting only; the default hour-long soak was **not run**. The short step-ramp does not locate a saturation knee. PostgreSQL lock waits/slow queries/deadlocks and generator network throughput are observation gaps, explicitly retained in reports rather than invented. Inactive labeled error counters may also be absent from Prometheus; these are missing observations, not synthesized zeroes. WSL2 and native Linux were unavailable for separate validation. The clean disposable qualification startup exercised Docker bootstrap/migrations/seed on this Docker Desktop host; cross-platform portability is not claimed from that result.

No source commit, merge, new branch, release tag, chaos injection, or autonomous recovery was performed. Work remains on `feat/pulsepay-dashboard`. Future observation, immutable manifest, phase-event and independent stop contracts are documented in the workload guide.
