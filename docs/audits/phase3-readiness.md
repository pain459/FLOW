# Phase 3 readiness audit

**Verdict: Phase 3 does not satisfy every requirement. NO-GO for a certified Phase 4 shadow-mode handoff; NO-GO for Phase 4 read-only investigation mode.** The application and financial invariants are healthy. The remaining blockers are the observation contract, enforceable investigator/ground-truth separation, and completeness of the historical handoff evidence. Offline contract development against explicitly restricted fixtures is possible, but does not certify the live lab.

Audit `audit-20261011T161813Z-ae620f81`, 2026-10-11 UTC, branch `feat/pulsepay-dashboard`, HEAD `ae620f81f1b91b8b57d4e7cfdf7900ba2614fa31`. This is a verification audit, not remediation. Only audit documents/evidence were written; application/configuration/fault definitions and historical bundles were preserved. No new fault, data reset, service restart or Phase 4 implementation was authorized or performed.

## Results

The 27-gate matrix contains **15 PASS, 3 FAIL, 8 NOT_RUN, 1 SKIPPED_UNSUPPORTED, 0 BLOCKED and 0 N/A**. A historical success is attributed to its original run/image and does not replace a fresh live scenario. NOT_RUN entries below refer to new executions during this audit; their retained historical proof is recorded separately.

| Check | Current executed evidence |
|---|---|
| Both Compose configurations | Exit 0; default plus load/chaos/proxy overlays validate |
| Framework/native/safety suite | **113 passed**, 19.18 seconds |
| Application/ledger/concurrency/recovery suite | **56 passed, 16 optional live/browser checks skipped**, 26.44 seconds |
| Load contracts/lifecycle/reporting suite | **66 passed**, 5.20 seconds |
| Active-load metrics/logs/traces/dashboard gate | **1 passed**, 3.31 seconds; 62 provisioned panel queries and real correlated traces |
| First telemetry invocation after traffic ended | **FAIL**, 63.84 seconds: generator CPU series absent once the finite generator stopped; retained, not relabelled |
| Independent verifier before and after | **PASS / PASS**, zero violations; consistent read-only snapshots |
| Safe unavailable-verifier fixture | **UNKNOWN**, exit **2**; real DB untouched |
| Sealed historical evidence | Five root seals, **447 files**, hash checks pass; native JSON/run-ID/per-run seals checked |
| Two bounded nominal HTTP runs | Both **PASS**, zero failed measured HTTP/unknown transfer outcomes |

There were **236 passing automated checks** across the four successful test invocations, plus the separately retained failed telemetry invocation and 16 optional skips. Existing upstream deprecation warnings are retained. Tests used current repository source mounted read-only into containers. No fresh browser fault workflow or live rollback drill was attempted.

The unavailable metric was a test scheduling limitation: the first telemetry gate ran after the short load had finished. The same gate passed while the second controlled workload was active. Missing live data was not replaced with zero. This does not turn the failed first invocation into a PASS.

## Current financial and workload evidence

Verifier before: `5e7c1971-dedd-400d-84e8-2bf6f8ff32a6`, 16:19:35–16:19:36 UTC, 200 accounts / 100,537 transfers. Verifier after: `5752321f-8147-4436-85e0-d7fa391c1129`, 16:30:44 UTC, 200 accounts / 102,873 transfers. Both use REPEATABLE READ, READ ONLY, report **20,000,000 minor units** in balances and recorded provisioning, and find zero double-entry, account, idempotency, outbox, receipt or projection violations. Pending outbox, overdue projections and quarantine count are zero at these snapshots.

Both nominal executions used seed 4217, 20 users, 30-second warmup, 120 measured seconds and a 20 logical-operations/sec pacing ceiling. Profile hash `8b06d02b9ca6f954c1a9315f48006142a35dcd85087d1c1d0c752634612ef67e`. Each recorded 2,421 completed HTTP requests, 1,461 valid reads, 960 valid transfer submissions, 934 distinct confirmed transfers, 26 idempotent replay responses, zero business rejections and zero unknown outcomes. Separate pre/post integrity checks passed for each run. The load/app HTTP counter comparison passed its documented sampling tolerance.

