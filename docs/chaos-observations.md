# Sanitized observations and evaluator evidence

Schema **1.1** uses opaque run IDs, UTC observation time, a 30-second window, workload users/RPS, API throughput/error/latency, database reachability/connections/locks, Redis reachability, worker queues, independent integrity and allowed read-only investigation names. It contains no scenario, target, injector, fault intensity or expected cause.

Each logical source carries provenance, observed time, age, maximum age and FRESH/STALE/UNKNOWN. Worker/outbox/database values require both a successful scrape and a completed producer sample within 15 seconds. Polling failures retain the old producer timestamp, even while the metrics HTTP server responds. API/load statistics require a fresh successful scrape. Independent verification has a 60-second freshness bound; an expired PASS becomes current UNKNOWN while retaining the last observed verdict. Missing, negative, nonfinite or stale values are null with controlled missing-field identifiers. Delivery freshness measures snapshot age separately from signal freshness.

Worker quantities have distinct units: `consumer_lag_messages` is the undelivered group-entry count; `pending_messages` is delivered/unacknowledged entries; `outbox_pending` and `outbox_oldest_seconds` describe unpublished SQL rows. `oldest_pending_age_seconds` is the maximum idle age sampled from the first 25 pending stream entries, not a full-scan maximum or commit-to-processing latency. No metric currently measures the age of every undelivered entry; `consumer_lag_seconds` is null and explicitly missing. The event-processing latency histogram remains available to trusted operators.

The publisher writes preflight, exposure and post-restoration snapshots plus replay into `chaos-observations`. The non-root `observation-feed` mounts only that volume read-only, contains only two standard-library modules, and joins only the internal investigation network. It has 128 MiB / 0.25 CPU / 32 PIDs, at most eight request threads, a three-second connection timeout, a four-MiB file bound and at most 512 replay samples. It rejects mutation methods, extra fields, contradictory freshness, private fields, symlinks, oversized files and arbitrary endpoints. Unknown evidence returns 503 rather than a healthy verdict. No database, Docker, Prometheus or operator credentials are present.

The feed intentionally has no host port. Its network is available for a future separately restricted read-only consumer. An operator can inspect it through Docker:

```sh
docker compose exec -T observation-feed python -c 'import urllib.request; print(urllib.request.urlopen("http://localhost:8091/api/v1/observations/latest").read().decode())'
# From a container explicitly attached to chaosloop_investigation:
# GET http://observation-feed:8091/api/v1/observations/<opaque-run-id>/sequence?limit=100
```

Workbench at localhost:8090 is a privileged operator surface and must not be supplied to an investigator/model. The feed cannot reach its control or artifact paths, even by discovered IP. Host Docker administrators remain trusted and can bypass container boundaries.

Original journals and fault truth remain in private `chaos-evidence`. Historical missing labels are supplemented under `artifacts/baseline/readiness-v1/evaluator/ground-truth/`, using hashes and explicit field provenance. This derived namespace is not mounted in the feed. Original results and seals are preserved; absent exact injection/termination evidence stays unknown. New reports distinguish injector confirmation from independent effect and verified restoration. The derived labels support evaluation, not decisions.

Allowed investigation names are a contract and capability inventory, not implemented model tools. Existing health queries, read-only SQL verifier/database observer, bounded metric queries and trusted log/trace lookups provide provenance and errors. A future investigation executor still requires a separately audited allowlist, per-tool timeout/cost limits, authentication and denial of control/privileged evidence. This change implements no model, tool executor or autonomous action selection.
