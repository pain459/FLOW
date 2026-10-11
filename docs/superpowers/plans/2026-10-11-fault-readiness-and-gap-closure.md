# PulsePay fault readiness and gap closure implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Preserve the current branch and use one fresh final review.

**Goal:** Explain the rejected fault attempt and close verified application/workload gaps before later decision-model work.

**Architecture:** Retain native Chaos Toolkit, the restricted gateway and independent watchdog. Expose the existing workload precondition to the browser; persist client transfer intentions before HTTP submission and reconcile them over read-only HTTP after recovery. Kernel containment remains a fail-closed capability until it is directly proven.

**Tech stack:** Existing Docker Compose, Python, FastAPI, Locust, PostgreSQL, Chaos Toolkit/Pumba, Prometheus and Chromium tests.

**Spec:** User's framework specification and latest fault-error/gap-closure request; existing `docs/phase3-acceptance.md` supplies recorded findings.

## Constraints

- Use `feat/pulsepay-dashboard`; no new branch, commit, tag, push or destructive reset.
- Everything runs and is tested in Docker with finite resource limits.
- No safety-gate weakening, automatic load/fault startup, new chaos engine, broad Docker authority or volume deletion.
- Preserve sealed historical reports. Missing evidence stays UNKNOWN/INCOMPLETE.
- Workload financial operations use HTTP only; the independent read-only verifier remains authoritative.

## Review focus

- No active load or unfinished warmup: explain how to become ready without injecting.
- Timeout after a committed transfer: reconcile the original key/payload without another debit.
- Generator interruption or multiple workers: retain unique pending intentions and do not silently drop ambiguity.
- Unavailable or malformed lookup evidence: report UNKNOWN rather than infer a failed/committed transfer.
- CPU stress and database outage: keep exact target/resource restrictions and distinguish recovery under traffic from recovery after a safety stop.

## Task 1 — Workbench readiness and actionable diagnostics

Files: `chaos/preflight.py`, `chaos/cli.py`, `chaos/workbench.py`, `chaos/ui/*`, `chaos/tests/*`, `tests/ui/test_workbench_browser.py`.

- [x] Add failing tests for idle/warmup/stale/productive workload status and structured rejected-run diagnostics.
- [x] Run the focused Docker tests and record RED.
- [x] Share the existing workload gate between preflight and read-only UI status; preserve gate semantics. Include safe message and remediation in INVALID summaries and display historical failure evidence.
- [x] Run framework/browser checks and reproduce idle rejection with actionable output, then actual bounded worker pause under productive Locust load.

## Task 2 — Durable transfer-outcome reconciliation

Files: `apps/pulsepay/api/v1/transfers.py`, `apps/pulsepay/application/queries.py`, `load_generator/clients/*`, `load_generator/workloads/*`, controller/manual finalization and corresponding tests.

- [x] Test read-only idempotency lookup, timeout-after-commit and restart/pending-intent reconciliation; record failing Docker tests.
- [x] Add a compatible read-only lookup that verifies the original payload hash. Persist bounded immutable client intentions before submission and terminal evidence separately on the reports volume.
- [x] Reconcile outstanding intentions through HTTP after inflight completion, preserve UNKNOWN for unavailable/invalid evidence, and keep observed HTTP performance distinct from post-run reconciliation.
- [x] Test isolated financial invariants, distributed/manual/headless finalization and negative evidence paths in Docker.

## Task 3 — Safety capability and recovery qualification

Files: existing containment adapters/tests if direct proof is possible, acceptance/operations docs and a new sanitized evidence bundle.

- [x] Inspect actual kernel cgroup evidence without broader privilege; enable CPU faults only if parent/child containment is directly proven and tested. Otherwise retain disabled capability with a precise limitation.
- [x] Run conservative database interruption only under explicit opt-in and a documented bounded workload policy; record safety intervention and productive recovery separately.
- [x] Run full application/load/framework/browser regression, smoke and independent verifier; preserve actual failures and new results.
- [x] Obtain one fresh final review, fix important findings with reproducing tests, and update acceptance/operations documentation and remaining limitations.

## Progress and decisions