| Run | Measured UTC window | Achieved HTTP RPS | Observed logical operations/sec | HTTP p50 / p95 / p99 |
|---|---|---:|---:|---:|
| `load-20261011T162156Z-f152cbae` | 16:22:28.885611–16:24:28.885611 | 20.175 | 19.9583 | 31 / 55 / 89 ms |
| `load-20261011T162713Z-aff5d67b` | 16:27:45.414713–16:29:45.414713 | 20.175 | 19.9583 | 33 / 59 / 72 ms |

These are two functional repetitions on a growing dataset, not a new identical-dataset capacity baseline, saturation qualification, or soak. Target HTTP RPS remains null because closed-loop logical pacing does not establish a prescribed HTTP arrival rate. Historical matching-image three-repeat nominal evidence and the older one-hour soak remain valid only for their recorded versions/data. No automatic background breathing client contaminated these runs.

The final inspected stack has 17 running persistent services, fixed 6,016 MiB / 10.5 CPU ceilings, healthy gateway/watchdog, no active experiment, and idle workload. Workbench correctly reports `LOAD_NOT_ACTIVE` after the audit's bounded traffic ends. No injector was left running by this audit.

## Gate matrix

| Gate | Status | Evidence / limitation |
|---|---|---|
| P3-01 Docker reproducibility | PASS | Both configs valid; fixed resources, isolated targets; no automatic fault job |
| P3-02 Funds safety | PASS | Applied schema 0002; independent pre/post snapshots and negative fixtures |
| P3-03 Load foundation | PASS | Two genuine read/write runs; separate warmup, offered logical work and achieved HTTP measurements |
| P3-04 Telemetry | PASS | Real HTTP/DB/events/resource samples, source timestamps, logs/traces and 62 dashboard queries; sanitized freshness gap scored H01 |
| P3-05 Native declarations | PASS | Eight native definitions; current framework suite validates schema/parameters/unsafe selection without injection |
| P3-06 Privilege/targets | PASS | Exact-label/full-ID gateway policy, protected targets, bounded helpers, negative tests; trusted socket gateway remains high privilege |
| P3-07 Watchdog | PASS | Independent healthy service/deadlines; current unit contracts and retained real kill/abort restoration evidence |
| P3-L01 API fault | NOT_RUN | No new injection authorized; historical effective pause PASS retained |
| P3-L02 Worker fault | NOT_RUN | Historical effective pause/repeat/60-second run PASS retained |
| P3-L03 Redis outage | NOT_RUN | Historical outage/restoration/ledger PASS retained |
| P3-L04 PostgreSQL outage | NOT_RUN | Historical bounded dependency-recovery runs PASS retained; ordinary nominal can safety-stop |
| P3-L05 Dependency latency | NOT_RUN | Historical API netem and PostgreSQL proxy-latency effects/restoration retained |
| P3-L06 Partition | NOT_RUN | Historical explicit Redis proxy partition PASS retained; proxy currently inactive |
| P3-L07 CPU pressure | SKIPPED_UNSUPPORTED | Recorded Docker Desktop cgroup-v2 OCI failure; no stress ran; catalog disabled |
| P3-L08 Negative control | PASS | Current policy/gateway tests and retained live protected/unknown-target 403 refusals |
| P3-S01 Runner interruption | NOT_RUN | No new kill drill; retained independent watchdog restored in 15 seconds |
| P3-S02 Manual abort | NOT_RUN | No new live abort; retained independent restoration in 4 seconds |
| P3-S03 Unsafe target | PASS | Current tests reject protected/wrong-project/wrong-role/full-ID violations |
| P3-S04 Double-run guard | PASS | Current exclusive-lease/concurrency contracts; retained live second-run refusal |
| P3-S05 Verifier unavailable | PASS | Safe localhost unavailable fixture returns UNKNOWN/2; no real outage |
| P3-S06 Stale/partial metrics | PASS | Current missing/stale observation contracts preserve nulls/gaps; H01 freshness export remains separate failure |
| P3-H01 Observation shape | FAIL | Missing data-freshness fields; outbox age mislabeled consumer lag |
| P3-H02 Privileged-label separation | FAIL | No enforceable investigator-only read boundary; raw operator artifact API and Prometheus expose fault truth |
| P3-H03 Read-only tool inventory | PASS | Existing sources/roles/bounds inventoried; reserved names are not a deployed isolated executor |
| P3-H04 Ground-truth quality | PASS | Retained injection intent/effect/restore compared; ineffective/unsupported attempts are not scored as successful faults; legacy completeness fails A01 |
| P3-H05 Load linkage | PASS | Real run/profile/hash crosswalks, UTC epochs, warmup and measured windows; image differences explicit |
| P3-A01 Evidence completeness | FAIL | Six older passing runs lack a distinct evaluator ground-truth artifact; legacy versions cannot be promoted to a complete current handoff |

