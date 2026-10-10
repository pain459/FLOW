# Operational signals

`make up` enables observability without automatic traffic. Start Locust on demand. Grafana: http://127.0.0.1:3000 (admin password in local `.env`); Prometheus: http://127.0.0.1:9090. Loki/Tempo/collector endpoints stay internal. Six provisioned dashboards are System Overview, Database and Ledger, Redis and Events, Workload and Correctness, Trace and Logs Explorer, and Load & Capacity.

API metrics expose traffic counters/histograms with templated routes and status classes. Pool checkout count and actual acquisition-wait histogram come from async connection checkout. Worker endpoints on 9100 expose process/productive health and event metrics. Locust exposes measured HTTP counters and latency histograms; verifier exports the latest independent check status.

| Metric | Meaning |
|---|---|
| `http_requests_total{method,route,status_class}` | Request outcomes; account/transfer IDs never label series |
| `http_request_duration_seconds{method,route}` | Real request latency histogram |
| `pulsepay_transfers_total{outcome}` / `pulsepay_transfer_duration_seconds` | Commits, replays, rejected/failed requests and latency |
| `pulsepay_db_pool_checked_out` / `pulsepay_db_pool_wait_seconds` | Pool occupancy and checkout delay |
| `pulsepay_db_errors_total{type}` | Controlled constraint/unavailable error classes |
| `pulsepay_redis_operations_total{operation,outcome}` | Bounded cache/stream operations and failures |
| `pulsepay_cache_hits_total` / `pulsepay_cache_misses_total` | TTL summary outcomes |
| `pulsepay_outbox_pending` / `pulsepay_outbox_oldest_age_seconds` | Unpublished durable events |
| `pulsepay_events_processed_total{outcome}` | Processed, duplicate, quarantined and retry outcomes |
| `pulsepay_event_processing_lag_seconds` | Commit-to-consumer processing histogram |
| `pulsepay_consumer_pending` / `pulsepay_consumer_lag` / `pulsepay_consumer_oldest_pending_age_seconds` | Pending, not-yet-delivered, abandoned delivery signals |
| `pulsepay_verification_status{check}` | PASS 0, FAIL 1, UNKNOWN 2, DEGRADED 3; absent evidence is UNKNOWN |
| `pulsepay_service_up{service}` | Reachability/component observations; combine with scrape `up` and freshness |

No account UUID, transaction UUID, key, request ID or exception string appears in metric labels. Prometheus scrapes every five seconds. The load scrape is absent while idle; this is intentional. Missing verifier evidence stays UNKNOWN.

FastAPI, SQLAlchemy, HTTPX and Redis instrumentation exports OTLP through the collector to Tempo. Transfer service and publish/project spans describe asynchronous causality. Outbox metadata stores W3C context and request ID; relay extracts context, consumer creates trace links. Redis span statements contain command names only; no cached balance payload is placed in them. The log formatter uses active trace IDs.

JSON stdout fields: UTC timestamp, level, service, event, message, request_id, trace_id, operation_id and controlled error_class. Docker's built-in Fluentd driver asynchronously forwards to Fluent Bit's Forward input on loopback 24224. Fluent Bit parses JSON and labels Loki only by job/service. No Docker socket or host container-log path is mounted. Loki queries: `{job="pulsepay",service="api"} | json`, then filter request_id/trace_id. Grafana derived fields link trace_id to Tempo; Tempo links back to Loki.

Trace/log export is best effort. Docker buffers 4096 events plus 4 MiB nonblocking logging; dual logging cache rotates at 10 MiB × 3. Fluent Bit retains at most 64 MiB disk backlog; telemetry outage can drop logs after those limits. Money and durable event state are independent. Loki/Tempo/Prometheus retain 24 hours (Prometheus also capped at 256 MiB). Redis streams and quarantine evidence are deliberately retained throughout the finite PulsePay lab; reset only disposable lab volumes when needed.

`make observe-test` checks live Prometheus traffic, Loki correlation across API/relay/worker, HTTP and SQL spans, relay trace continuity, consumer causal links, Grafana datasource/dashboard provisioning and dashboard PromQL result vectors. Executed evidence is recorded in [phase1-acceptance.md](phase1-acceptance.md); provisioning files alone are not acceptance evidence.
# Operator dashboard signals

The provisioned **Load & Capacity** Grafana dashboard shows measured HTTP mix/RPS, configured users/weights, pooled latency buckets, logical transfer outcomes, core/container/generator resources, queue lag, and verifier age. It is provisioned as part of the same PulsePay lab. Locust controls are part of normal startup on localhost:8089 and remain idle until Start. `make load-ui` ensures the service is running. During idle operation, missing load-controller scrape data means no run is active. See [workload operations](phase2-load-generator.md) for metric/report semantics and qualified baseline requirements.

The FastAPI dashboard adds a live transaction chart, component diagram, request/event correlation details and fresh independent verification at http://127.0.0.1:8080/. Grafana remains available for detailed metrics, logs and traces. The UI explicitly distinguishes queued publication, pending processing and durable commit; stale/missing evidence is UNKNOWN. See [dashboard documentation](dashboard.md).

## Database, generator and explicit experiments

The `db-observer` uses SELECT-only access plus lab-scoped PostgreSQL monitoring privileges. It exposes `pulsepay_database_connections{state}`, `pulsepay_database_lock_waits`, `pulsepay_database_deadlocks_total`, active queries over 250 ms, and aggregate `pg_stat_statements` timing without SQL text. `pulsepay_database_observed_timestamp_seconds` measures freshness; unavailable samples are NaN/UNKNOWN and never zero-filled. This process has 128 MiB / 0.25 CPU.

Generator network counters come from its Linux `/proc/net/dev` namespace and include source/availability metadata. Load & Capacity panels show these counters, DB waits/query timing, monitoring age and the existing latency/queue/verifier signals. Real query validation is part of the live observability regression; provisioned JSON alone does not count as evidence.

The optional watchdog exports `pulsepay_experiment_status{scenario}` (idle 0, armed 1, exposure 2, restoring 3, restored 4) for privileged Grafana annotations. Scenario labels are from the finite catalog, never run IDs. Monitoring remains outside all fault target labels. Missing watchdog scrape while chaos tools are stopped is expected.

Per-run sampled Prometheus, HTTP, Loki and Tempo evidence has source timestamps and explicit missing-data indicators. Thirty-second histogram windows overlap short faults; recorded percentiles describe those windows. The output-only [observation contract](observation-contract.md) excludes privileged scenario/target/injector fields. Operators retain full framework journals and ground truth separately.
