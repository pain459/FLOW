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

The normal persistent stack, including idle Locust, totals **5,248 MiB / 9.25 CPU ceilings**. A headless run plus its helpers adds **928 MiB / 1.35 CPUs**, for **6,176 MiB / 10.6 CPUs** while running. CPU quotas limit individual processes; fewer physical CPUs simply mean shared contention. Configure the Docker VM with sufficient memory for the chosen services and transient jobs. The temporary qualification project is a second copy only while validation runs; stop it afterward without deleting evidence.

`LOAD_CPU_LIMIT` and `LOAD_MEMORY_LIMIT` explicitly configure both UI and headless generator ceilings. Worker processes share their generator container's ceiling. App/Locust containers also have a 128-process ceiling and 64 MiB temporary filesystem; helper ceilings are smaller. PostgreSQL connection pools default to eight with no overflow and bounded waits. Redis limits data to 128 MiB with no eviction of transport evidence.

Logging rotates at 10 MiB × three files per service (helpers 1 MiB × two). Prometheus retention is 24 hours and 256 MiB; Loki/Tempo retention is 24 hours. The collector uses bounded queues. Generator sampled errors are capped at 50 per worker.

`LOAD_REPORT_BUDGET_MIB=512` is a report admission budget: refuse a new run unless 32 MiB remains, and stop running traffic if the remaining budget falls below 1 MiB. Historical evidence is never silently deleted. This is an application admission safeguard with a small polling/write overhead, not a filesystem quota. PostgreSQL and named-volume disk space must be monitored by the operator; Compose cannot impose a portable hard volume quota. Runs have finite duration/users and never silently mint additional funding. Archive retained reports explicitly before starting further runs once the budget is reached. Financial records remain immutable.

Actual sanitized Docker resource evidence is retained with acceptance artifacts. No Docker socket, privileged mode or host networking is used.

The raw bootstrap-secret and reset-scope parser containers are also capped at 128 MiB / 0.5 CPU / 32 processes with networking disabled; they only manipulate local configuration or parse scoped project metadata. These host-invoked utilities do not run in normal operation.
