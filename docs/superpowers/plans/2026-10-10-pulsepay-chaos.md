# PulsePay framework chaos implementation plan

> Execute inline using executing-plans, test-driven-development and final independent review. Preserve existing branch/workspace; no commit, tag, merge or push unless requested.

**Goal:** Framework-native real faults, bounded independent restoration and auditable recovery under sustained HTTP traffic, plus closure of prior measurement/soak gaps.
**Architecture:** Chaos Toolkit YAML invokes narrow Python adapters to pinned Pumba jobs and optional Toxiproxy. A Docker authorization proxy filters exact label-allowed targets and tightly constrained helper creation. An independent watchdog restores a frozen pre-state lease. Existing load controller/verifier/Prometheus remain authoritative.
**Spec:** User's full framework-based chaos specification, refined by `docs/phase3-discovery.md`.

## Global constraints and review focus

- Docker-only, non-root app/runner, finite CPU/memory/disk/report budgets; opt-in chaos startup. No Laya/custom operator/scheduler/scenario language.
- Native Toolkit owns sequencing; wrappers only preflight/arm/framework invocation/evidence export. No arbitrary shell/URL/regex/container/image arguments from operators.
- Socket access exists only in authorization gateway; default deny volume/image/network/daemon mutation. Helper mounts/caps/namespaces are exact allowlisted; no host stress, privileged/PID/host network.
- Preserve active load; correlate its run and epochs, do not disguise safety-stop interventions. Keep ground truth outside sanitized observations.
- Crash between injector start and confirmation, stale/replaced target IDs, expired leases, gateway/watchdog restart, blocked postflight and disk/report failures must fail closed and retain partial evidence.

## Tasks / persistent execution ledger

### A0 — Discovery and prior gaps

- [x] Audit actual contracts, labels, health, profiles, verifier and existing limits; write discovery before source changes.
- [x] RED tests for read-only DB statistics, absent-data semantics and Linux network parsing; implemented isolated monitor/config and exporter, generator network metrics and controlled zero-label initialization. Final financial regression 55 PASS; load tests 36 PASS; formatting/type checks PASS.
- [x] Built/runs Docker; actual new DB/network metrics observed. Full-hour run `load-20261010T161333Z-974fd66b` PASS, 3,600 measured seconds, independent pre/post PASS. Three current-monitoring nominal repeats PASS, curated at `artifacts/baseline/workload-v3`; temporary project stopped retaining volumes.

### A1 — Framework bootstrap and authorization

- [x] Pinned tested Toolkit/Pumba/Toxiproxy/helper images and locked Python adapter dependencies. RED safety tests cover labels/full IDs, namespaces/caps, command bounds, default-deny endpoints, lease ownership and forged runner state. Missing greenlet fixed from actual Docker traceback.
- [x] Added chaos-only overlay/security gateway, private authorization volume and authenticated watchdog listener; non-root runner, independent watchdog and explicit resource limits. Implemented native validation, preflight and Pumba dry targeting.
- [x] Actual Docker config, all eight native validations, pinned framework/Pumba help, isolated namespace capability and 31/31 safety tests PASS. No-fault live worker preflight `chaos-20261010T173049Z-6748caa5` PASS, exact frozen container ID, zero injection. Earlier warmup-only preflight refused as INVALID, retained.

### B — First real native experiments

- [x] Create 001 API pause and 002 worker pause with native hypothesis/method/rollbacks and bounded configuration. Rollback/evidence/redaction tests PASS.
- [x] Implement thin observations/health/verifier/injector/evidence adapters and watchdog restoration. Exposure is separate from strict recovery. Final expanded native/safety/rollback/evidence suite: 56 PASS.
- [x] API/worker runs PASS under nominal load; worker repeat reproduced backlog growth/catch-up. SIGKILL restoration 15 seconds, explicit abort 4 seconds; both safety tests PASS and experiments ABORTED. Invalid targets/concurrent lease refused live.

### C — Dependency and resource library

- [x] Redis outage and real API netem qualify PASS; explicitly opted-in PostgreSQL outage restores financial integrity but exposes workload safety-stop/51 client unknown outcomes, retained as RESILIENCE_FAILURE. CPU native definition exists but is refused on every backend; kernel containment remains unproven and no stress was injected.
- [x] Explicit Toxiproxy connectivity tested first; DB latency and Redis partition qualify PASS. Private administrative network inaccessible to runner, owned toxic/proxy restoration verified.
- [x] Six distinct scenarios qualify under continuous load; one worker repeat. Original failed/invalid attempts, framework journals, signals and independent restore/integrity evidence preserved.

### D — Evaluation, regression and handoff

- [x] Exact metadata/images/scenario hashes, baseline/load links, journals/timelines, before/during/after signals, verifications and reports exported. Sanitized contract excludes ground truth. Existing seals verified; older runs missing standalone truth/journal fields remain explicit.
- [x] Final checks: framework 56, application 55, workload 36, browser 7, live Locust UI 1 and live observability 1 PASS. All eight native YAMLs validate. Actual 62 Grafana panel queries and correlated metrics/logs/traces verified during bounded run `load-20261010T184109Z-67498a30` PASS.
- [x] Full-hour soak and three comparable nominal repeats PASS, evidence in workload-v3. Framework-v1 preserves full experiments/load bundles and check logs. Qualification cleanup corrected to stop monitoring profiles too; one normal direct-routed idle stack remains, control services stopped and volumes retained.
- [x] Independent final safety review completed; reproduced blockers fixed/tested. Acceptance report updated: overall INCOMPLETE for CPU containment and PostgreSQL sustained-load/client-outcome finding. macOS Docker Desktop only; native Linux/WSL2 untested. No false catalog PASS or performance equivalence claim.

### Rulings

- User already supplied architectural intent, exact framework choices and execution directive. Implement authorized concrete design without redundant skill approval gates. Same branch and existing changes preserved; no worktree/new branch.
- Gateway is strictly a Docker API authorization boundary, and watchdog only restores a bounded lease. Toolkit remains the sole experiment engine; no independent generic scheduler or second YAML format.
- Previous burst failure remains unchanged. New instrumentation changes resource/image fingerprints, so new measurements cannot reuse the old reference as a comparable baseline.
- Only the available Docker Desktop Linux VM can be tested here. Never relabel its tests as native Linux or WSL2; provide an exact rerun matrix if those environments remain unavailable.
- Gateway never writes through runner-owned mailboxes: private authority/audits prevent symlink attacks. CPU stress requires actual kernel parent-resource accounting proof; a driver name alone cannot authorize it.
- Concurrent helper removal is accepted only after Docker confirms that the exact owned helper is absent; regression reproduced MANUAL_ACK_REQUIRED then passed after correction. Final verdicts and later recovery reports preserve original checksums.
