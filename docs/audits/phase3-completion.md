# PulsePay chaos readiness completion

**Supported Phase 3 qualification: PASS. Phase 4 shadow-mode handoff: GO. Phase 4 read-only investigation mode: NO-GO until its isolated, bounded investigation executor exists.** No model, decision engine, autonomous recovery or new chaos operator was added.

This remediation and qualification follows the [original readiness audit](phase3-readiness.md). That audit remains an immutable record of the earlier NO-GO, rather than being rewritten as a pass. Work stayed on `feat/pulsepay-dashboard`, HEAD `ae620f81f1b91b8b57d4e7cfdf7900ba2614fa31`; changes are uncommitted. The operator authorized the remaining fixes and bounded synthetic-lab demonstrations. All tests and workload tools ran in Docker.

Evidence: [readiness-v1](../../artifacts/baseline/readiness-v1/README.md), including `manifest.json`, `gates.json`, commands, exact native runs, workload reports, restricted replay copies, evaluator labels and SHA-256 seals. The 27-gate matrix is **26 PASS, 1 SKIPPED_UNSUPPORTED, 0 FAIL, 0 BLOCKED, 0 NOT_RUN, 0 N/A**. The skipped gate is CPU pressure; seven distinct supported scenarios exceed the six-scenario catalog requirement and cover four effective fault mechanisms across API, worker, Redis and PostgreSQL.

## Fixes

- Observations now include source timestamps, completed producer-observation timestamps, freshness, missingness and quality. A fresh Prometheus scrape cannot turn a stalled worker's cached gauge into fresh evidence. Missing, stale, future-dated, non-finite or contradictory observations retain null/UNKNOWN.
- Stream undelivered count, pending message count, delivery idle age and outbox age have distinct names and units. `consumer_lag_seconds` remains null because no genuine undelivered-age measurement exists. Pending idle age samples the first 25 pending entries; it is not an asserted global maximum.
- A minimal non-root read-only observation service has only the sanitized volume and an isolated internal network. It contains two Python modules, no experiment catalog, runtime credentials, private evidence, control or Docker authority. Strict validation rejects private fields, contradictory freshness, oversized files and symlinks. Seventeen discovered-IP/host connection probes were denied. Operator Workbench/Grafana remain privileged operator interfaces, rather than investigator inputs.
- A separate evaluator bundle derives 19 historical labels from sealed source evidence, with hashes, field provenance and UNKNOWN for unavailable facts. All 447 files in the five original baselines, all 59 original audit files, and both original audit documents were rechecked unchanged.
- Preflight captures integrity before assembling its observation. A bounded eight-second wait permits a newly logged trace to reach Tempo's batched export; the same trace IDs/window must still produce real stored spans. It continues to reject unavailable telemetry.
- The optional proxy-control subnet now assigns both endpoints explicitly. This fixes the reproduced startup collision where the gateway occupied Toxiproxy's reserved address.

## Executed tests

| Suite / check | Actual result |
|---|---|
| Application, ledger, concurrency and recovery | **57 passed**, 16 optional checks skipped, 27.75 seconds |
| Workload contracts, retries, lifecycle and reporting | **66 passed**, 6.30 seconds |
| Final native framework, policy, watchdog, observations and evidence | **157 passed**, 30.28 seconds |
| Ruff / formatting / mypy | PASS; format/check commands passed; 91 runtime files type-checked |
| Workbench catalog/history/exposure contracts | **3 passed**, 3 optional live faults skipped, one idle-only case deselected |
| Final idle-load and PostgreSQL-selection browser checks | **2 passed**, 5 deselected, 5.68 seconds |
| Real Locust UI start/stop/restart and input guards | **1 passed**, 42.86 seconds |
| Final active-load metrics/logs/traces/dashboard gate | **1 passed**, 1.50 seconds; **62** real provisioned panel queries |
| Compose default and all overlays | Both exit 0 |
| Sanitized contract/replay evidence | **84 snapshots validated**, with no privileged fields |
| Credential and original-evidence preservation checks | PASS; sealed evidence retained |

Earlier failed attempts remain recorded. A combined suite initially used the wrong image and could not import YAML; it was rerun in the existing framework image. An idle-only Locust assertion initially ran while a headless workload was active; it was rerun after traffic ended. The proxy startup collision, insufficient post-warmup sample rejection and initial trace-export preflight rejection were reproduced and retained. They are not relabelled as passing runs. CPU capability detection applies no stress.

## Real scenario qualification

Each PASS below has a native Chaos Toolkit journal, successful injector result, independently observed impact, verified restoration, independent pre/post integrity PASS, a sealed complete normal-run bundle, and the same load still productive after recovery. No safety intervention stopped the workload in these eight runs.

| Scenario | Exposure | Run ID | Result |
|---|---:|---|---|
| API pause | 10 s | `chaos-20261011T173126Z-f0cfd929` | PASS |
| Worker pause | 20 s | `chaos-20261011T173244Z-4a48ffcd` | PASS |
| Redis outage | 15 s | `chaos-20261011T173405Z-bb98b14a` | PASS |
| API network delay | 15 s / 150 ms | `chaos-20261011T173544Z-173e7b3b` | PASS |
| PostgreSQL outage | 8 s | `chaos-20261011T174755Z-e8a0f1e2` | PASS |
| PostgreSQL proxy latency | 15 s / 150 ms | `chaos-20261011T174926Z-4f60f4c4` | PASS |
| Redis proxy partition | 15 s | `chaos-20261011T175051Z-26dc651c` | PASS |
| Identical Redis partition repeat | 15 s | `chaos-20261011T175250Z-2fba1d4e` | PASS |

