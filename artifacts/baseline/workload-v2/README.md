# PulsePay workload reference v2

Measured 2026-10-10 on Docker Desktop Linux arm64. [baseline.json](baseline.json) qualifies three matching nominal repetitions **PASS**. [measured-results.json](measured-results.json) collects exact per-run observations, including the **FAILED** upper burst and **INTERRUPTED** cancellation; no historical verdict was rewritten.

Each run directory contains its manifest, summary, exact independent pre/post verifier output, measured statistics and `full-evidence.tar.gz`. The archive retains the complete exported bundle: time-series, resource samples, workload phase events, raw Locust statistics, bounded errors and worker evidence. Operator commands, actual test outcomes and interpretation limits are in [acceptance](../../../docs/phase2-acceptance.md) and [methodology](../../../docs/workload-methodology.md).

Nominal repetitions restored identical supported seed snapshots: 200 active INR accounts, 20,000,000 minor units of explicitly recorded provisioning, zero initial transfers. Generator image was pinned for the entire qualification. Subsequent short trials intentionally grew the ledger between runs; compare their actual manifests rather than assuming equal data volume. Automatic activity was removed and the persistent Locust UI stayed idle during measured headless runs.

The `evidence/` directory retains regression, browser, UI, resource-limit, recovery, tracing/logging, cancellation, final idle/verification and deployment-cleanup evidence. Temporary deployment volumes were retained after stopping its containers. Full runtime exports under `artifacts/load-runs/` remain gitignored; this compact versioned bundle is intentionally kept in the repository.

The upper 20→60→20-user burst did not meet its cooldown deadline and is **not healthy capacity**. Later verification proved recovery, without altering its failed report. The lower burst differs in duration and peak concurrency. Short soak and ramp runs establish functionality only. Database lock/slow-query metrics, hour-scale stability and unavailable host platforms remain explicit evidence gaps.
