# PulsePay healthy workload references

Current monitoring reference **v3: PASS**. Three identical nominal repetitions measured median 20.175 HTTP requests/s, p50/p95/p99 26/48/63 ms, with independent pre/post PASS. The full-hour main-lab soak also passed: 3,600 measured seconds, 43,218 valid reads, 28,687 confirmed transfers, unknown outcomes 0, p95 84 ms. Database lock/deadlock/query timings and generator network counters are now observed. See [workload-v3 evidence and comparison limits](../artifacts/baseline/workload-v3/README.md). The prior references and failures below remain historical; their absent instrumentation and short-soak limitations are not claims about the current image.

Current on-demand reference **v2: PASS**. Three 120-second nominal measurements after 30-second warmups, 20 users, 20 logical ops/sec ceiling: median achieved HTTP **20.2167 RPS** (20.1750–20.2167), p50 **28 ms** (28–28), p95 **50 ms** (45–52), p99 **63 ms** (58–69). Financial integrity passed before and after every run. Normal Locust UI was idle; automatic breathing was removed. Exact matching manifests, summaries, verification and full compressed evidence are in [workload-v2](../artifacts/baseline/workload-v2/README.md).

## Current capacity observations

Read-heavy, write-heavy and hot-account 120-second trials passed at **39.5917**, **30.3083**, and **30.1083 HTTP RPS**, respectively. All returned independent pre/post PASS and drained their asynchronous work. A 60-second, 20→30→20-user burst passed at **120.4 HTTP RPS**. A longer 120-second, 20→60→20-user burst achieved **148.175 HTTP RPS** but **FAILED** its 180-second event-backlog cooldown. Financial checks passed; later independent verification confirmed delivery recovery. Its failed verdict remains unchanged.

These observations bound the tested recovery behavior; different duration and shape prevent a precise capacity threshold. Nominal is the qualified healthy reference, not the upper burst. Short step-ramp, soak functionality, journey/rejection and two-worker trials passed too. Exact counts, timings, limits, resource peaks and missing signals are in [measured-results.json](../artifacts/baseline/workload-v2/measured-results.json) and the [final acceptance table](phase2-acceptance.md#final-current-configuration-results). No hour-scale stability or universal throughput claim is made.

Current qualification used pinned generator `pulsepay-load:qualified-20261010T142752Z`, identical initial seed snapshots, and the unchanged fixed resource ceilings documented in [resources](resources.md). The main lab remained idle on the shared Docker VM during nominal qualification. Temporary qualification services have been stopped without deleting volumes; the normal stack and idle Locust UI remain running.

## Historical reference v1

This reference is historical: it predates removal of the automatic activity client. Current on-demand configuration must be qualified separately.

Measured on 2026-10-10 with Docker Desktop Linux arm64 on macOS. The nominal baseline below is qualified **PASS**; additional workload-trial results and final regression status are recorded separately as they finish. No universal capacity or long-soak result is implied.

## Qualified nominal repetitions

All three runs used the same pinned image `pulsepay-load:qualified-20261010T134503Z`, source/profile hashes, API/dependency images, runtime settings and resource ceilings. Each began from the identical supported seed snapshot: 200 active INR accounts, 100,000 minor units each, 20,000,000 total funds, 200 provisioning ledger entries and zero transfers/projections. Activity was stopped in this test project. The main lab continued its ordinary breathing traffic on the same Docker VM; measurements therefore describe this shared development machine.

Profile: `nominal`, seed 4217, 20 users, spawn rate 10 users/sec, closed-loop pacing ceiling 20 logical operations/sec, 60% reads / 40% transfers, 30-second warmup followed by 120 measured seconds. Warmup samples remain in raw evidence and are excluded from these primary metrics. A replay can add an HTTP request, so achieved HTTP RPS can exceed the logical-operation ceiling.

| Metric | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Achieved HTTP requests/sec | 20.2167 | 20.1750 | 20.2167 |
| HTTP p50, ms | 28 | 27 | 30 |
| HTTP p95, ms | 50 | 48 | 52 |
| HTTP p99, ms | 65 | 63 | 67 |

Run IDs: `load-20261010T134512Z-9f044a0c`, `load-20261010T134757Z-9b10a699`, `load-20261010T135043Z-bc1ade62`. Every independent preflight and postflight verifier returned **PASS**. Each completed normally with zero unresolved transfer outcomes; the async pipeline drained in bounded cooldown. Exact per-run outcomes, operation latencies, resource observations and data volumes are in the retained evidence, rather than inferred from aggregate HTTP status codes.

The Docker VM reported 18 CPUs and 8,317,267,968 bytes of memory. The generator was capped at 1 CPU and 805,306,368 bytes. Core-service ceilings, image IDs and allowlisted configuration are captured in each manifest. These are allocated limits and actual observations, not assertions that the application can sustain a larger workload.

## Evidence and reproducibility

Versioned qualification metadata: [baseline.json](../artifacts/baseline/workload-v1/baseline.json). Full exported bundles remain under `artifacts/load-runs/<run_id>/` and the scoped Docker reports volume; historical failed/interrupted runs are retained too. The three earlier nominal runs with different Docker image IDs were correctly rejected and are not included in this reference.

Use `RESUME_QUALIFICATION=true make load-qualify` to repeat from the retained disposable snapshot. It creates new IDs and logs, builds/pins one image for the invocation, and checks the existing verifier before and after every run. Recorded image/source/profile/data/config identities must match before any comparison qualifies. See [workload methodology](workload-methodology.md) and [operator commands](phase2-load-generator.md).

## Interpretation limits

This is a bounded healthy reference at the selected pacing ceiling, not a saturation claim. PostgreSQL lock-wait, slow-query and deadlock metrics are not exported; pool wait cannot stand in for them. Generator network throughput is not independently measured. Exact arrival-rate scheduling is not implemented: Locust users are closed-loop. A shortened soak cannot establish hour-scale stability. WSL2/native Linux/Intel/macOS-host variants were not separately validated; executed platform evidence is Docker Desktop on this machine.