Machine-readable records include the exact requirement, command/probe, expected/observed outcome, evidence, UTC review time, run linkage and limitations. Historical framework PASS/ABORTED/RESILIENCE_FAILURE/INCONCLUSIVE/INVALID are source run results, distinct from the audit gate taxonomy.

## Retained effective scenarios and safety drills

Review covered 23 sealed native records: **11 PASS, 2 ABORTED, 5 RESILIENCE_FAILURE, 1 INCONCLUSIVE, 4 INVALID**. Seven scenario IDs have successful historical effects, covering pause, container outage, latency and partition fault families across API, worker, Redis and database. No failing record was repaired or relabelled.

| Scenario | Representative retained run | Confirmed execution/effect |
|---|---|---|
| API pause | `chaos-20261010T173513Z-4f19fcaf` | Pumba/native action + availability impact + restoration + pre/post integrity PASS |
| Worker pause | `chaos-20261011T083533Z-f33045fd` | 60-second actual pause/unpause, peak backlog 447, catch-up under the same manual load, PASS |
| Redis outage | `chaos-20261010T174221Z-0caa7065` | Real outage/cache-event impairment; persisted source of truth and catch-up PASS |
| API network delay | `chaos-20261010T180303Z-0dc9e29e` | Actual netem/latency rise and owned cleanup, PASS |
| PostgreSQL latency | `chaos-20261010T181949Z-bdbd407d` | Explicit routed toxic, observed latency, cleanup and productive recovery, PASS |
| Redis partition | `chaos-20261010T182127Z-a368dc4b` | Explicit proxy interruption, impact, restored connection and productive load, PASS |
| PostgreSQL outage | `chaos-20261011T054327Z-0759842d` | Real 8-second outage, same active dependency-recovery load, independent PASS, zero final ambiguous outcomes |

Older archive runs reside in `artifacts/baseline/framework-v1/evidence/experiments.tar.gz`; newer runs in the exposure/gap-closure/workbench bundles. Root and per-run hashes were checked. Earlier summaries without an `injection_confirmed` boolean are assessed from native journal, injector output and actual metrics, not from an assumed missing-field default.

Runner SIGKILL run `chaos-20261010T174041Z-eb8faa38` was correctly **ABORTED**; independent heartbeat-loss restoration took 15 seconds, followed by verifier PASS. Its incomplete journal is explicit. Manual abort `chaos-20261010T182309Z-08c818c4` restored in 4 seconds and verified PASS; its sealed recovery-under-load classification is conservative and is not rewritten. Current tests cover failed evidence writes, non-renewable deadlines, repeated restoration, shared-lock refusal and watchdog independence. Live historical protected/unknown targets and broad image/volume operations returned 403.