- Initial repository is clean at `680d097` on the existing branch; one `chaosloop` project has 17 persistent services.
- Failed run `chaos-20261011T035003Z-005d521b` is INVALID before injection: `Scenario requires existing active steady HTTP load`. Existing UI hides `failure.json.safe_message` behind its summary.
- Earlier findings: 51 ambiguous client outcomes during PostgreSQL outage; sustained-load recovery not demonstrated; CPU containment unproven. Native Linux/WSL2 unavailable and cannot be validated on this host.
- Implementation is already authorized by the latest user request. This ledger replaces redundant approval checkpoints; no commit/worktree steps are used.
- Task 1 code/framework tests and idle browser reproduction complete: 70 framework tests and one real browser regression PASS. Productive-fault demonstration is scheduled after rebuilding the workload client.
- Task 2 initial gates: 16 financial integration tests and 44 workload tests PASS. Durable intent precedes HTTP, read-only key/hash lookup is compatible, recovery retries retain identity, and measured HTTP counts are not inflated.
- CPU diagnostic: bounded idle helper failed before execution with OCI `cannot enter cgroupv2 ... with domain controllers -- it is in an invalid state`. No stressor ran. The API will be recreated from its fixed Compose limits to clear the daemon's failed cgroup setup; original volumes are retained.
- Ruling: qualify database recovery with a separate committed `dependency_recovery` workload, preserving default immediate UNKNOWN stop. Its explicit uncertainty deadline is 20 seconds after an UNKNOWN observation, corruption still stops immediately, and the existing 30% error ceiling uses a 60-second observation window. UNKNOWN samples remain recorded. An independent watcher enforces expiry while verifier communication waits; periodic verification and its communication timeout remain separate bounds. This is a deliberately selected workload policy, not a claim that default nominal traffic survives an outage.
- Live worker pause `chaos-20261011T051021Z-4c7c81a6`: Chromium Run workflow PASS, native journal PASS, restoration verified, both integrity snapshots PASS, existing load remained RUNNING throughout recovery.
- Live PostgreSQL outage `chaos-20261011T051149Z-4267a1dd`: PASS, eight-second scoped fault, independent restoration and integrity PASS under the same sustained load. The measured workload itself is correctly FAILED as a healthy benchmark: 211 infrastructure responses were recorded rather than hidden. All 51 measured ambiguous intentions were reconciled after recovery, without inflating the 2,813 measured commits. Original sealed reports remain unchanged.
- Fresh review identified five important corrections: sticky/independent uncertainty deadline; malformed journal records; total HTTP deadline/body ceiling; strict missing-transfer error validation; supported finalization wait budget. Reproducing Docker tests recorded RED (10 failed, 17 passed), then focused GREEN (28 passed). These fixes preserve strict default UNKNOWN behavior and permit no new fault or Docker authority.
- Final full gates: 56 application tests, 61 workload tests and 71 framework tests PASS; Ruff check/format PASS (135 files), expanded mypy PASS (88 runtime source files). The typed envelope/helper gaps received reproducing failures before correction. Live dashboard/Workbench/Locust and full metrics/logs/traces/Grafana checks PASS; native Compose overlays validate.
- Post-review PG repeat `chaos-20261011T054327Z-0759842d` PASS under sustained workload `load-20261011T054159Z-50866465`, full 180-second measurement and no control intervention. Workload benchmark correctly FAILED for 226 real HTTP infrastructure responses, but all 66 ambiguous measured intentions were reconciled and independent integrity passed.
- Separate final-image six-minute healthy functional check `load-20261011T053002Z-3ccb11ea` PASS: achieved 20.1 HTTP requests/sec, 2,869 measured commits, zero unknown outcomes and independent pre/post PASS. This does not replace matching-volume three-repeat performance qualification.
- Ruling after review: deadline expiry is permanent for that run, enforced by a separate headless thread/manual greenlet while verification communicates. Async cancellation bounds headers/body; 16 KiB response ceiling and complete error-schema validation authorize no malformed recovery write. Stop waits for a profile-derived finite finalization budget and never reports completion without the summary.
- Resource boundary remains unchanged; CPU unavailable after actual kernel rejection, native Linux/WSL2 unavailable, and sealed legacy ambiguity cannot be retroactively resolved. These are documented limits, not fabricated PASS. Temporary database opt-in is restored to false and traffic returns to idle before handoff.
- Final matching-volume/frozen-image qualification completed all three nominal repetitions: median 20.175 HTTP requests/sec, p50/p95/p99 26/47/57 ms, zero measured failures/unknown outcomes and independent pre/post PASS. The bounded 120-second measurements do not claim a new hour-long soak or saturation threshold.
- Qualification exited 0 and automatically stopped its temporary project, retaining data/reports. Final ordinary stack has 17 running services, 6,016 MiB / 10.5 CPU ceilings, idle Locust, healthy gateway/watchdog and no experiment lease. Independent final verifier PASS covers 83,579 transfers with zero violations/backlog. Historical checksum seals and evidence sanitization PASS; full reports and source/resource/health provenance are retained in the new bundle.
