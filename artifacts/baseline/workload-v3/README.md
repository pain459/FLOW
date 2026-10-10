# PulsePay current monitoring baseline

Measured on 2026-10-10 using Docker Desktop's Linux arm64 VM (18 allocated CPUs, 8,317,267,968 bytes), with the CPU/memory ceilings recorded in each manifest. These are host-specific observations, not capacity promises.

Three nominal repetitions used the same original seed snapshot in the disposable `chaosloop-load-baseline` project, one frozen image, 20 users, a 20 logical-operation/s ceiling, 30 seconds of separate warmup and 120 measured seconds. All three independently verified PASS before and after. Median achieved HTTP throughput was 20.175 requests/s (range 20.175–20.175); median p50/p95/p99 were 26/48/63 ms (ranges 26–33, 47–55, 60–70 ms). See `baseline.json`, the three summaries and `evidence/nominal-repeats.tar.gz`. The temporary deployment was stopped, retaining its scoped data and evidence volumes.

The full-hour soak ran on the living main `chaosloop` dataset: 40 users, 20 logical-operation/s ceiling, 30 seconds warmup, 3,600 measured seconds. It completed 43,218 valid reads and 28,687 confirmed transfers, with no business rejections or unknown transfer outcomes. Independent pre/post verification both passed. Achieved throughput was 20.133333 HTTP requests/s; p50/p95/p99 were 46/84/103 ms. See the soak summary/verifications and `evidence/hour-soak.tar.gz`.

Database observations include read-only connections, lock waits, deadlocks, active queries exceeding 250 ms and aggregated `pg_stat_statements` timings, without SQL text. Generator network counters come from its Linux network namespace. Missing observations remain explicitly recorded. The living soak dataset differs from the restored nominal dataset; performance comparisons between them are not controlled comparisons. The previous high-burst delivery timeout and interrupted soak attempt remain retained in raw run history.

No native Linux or Windows/WSL2 host was available. These results establish the available Docker Desktop VM only. Uncommitted source is identified by the exact built image IDs and configuration fingerprints in the manifests; Git HEAD alone is not a complete source revision.
