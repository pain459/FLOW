# PulsePay workload methodology

## What is measured

Profiles use closed-loop Locust users. A user selects a weighted logical operation, issues one or more HTTP requests, and waits. Users and spawn rate determine concurrency. The optional RATE control is an operation pacing ceiling, not an open-loop arrival guarantee. Scheduling and server response time can lower the offered operation rate. A journey, replay or retry can issue multiple HTTP requests, so achieved HTTP RPS can exceed logical operations/sec. Reports keep configured users, peak observed users, pacing ceiling, selected operations/sec and completed HTTP requests/sec separate. Target RPS is null because no exact arrival-rate controller is implemented.

Warmup has its own counters. Primary HTTP and business results use only requests initiated during the measured clock window; bounded inflight completion can finish afterwards. Native Locust CSVs retain all phases, while `locust-stats.csv` and summary percentiles use measured samples. Integer-millisecond pooled response-time histograms yield p50/p95/p99 without averaging worker quantiles. Quantiles are estimates at one millisecond precision.

A successful response requires the existing API's typed schema and matching known identifiers, currency and transfer intent. Expected rejection scenarios must return the exact expected error code. Reads, writes, business rejections, infrastructure failures, contract failures, timeouts and idempotency replays have separate counters. Only schema-valid successful transfer submissions count as accepted writes.

## Dataset and repeatability

Account IDs are discovered through the existing readonly dashboard API, never random nonexistent probes. Active funded accounts, external references, initial per-account funding and global fake funds are fingerprinted. Selection is seeded and stable for a single worker's controlled plan. Concurrent request scheduling, user distribution, UUID idempotency keys and lock acquisition are intentionally nondeterministic. Reproduce scenario inputs, not an identical interleaving.

One logical transfer gets one immutable canonical body and key, durably recorded before submission. Infrastructure retry reuses both; HTTP 200 replay must return the original transfer identity. Timeouts remain ambiguous until original-key/hash lookup or same-key replay establishes the outcome. Final reconciliation follows an independent verification barrier and remains outside measured performance; any recovery write is followed by another integrity check. Exhausted or malformed evidence is reported UNKNOWN and disqualifies a healthy run. Historical runs without intent journals cannot be retrospectively resolved. Positive amounts are at most 1,000 minor units, and random bidirectional selection limits systematic depletion. Unexpected business rejections remain visible and sustained depletion stops the workload. The generator never replenishes balances during measurement.

## Evidence and validity

Preflight and postflight execute the existing verifier with SELECT-only credentials. FAIL or UNKNOWN never qualifies as a healthy baseline. During runs, checks execute every 15 seconds. After traffic stops, bounded cooldown requires outbox pending=0 and projections=transfers.

Operational DEGRADED lag during a run does not imply fund corruption. Invariant FAIL stops immediately; ordinary profiles also stop on UNKNOWN immediately. The separately selected dependency_recovery profile permits a bounded 20-second uncertainty window, recorded as UNKNOWN, with an independent sticky deadline. The final cooldown and postflight must return PASS. Interactive Locust sessions are labeled manual and never qualify as comparable healthy baselines, even when their financial integrity passes.

Prometheus is sampled every five seconds, with explicit scrape timestamps. Required core observations must remain fresh through measurement. Missing optional counter series are null with a documented gap; absence is never a fabricated zero. Server/client HTTP counter differences use aligned sample windows and allow two five-second scrape windows. No automatic background traffic is included.

Docker resource observations come from an operator-side `docker stats` stream piped to the report container; no socket is mounted. Generator cgroup CPU and memory cover the controller plus local Locust master/workers. Consecutive measured CPU utilization >=90% disqualifies generator-limited results. Container ceilings, kernel/architecture, Docker VM CPUs/memory, image IDs, allowlisted runtime settings, profile/source hashes and seed evidence are recorded. The read-only database observer exports connection counts, lock waits, deadlocks and aggregate slow-query/statements timing without SQL text; pool waits remain a separate signal.

A comparable baseline needs at least three distinct PASS run IDs with matching initial account funding/data volume, profile, image IDs, runtime settings, generator/core resource ceilings, machine and on-demand traffic mode. Ordinary writes increase ledger volume, so those runs are not silently treated as equivalent. The qualification wrapper restores a supported-seed snapshot only in its fixed disposable project between repetitions. Median and range communicate variability without a universal RPS target.

## Boundaries

Profiles are versioned schema v1 YAMLs. Only the internal `http://api:8080` target is allowed. Hard limits: 150 users, four local workers, 14,400 measured seconds, bounded request/retry/backoff/cooldown. Durations over one hour require ALLOW_LONG_RUN=true. Starter profiles are tuning inputs, not measured capacity claims. A shortened soak only validates scheduling and lifecycle; it cannot prove multi-hour stability.

