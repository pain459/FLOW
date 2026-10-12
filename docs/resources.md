# PulsePay resource budget

Every Compose service has an explicit CPU quota and memory ceiling, including one-off tools. Limits are enforced by Docker Compose/Desktop. They are ceilings, not reservations or measured usage.

| Service group | Memory ceiling | CPU ceiling |
|---|---:|---:|
| API, relay, consumer, verifier (each) | 384 MiB | 1 |
| PostgreSQL | 768 MiB | 1 |
| Redis | 256 MiB | 0.5 |
| Prometheus, Grafana, Loki, Tempo (each) | 384 MiB | 0.5 |
| OpenTelemetry collector | 256 MiB | 0.5 |
| Log collector | 128 MiB | 0.25 |
| Persistent Locust UI | 768 MiB | 1 |
| Optional headless controller and its Locust processes | 768 MiB | 1 |
| Load workflow guard | 32 MiB | 0.1 |
| Resource sampler | 128 MiB | 0.25 |
| Migration, seed, ordinary tests (each, transient) | 384 MiB | 1 |
| Browser tests (transient) | 1,024 MiB | 1 |
| Telemetry ownership job (transient) | 32 MiB | 0.25 |
| Read-only database observer | 128 MiB | 0.25 |
| Database monitoring setup (transient) | 384 MiB | 1 |
| Persistent Chaos Workbench | 384 MiB | 0.5 |
| Authorization gateway / watchdog (each) | 128 MiB | 0.25 |
| Restricted read-only observation feed | 128 MiB | 0.25 |
| Observation-volume ownership job (transient) | 32 MiB | 0.1 |
| Framework runner (on demand) | 384 MiB | 0.5 |
| Pumba / namespace helper (each, at most four) | 64 MiB | 0.25 |
| Reserved stress helper (currently disabled) | 64 MiB | 1 |
| Optional Toxiproxy | 64 MiB | 0.25 |
| CPU Laya inference | 3,072 MiB | 2 |
| Incident controller | 384 MiB | 0.5 |
| Localhost investigation ingress | 128 MiB | 0.25 |
| Fixed-read live evidence reader | 128 MiB | 0.25 |
| Model provisioning (transient) | 512 MiB | 0.5 |
| Decision roles / export (each, transient) | 128 MiB | 0.25 |
| Decision migration (transient) | 256 MiB | 0.25 |
| Evaluator (transient) | 256 MiB | 0.5 |
| Decision tests (transient) | 384 MiB | 0.5 |

The inference/controller/ingress/evidence services add **3,712 MiB / 3.00 CPUs** to the earlier persistent ceiling totals: **9,856 MiB / 13.75 CPUs** overall. These are enforced per-service ceilings, not reserved usage. The current 8 GiB Docker VM was sufficient for the measured idle/replay checks; allocating 12 GiB provides headroom for the complete stack and transient test jobs. This does not establish high-load capacity. No service is uncapped.

The normal persistent `make up` stack, including idle Locust, Workbench, its gateway/watchdog, the read-only database observer and restricted observation feed, totals **6,144 MiB / 10.75 CPU ceilings**. A headless run plus its helpers adds **928 MiB / 1.35 CPUs**, for **7,072 MiB / 12.10 CPUs** while running. Browser-triggered native Toolkit processes share the Workbench's 384 MiB / 0.5 CPU ceiling; a separate CLI runner adds 384 MiB / 0.5 CPU only while invoked. Each Pumba/namespace helper is capped and at most four can exist. CPU stress is disabled on every backend until actual kernel parent-cgroup containment is proven. CPU quotas limit individual processes; fewer physical CPUs simply mean shared contention. Configure the Docker VM with sufficient memory for the chosen services and transient jobs. The temporary qualification project is a second copy only while validation runs; its exit cleanup stops all profiles without deleting evidence. Plain `docker compose up` without the `chaos` profile starts Workbench in history/read-only mode; `make up` enables the reviewed controls, without automatic injection.

`LOAD_CPU_LIMIT` and `LOAD_MEMORY_LIMIT` explicitly configure both UI and headless generator ceilings. Worker processes share their generator container's ceiling. App/Locust containers also have a 128-process ceiling and 64 MiB temporary filesystem; helper ceilings are smaller. PostgreSQL connection pools default to eight with no overflow and bounded waits. Redis limits data to 128 MiB with no eviction of transport evidence.

Logging rotates at 10 MiB × three files per service (helpers 1 MiB × two). Prometheus retention is 24 hours and 256 MiB; Loki/Tempo retention is 24 hours. The collector uses bounded queues. Generator sampled errors are capped at 50 per worker.

`LOAD_REPORT_BUDGET_MIB=512` is a report admission budget: refuse a new run unless 32 MiB remains, and stop running traffic if the remaining budget falls below 1 MiB. Historical evidence is never silently deleted. This is an application admission safeguard with a small polling/write overhead, not a filesystem quota. PostgreSQL and named-volume disk space must be monitored by the operator; Compose cannot impose a portable hard volume quota. Runs have finite duration/users and never silently mint additional funding. Archive retained reports explicitly before starting further runs once the budget is reached. Financial records remain immutable.

Actual sanitized Docker resource evidence is retained with acceptance artifacts. Application, Workbench, workload, runner and watchdog containers receive no Docker socket or host networking. Only the private authorization gateway mounts the socket; it uses an isolated network and exact target/helper policies. `make chaos-stop` removes runtime authority while leaving history accessible. No container uses privileged mode. Network helpers receive NET_ADMIN only inside their selected target network namespace.

The raw bootstrap-secret and reset-scope parser containers are also capped at 128 MiB / 0.5 CPU / 32 processes with networking disabled; they only manipulate local configuration or parse scoped project metadata. These host-invoked utilities do not run in normal operation.
