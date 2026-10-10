# PulsePay chaos integration discovery

Audited 2026-10-10 on existing branch `feat/pulsepay-dashboard`; existing uncommitted workload/UI work is preserved. Docker Desktop runs Linux arm64, 18 allocated CPUs and 8,317,267,968 bytes. Only the main `chaosloop` deployment is running. No host tools beyond Docker/Compose and shell are required.

## Actual integration matrix

Existing Compose labels are `com.docker.compose.project=chaosloop` and `com.docker.compose.service=<service>`. Resolve container IDs through Docker's label-filtered list, require exactly one active replica, inspect its full ID, and recheck identity/labels before any mutation. Do not construct IDs from display names. The implementation adds `io.pulsepay.lab=disposable`, `io.pulsepay.chaos.target=true`, and `io.pulsepay.chaos.role=<service>` only to the following approved targets. All other services are excluded by default; tools, monitoring and verifier carry protected labels.

| Logical service | Compose name | Target role | Health / monitoring | Safe restore |
|---|---|---|---|---|
| HTTP API | `api` | `api` | HTTP :8080 `/health/live`, `/health/ready`, `/health/dependencies`; `up{job="api"}`, HTTP histograms | Unpause/start the frozen container ID; ready 200 |
| Event consumer | `event-worker` | `event-worker` | :9100 `/health/live`; heartbeat through dependency endpoint; lag/pending and event effects | Unpause/start frozen ID; require productive heartbeat and catch-up |
| Event relay | `outbox-relay` | excluded initially | :9100 `/health/live`; outbox pending/oldest | Observe only |
| Cache/transport | `redis` | `redis` | Docker Redis PING health; API dependency report; Redis operation/cache metrics | Start frozen ID without deleting AOF volume; require reachable and pipeline catch-up |
| Authority | `postgres` | `postgres`, explicit DB opt-in | Docker `pg_isready`; API readiness; independent verifier | Start frozen ID without altering volume; require schema readiness and full reconciliation |
| Integrity | `verifier` | excluded | :9100 metrics/live; `pulsepay_verification_status` | Read only; never inject |
| Workload UI | `locust` | excluded | :8089 HTTP UI, :9101 metrics | Remains running and retains shared run lock |
| Chaos Workbench | `chaos-workbench` | protected/excluded | :8090 `/health/live`, `/api/status`; loopback browser UI | No injection on boot; fixed native CLI actions; independent watchdog survives UI restart |
| Authorization / restoration | `docker-gate`, `chaos-watchdog` | protected/excluded | Private :2375 and :9111 health | Exact lease restoration/release before stopping controls |
| Headless workload | `load-controller` plus helpers | excluded | profile CLI, report volume, :9101 metrics | Never restart or stop from injector |
| Telemetry | Prometheus/Grafana/Loki/Tempo/OTel/log collector | excluded | internal service DNS and provisioned sources | Never inject |

`internal` is an isolated Compose network; `edge` publishes only loopback API8080, Locust8089, Workbench8090, Grafana3000, Prometheus9090 and logging24224. Database5432 and Redis6379 are not host-published. Application and browser containers are non-root with finite CPU/memory limits. Only the private authorization gateway mounts the Docker socket; no application, load, Workbench, runner or watchdog receives it. There is no host networking, PID namespace sharing or privileged container.

## Workload and financial contracts

`make load-run PROFILE=nominal` uses actual `/api/v1/accounts/...` and `/api/v1/transfers` HTTP routes. Supported discovery is `/api/v1/dashboard/accounts`; the dashboard snapshot provides aggregate volumes and event delivery. No workload SQL writes. Transfers require `Idempotency-Key`; canonical retries reuse the body/key. `make load-stop` cancels current traffic independently of the API and retains INTERRUPTED evidence. The lock and `active.json`, run `state.json`, `latest-observation.json`, manifests and verifier artifacts live in `load-reports:/reports`. Warmup is separate from measured RUNNING traffic. The new chaos tooling will mount this volume **read-only**, and will not receive load stop permissions.

`python -m verifier.main --once` uses the SELECT-only `pulsepay_verifier` principal and one REPEATABLE READ, READ ONLY snapshot. Exit PASS=0, FAIL=1, UNKNOWN=2, DEGRADED=3; schema version `0002`. Operational delivery lag may be DEGRADED during a fault, but final recovery requires full PASS. Runtime workers use `pulsepay_worker`; API uses `pulsepay_app`; schema migration uses `pulsepay_migrator`.

At discovery the healthy reference was workload-v2. New monitoring was qualified with three identical restored-dataset nominal repeats in `artifacts/baseline/workload-v3/baseline.json`: nominal20 users, 120 measured/30 warmup seconds, logical ceiling20/s; median20.175 HTTP RPS, p95 48ms. The full-hour soak also passed. Higher historical burst FAILED its delivery cooldown; that report is preserved. Current chaos data grows under continuous writes, so this reference is a healthy-state anchor rather than a controlled performance comparison. Each fault records its own fresh pre-state and dataset counters. Automatic activity/breathing was removed; the persistent Locust UI stays idle until explicitly started.

## Gaps and integration choices

- Completed read-only PostgreSQL statistics monitoring: connections/lock waits/deadlocks/long queries and aggregate statement timing, no SQL text or account labels. API pool wait remains a separate metric.
- Completed generator network counters with provenance, counter reset handling and controlled zero-error labels. A compact recent observation window supports bounded preflight and productive recovery checks.
- Completed 3,600 measured seconds of soak with independent pre/post PASS; complete evidence is in workload-v3.
- Docker Desktop Linux VM is the available platform. Native Linux and WSL2 cannot be claimed without those runtimes; provide repeatable containerized validation commands and document the remaining availability constraint.
- Chaos Toolkit owns native YAML sequencing, steady-state probes and rollbacks. A small Docker authorization gateway is a security boundary, not a custom chaos engine. Only this private gate mounts the Docker socket. Pumba jobs access its filtered API; other containers receive no daemon credentials. After the user's explicit UI request, `make up` enables Workbench and the `chaos` control profile while one-shot experiment jobs remain opt-in. Bare Compose startup retains history/read-only UI without enabling authority. The official visual offering Reliably is proprietary; the local free Workbench is a thin frontend over the existing native framework.
- Independent watchdog uses a bounded lease and restores frozen targets even if the runner dies. Its control volume is separate from load/evidence observations. Telemetry and watchdog cannot match injection labels.
- Network emulation uses a pinned namespace-scoped `tc` helper after a real isolated capability probe; host network/PID/cgroup mounts are denied. CPU stress is currently disabled on every backend pending kernel membership proof, with a recorded unsupported reason.
- Toxiproxy is opt-in through an explicit dependency-routing overlay. Route only API PostgreSQL and API/relay/consumer Redis clients; leave migration, seeding, verifier and monitoring direct. No transparent interception.

Framework references: [Chaos Toolkit experiment format](https://chaostoolkit.org/reference/api/experiment/), [run/rollback behavior](https://chaostoolkit.org/reference/usage/run/), [official Docker deployment](https://chaostoolkit.org/deployment/local/docker/), [Pumba](https://github.com/alexei-led/pumba), [Toxiproxy](https://github.com/Shopify/toxiproxy). Release tags and actual image digests are frozen after containerized command/capability validation.
