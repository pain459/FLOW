# Operational signals

`make breathe` enables low-rate HTTP activity and the observability profile. Grafana: http://127.0.0.1:3000 (admin password in local `.env`); Prometheus: http://127.0.0.1:9090. Loki/Tempo/collector endpoints stay internal. Five provisioned dashboards are System Overview, Database and Ledger, Redis and Events, Activity and Correctness, and Trace and Logs Explorer.

API metrics expose traffic counters/histograms with templated routes and status classes. Pool checkout count and actual acquisition-wait histogram come from async connection checkout. Worker endpoints on 9100 expose process/productive health and event metrics. Activity has independent HTTP counters, in-flight gauge and latency buckets for p50/p95; verifier exports the latest independent check status.

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
| `pulsepay_activity_requests_total{operation,outcome}` / `pulsepay_activity_request_duration_seconds` / `pulsepay_activity_pending` | Actual client requests, latency, in-flight work |
| `pulsepay_service_up{service}` | Reachability/component observations; combine with scrape `up` and freshness |

No account UUID, transaction UUID, key, request ID or exception string appears in metric labels. Prometheus scrapes every five seconds. Activity `up=0` in idle mode means intentionally absent, not an outage of the core system. Zero activity and UNKNOWN verifier panels are explicit fallbacks before those services start.

FastAPI, SQLAlchemy, HTTPX and Redis instrumentation exports OTLP through the collector to Tempo. Transfer service and publish/project spans describe asynchronous causality. Outbox metadata stores W3C context and request ID; relay extracts context, consumer creates trace links. Redis span statements contain command names only; no cached balance payload is placed in them. The log formatter uses active trace IDs.

JSON stdout fields: UTC timestamp, level, service, event, message, request_id, trace_id, operation_id and controlled error_class. Docker's built-in Fluentd driver asynchronously forwards to Fluent Bit's Forward input on loopback 24224. Fluent Bit parses JSON and labels Loki only by job/service. No Docker socket or host container-log path is mounted. Loki queries: `{job="pulsepay",service="api"} | json`, then filter request_id/trace_id. Grafana derived fields link trace_id to Tempo; Tempo links back to Loki.

Trace/log export is best effort. Docker buffers 4096 events plus 4 MiB nonblocking logging; dual logging cache rotates at 10 MiB × 3. Fluent Bit retains at most 64 MiB disk backlog; telemetry outage can drop logs after those limits. Money and durable event state are independent. Loki/Tempo/Prometheus retain 24 hours (Prometheus also capped at 256 MiB). Redis streams and quarantine evidence are deliberately retained throughout the finite Phase 1 lab; reset only disposable lab volumes when needed.

`make observe-test` checks live Prometheus traffic, Loki correlation across API/relay/worker, HTTP and SQL spans, relay trace continuity, consumer causal links, Grafana datasource/dashboard provisioning and dashboard PromQL result vectors. Executed evidence is recorded in [phase1-acceptance.md](phase1-acceptance.md); provisioning files alone are not acceptance evidence.