API netem raised sampled HTTP p95 from **45.90 ms** to **4,678.28 ms**, returning to **35.18 ms** in the post-run sample. Database proxy latency raised it from **56.75 ms** to **4,596.35 ms**, returning to **25.76 ms**. These are sampled 30-second histogram windows, not equivalent to the configured 150 ms or precise recovery latency. The Redis partition repeat used the same profile/seed/users/routing/exposure and reproduced impairment and recovery; exact timings vary.

Financial image `sha256:80feb06f24c7c17b2f1cb91d9744e7ef7115c0b1e5684a1337b341140604db56` was unchanged throughout qualification. The first four direct-route runs used the earlier observation-fixed framework image; the later dependency runs and drills used the final image after the bounded trace-export/preflight-order fixes. Every native metadata file retains its actual image, revision and scenario hash. This is version-attributed qualification, not a claim that every run used an identical framework image or unchanged data volume.

## Watchdog, abort and boundaries

Runner SIGKILL drill `chaos-20261011T175436Z-6fed991d`: the selected worker was genuinely paused before killing only the named runner. The independent watchdog recorded `RUNNER_HEARTBEAT_LOST`; unpause occurred **15 seconds after interruption**. Result **ABORTED**, restoration RESTORED, post-integrity PASS. The native process was killed before it could emit a completed journal or final injector confirmation; its partial native execution log, injector state, gateway audit, watchdog trigger, restore report and integrity evidence are retained. It is not a passing experiment or invented completed journal.

Manual abort `chaos-20261011T175607Z-f4593d2a`: independent `OPERATOR_ABORT`, worker restored in **4 seconds**, native journal retained, result ABORTED, restoration RESTORED, integrity PASS. The summary conservatively records active-load productivity as unverified for this early-abort drill; it is not promoted to a sustained-load performance success.

A concurrent second experiment was refused before injection with the exclusive-lab-lease error. A protected Prometheus full container ID returned **403** and remained running/unpaused. Current safety tests also reject unsafe project/role/IDs, arbitrary commands, volume operations and privileged targeting. The only socket holder is the trusted local authorization gateway; Docker administrator control remains high privilege and is not represented as a sandbox for a hostile host operator.

## Workload and funds

The two 600-second recovery workloads generated genuine reads/transfers at a configured ceiling of 20 logical operations/sec, 20 users, seed 4217 and separate 30-second warmup. Achieved HTTP throughput was **19.410** and **19.745 RPS**. Their performance verdicts correctly remain **FAILED**, because deliberately injected faults caused 28 and 251 failed measured requests. Pre/post health recovered and all integrity checks passed. The proxy workload reconciled **64** initially ambiguous transfer intents using the same idempotency keys/payloads; final unknown outcomes were **zero**. Both HTTP/application counter comparisons passed their documented scrape-window tolerance.

Final healthy run `load-20261011T181909Z-ddf24259`: **PASS**, 120 measured seconds, 20 users, warmup 30 seconds, **20.175 achieved HTTP RPS**, **1,461 valid reads**, **934 distinct confirmed transfers**, zero failed measured requests, zero unresolved transfer outcomes, independent integrity PASS before and after. Actual p50/p95/p99 and UTC windows are in its retained summary. This is a functional recovery check on a growing dataset, not a fresh saturation or soak baseline.

Final independent verifier `3a83a4bf-f11c-4c6a-a870-32453f41fb64`, finished **2026-10-11T18:24:16.777915Z**, reports **PASS** across all 12 checks: **200 accounts**, **113,973 transfers**, **20,000,000 minor units** equal recorded provisioning, zero violations, pending outbox, overdue projection or quarantine. It uses REPEATABLE READ, READ ONLY. A separate safe unavailable-database fixture returned **UNKNOWN / exit 2** without interrupting the real database.

## Final state and limits

One Compose project, `chaosloop`, remains. Its **18** persistent services are running with **6,144 MiB / 10.75 CPU aggregate ceilings**. Core services, gateway, watchdog and observation reader are healthy. Locust is stopped, no experiment lease or fault helper is active, targets are unpaused, dependency clients use direct PostgreSQL/Redis routes, both proxies were restored enabled with no toxics, and optional Toxiproxy is stopped. No data volumes, branches or old reports were removed.

CPU pressure is **SKIPPED_UNSUPPORTED**, with actual `KERNEL_CGROUP_MEMBERSHIP_UNVERIFIED` evidence on this Docker Desktop cgroup-v2 backend. No uncontained fallback or host stress is enabled. Native Linux/Windows WSL2, a fresh clean-volume bootstrap and another full soak were not executed in this remediation; platform and historical results retain their original scope. The full 3–300 second exposure range is contract-tested, while live exposures above are the actually qualified values.

The API's best-effort exporter-delivery indicator remains UNKNOWN because it cannot attest to remote delivery. The independent live Loki/Tempo/Prometheus/Grafana gate supplied positive stored-delivery evidence. At idle, prior snapshots intentionally become STALE; no reader turns an old run into current healthy state.

Phase 3 supplies sanitized observations/replay and evaluator-only truth. The future read-only investigation executor, its authentication/query limits, audit log and model timeout/isolation remain Phase 4 work. Until they exist, use only the restricted observation feed or explicitly restricted offline replay for shadow consumers; do not grant access to operator Workbench, raw Prometheus, private evidence, Docker or the wider application network.