The last operator job predates this audit: `chaos-20261011T161430Z-b47e7342`, a 60-second PostgreSQL outage manually aborted. Its Workbench job shows FAILED/exit 1, while the native summary is ABORTED with RESTORED and financial pre/post PASS, but recovery FAIL after ordinary nominal load stopped. This is not evidence of a successful sustained-load experiment. It is consistent with the documented nominal safety ceiling; the audit did not run or retry that fault.

## Remediation required before certification

1. **High — Complete the sanitized observation contract.** Export per-source freshness/last-scrape age and data-quality indicators into each snapshot and replay element. Preserve null/unknown and distinguish stale from fresh. Current raw collection has source metadata, but `snapshot()` drops it. Reproduction: inspect audit `observation-runtime-raw.json` versus `observation-runtime-sanitized.json` and `chaos/adapters/observations.py:68`.
2. **High — Correct the lag field's meaning.** `consumer_lag_seconds` currently uses `outbox_oldest_seconds` (`observations.py:105`). Export genuine worker/stream lag separately from outbox age, with provenance/missingness. This matters when the relay has published while the worker is paused. Do not infer no consumer backlog from an empty outbox.
3. **High — Enforce evaluator/investigator separation before connecting a model.** Read-only GETs from the ordinary internal network received HTTP 200 for `observation.json`, `ground-truth.json` and `metadata.json` with no authentication supplied. Raw Prometheus exposes scenario labels. Sanitized snapshot bodies contain no detected fault truth, and no model is connected, but privileged flags/file names do not enforce access control. Provide a restricted namespace/API/identity, query allowlist and file/network isolation; never give an investigator the operator Workbench or entire evidence volume. Required for both certified shadow inputs and read-only investigation mode.
4. **Medium — Qualify a complete versioned evaluator bundle.** Six earlier passing API/worker/Redis/netem/DB-latency records lack a standalone ground-truth artifact. Existing journals/metadata retain facts, but they are not a complete evaluator-only label package. Preserve old seals; produce a derived, provenance-linked evaluator index or authorized fresh runs on frozen images, with intent versus effect and UTC injection/restore boundaries. Do not backfill unsupported facts or replace failed attempts.
5. **Certification follow-up — Obtain approval for current-build live demonstrations/drills.** Eight live scenario/drill gates are NOT_RUN in this audit. Historical evidence supports the design but is versioned. Use a healthy bounded load, validate at least four supported families/API-worker-Redis-DB coverage and repeat effect direction, then interruption/abort drills and independent integrity. Proxy scenarios require deliberate routing activation. CPU is not an accepted equivalent; leave it unsupported unless actual kernel containment is proven.

For **Phase 4 read-only mode**, additionally implement a bounded, audited, isolated read-only investigation executor. Existing names/source inventory satisfy discovery only; no such consumer permission service exists. This is future work, not code this audit was authorized to add. No risk acceptance has been supplied for the failed handoff gates.

## Evidence and scope limits

Evidence root: `artifacts/audits/phase3/audit-20261011T161813Z-ae620f81/`. Includes manifest, full gate records, exact command log/exit codes, container/source fingerprints, redacted test output, aggregate load/verifier copies, historical evidence review, boundary probes, remediation backlog and checksum seal. Source/hash checks and final credential scanning are recorded separately. Original account-specific client-intent bodies were not copied into the audit package.

Discovery is in [phase3-discovery.md](phase3-discovery.md). This verdict does not claim clean-volume bootstrap, a new 30-minute breathing test, a new hour soak, Windows/WSL2 compatibility, current-build live fault success, or browser acceptance where those commands were not executed. Those remain historical, NOT_RUN or unsupported as explicitly recorded. The reliable financial core is demonstrated; full Phase 3/Phase 4 handoff certification remains open.
