from prometheus_client import Counter, Gauge, Histogram

http_requests = Counter("http_requests_total", "HTTP requests", ["method", "route", "status_class"])
http_duration = Histogram("http_request_duration_seconds", "HTTP latency", ["method", "route"])
transfers = Counter("pulsepay_transfers_total", "Transfer requests", ["outcome"])
transfer_duration = Histogram("pulsepay_transfer_duration_seconds", "Transfer service latency")
pool_checked_out = Gauge("pulsepay_db_pool_checked_out", "Checked out DB connections")
pool_wait = Histogram("pulsepay_db_pool_wait_seconds", "Connection checkout wait")
db_errors = Counter("pulsepay_db_errors_total", "DB errors", ["type"])
redis_operations = Counter(
    "pulsepay_redis_operations_total", "Redis operations", ["operation", "outcome"]
)
cache_hits = Counter("pulsepay_cache_hits_total", "Summary cache hits")
cache_misses = Counter("pulsepay_cache_misses_total", "Summary cache misses")
outbox_pending = Gauge("pulsepay_outbox_pending", "Unpublished events")
outbox_oldest = Gauge("pulsepay_outbox_oldest_age_seconds", "Oldest unpublished event age")
events = Counter("pulsepay_events_processed_total", "Consumer effects", ["outcome"])
event_lag = Histogram("pulsepay_event_processing_lag_seconds", "Commit to projection time")
consumer_pending = Gauge("pulsepay_consumer_pending", "Pending deliveries")
consumer_oldest = Gauge("pulsepay_consumer_oldest_pending_age_seconds", "Oldest pending idle age")
consumer_lag = Gauge("pulsepay_consumer_lag", "Undelivered consumer group entries")
verification = Gauge(
    "pulsepay_verification_status", "PASS=0 FAIL=1 UNKNOWN=2 DEGRADED=3", ["check"]
)
service_up = Gauge("pulsepay_service_up", "Observed component reachable", ["service"])
component_observed = Gauge(
    "pulsepay_component_observed_timestamp_seconds", "Last completed component poll", ["service"]
)

# These finite dimensions have a known zero at process startup. Missing/stale
# scrapes still mean UNKNOWN; initialization does not substitute for availability.
for _operation in ("get", "set", "delete", "xadd"):
    for _outcome in ("success", "failure"):
        redis_operations.labels(_operation, _outcome)
for _outcome in ("processed", "duplicate", "quarantined", "retry"):
    events.labels(_outcome)
for _error in ("constraint", "unavailable", "deadlock", "serialization"):
    db_errors.labels(_error)
