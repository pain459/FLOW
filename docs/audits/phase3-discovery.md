# Phase 3 audit discovery

Audit `audit-20261011T161813Z-ae620f81`, started 2026-10-11 16:18:13 UTC. Repository `/Users/ravik/src_git/FLOW`, branch `feat/pulsepay-dashboard`, HEAD `ae620f81f1b91b8b57d4e7cfdf7900ba2614fa31`. This audit changes only audit documentation/evidence. No application, configuration, experiment, branch or historical evidence changes; no new faults or resets.

The user's supplied framework specification and verification checklist are the audit baseline. No root file named `CHAOSLOOP_PHASE3_FRAMEWORK_BASED_CHAOS.md` was found. Existing implementation and retained execution evidence determine actual interfaces.

## Runtime and isolation

The running project is `chaosloop`, with 17 persistent services. Docker Desktop reports Docker 29.8.2, Linux/aarch64, 18 VM CPUs and 8,317,267,968 allocated memory bytes. This is the macOS Docker Desktop backend; Windows/WSL2 and native Linux were not available for execution.

All 17 services have finite CPU and memory limits: aggregate configured ceilings **10.5 CPU / 6,016 MiB**. These are limits, not measured usage or guaranteed reservations. No observed service is privileged, paused, in host networking, or sharing the host PID namespace. Services with no declared healthcheck have no Docker health verdict; monitoring availability is checked separately. Full images, IDs, limits, restart policies and safe labels are in the audit's `runtime-state.json`; declarations are in `compose-discovery.json`.

`make up` runs `docker compose --profile observability --profile chaos up --build -d`. It includes idle Locust, Workbench and restoration controls, as requested earlier. It does not start an experiment or recurring injector. One-shot `chaos-runner`/Pumba services remain separately selected. Bare Compose startup does not enable the chaos authority profile. The old automatic breathing client is absent.

`internal` is the isolated application network; `edge` provides loopback-only host access; `chaos-control` separates fault/restoration control. The optional Toxiproxy control network is separate. API 8080, Locust 8089, Workbench 8090, Grafana 3000, Prometheus 9090 and the logging receiver 24224 bind to 127.0.0.1. PostgreSQL, Redis and private daemon-control ports have no host publication.

## Integration matrix

Targets require all of `com.docker.compose.project=chaosloop`, the exact Compose service, `io.pulsepay.lab=disposable`, `io.pulsepay.chaos.target=true`, and matching `io.pulsepay.chaos.role`. A protected label or one-off container excludes the target. Resolution uses label-filtered Docker discovery, then full 64-character ID inspection and revalidation; display names alone are insufficient. Exactly one target must match each role.

| Logical component | Actual service/interface | Target / lookup | Health and monitoring | Scoped restore or constraint |
|---|---|---|---|---|
| Financial API | `api:8080`, `/api/v1/*` | role `api`; gateway exact-ID target lookup | `/health/live`, `/health/ready`, `/health/dependencies`, `/metrics`; HTTP histograms and transfer metrics | Unpause/start frozen ID; require readiness and productive HTTP/write recovery |
| Event consumer | `event-worker:9100` | role `event-worker` | `/health/live`, heartbeat, worker pending/lag/event metrics | Unpause frozen ID; require backlog catch-up and receipts/projections |
| Outbox relay | `outbox-relay:9100` | Excluded | Process health, pending rows/age, publish errors | Observe only |
| Cache/transport | `redis:6379` | role `redis` | Redis PING health, dependency endpoint, cache/transport error metrics | Start frozen ID; retain AOF volume; require catch-up |
| Authoritative DB | `postgres:5432` | role `postgres` | `pg_isready`, API readiness, DB observer, independent verifier | Start frozen ID; never alter volume; verify schema and ledger |
| Integrity verifier | `verifier:9100`, `python -m verifier.main --once` | Protected/excluded | `/report`, `/metrics`, latest independent check | SELECT-only principal; PASS=0, FAIL=1, UNKNOWN=2, DEGRADED=3 |
| DB observer | `db-observer:9100` | Protected/excluded | Connections, locks, deadlocks, query aggregate metrics | Read-only statistics; no fault target |
| Persistent workload UI | `locust:8089`; metrics `:9101` | Protected/excluded | Manual session/status, actual request/outcome counters | Idle until Start; finite runtime; injector cannot stop/restart load |
| Headless workload | `load-controller`, `scripts/load-run.sh` | Protected/excluded | Manifest/profile, `latest-observation.json`, interval counters, report volume | Shared exclusive run lock; cancellation is a separate operator control |
| Native framework runner | `chaos-runner`, `chaos/experiments/*.yaml` | Never a target | Chaos Toolkit hypotheses, methods, rollbacks and journal | One-shot reviewed scenario; no uploaded shell or custom experiment language |
| Fault provider | Pinned `pumba` / gateway-created bounded helper | Never a target | Dry-run targeting, injector output, effect probes | Exact pinned command/image policy; finite exposure |
| Authorization boundary | `docker-gate` | Protected/excluded | Private filtered Docker API and target/lease lookup | Only socket-mounted service; trusted high-privilege component |
| Independent restoration | `chaos-watchdog:9111` | Protected/excluded | Health, heartbeat/lease/fault deadlines | Scoped restoration independent of runner lifetime |
| Operator Workbench | `chaos-workbench:8090` | Protected/excluded | `/api/status`, catalog, operator run/artifact history | Local operator UI; it is not an investigator-only API |
| Telemetry | `prometheus:9090`, Grafana, Loki, Tempo, OTel, log collector | All excluded | Provisioned metrics, logs, traces and dashboards | Never injected; source freshness must be preserved for future consumers |
| Precise dependency proxy | Optional `toxiproxy` | Fixed proxy names, explicit routing overlay | Proxy administration on separate control network | Restore only owned toxic/enable changes; not currently routed |

Database interruption is available in the normal stack by the current deployment default `ALLOW_DATABASE_CHAOS=true`; explicit false still opts out. Actual Run requires operator confirmation, healthy preflight and bounded duration. This audit did not exercise database interruption.

## Versions and capabilities

| Component | Frozen source |
|---|---|
| Chaos Toolkit | `chaostoolkit/chaostoolkit:1.21.4@sha256:ff1427c09b029e82796e430d9bf6e127f992da247a27175d64eb1193149e86fe` |
| Pumba | `ghcr.io/alexei-led/pumba:1.2.1@sha256:780505fe261932765921c94a23e24bda107c72927654c26a5893a238d7708bf0`; retained binary output reports 1.2.0 |
| Netem helper | `ghcr.io/alexei-led/pumba-alpine-nettools@sha256:bdcfacdd0c42f64cd280319d6dd5d3911f33425ce4a5168bb1b7de9570b72cd1` |
| Toxiproxy | `ghcr.io/shopify/toxiproxy:2.12.0@sha256:9378ed52a28bc50edc1350f936f518f31fa95f0d15917d6eb40b8e376d1a214e` |
| Application/load/framework builds | Local version tags plus actual content image IDs retained in audit manifest/runtime inventory; do not equate a reused `:v1` tag with identical historical images |

The eight native definitions validate in the Docker framework suite. Seven scenarios have retained successful real executions: API pause, worker pause, Redis outage, API network delay, PostgreSQL dependency latency, Redis partition and PostgreSQL outage. Default exposures are 10, 20, 15, 15, 15, 15 and 8 seconds respectively. Manual exposure is bounded to **3–300 seconds**; TTL is bounded to **60–420 seconds**, with restoration allowance. Netem latency is the reviewed 150 ms plan, not an arbitrary user command.

CPU pressure is disabled. Retained `artifacts/baseline/gap-closure-v1/checks/cpu-capability.json` records an idle, capped helper failing OCI setup before any stress executed: `cannot enter cgroupv2 with domain controllers -- it is in an invalid state`. It has no observation timestamp; none is invented. Mark CPU injection **SKIPPED_UNSUPPORTED**, and use supported lifecycle/network scenarios instead. Native Linux/WSL2 CPU containment remains untested. The audit did not repeat this daemon/cgroup diagnostic because it previously required API recreation to restore unchanged limits.

Toxiproxy is optional and stopped in the current topology. `compose.toxiproxy.yaml` routes only API→PostgreSQL through port 15432 and API/relay/consumer→Redis through port 16379. Migration, seed, verifier and DB observer stay direct. Proxy scenarios require deliberate overlay activation and cannot be interpreted as currently available from the default direct routes alone. Overlay configuration was validated without rerouting clients.

## Financial and workload contracts

Schema revision **0002** is applied. There is one explicit seed run and 200 funded synthetic accounts. The audit observed roles `pulsepay_app`, `pulsepay_worker`, `pulsepay_verifier`, `pulsepay_migrator` without superuser/create-role/create-DB/replication/bypass-RLS privileges. The verifier has SELECT but no INSERT/UPDATE/DELETE on accounts, ledger, transfers, outbox and projections. Financial reconciliation uses one **REPEATABLE READ, READ ONLY** transaction. Runtime write privileges use column/function restrictions; absence of table-level UPDATE privilege is not evidence that transfers cannot update balances.

Public HTTP load uses existing account/balance/summary/history/transfer paths and API-backed discovery at `/api/v1/dashboard/accounts`. The additional read-only `/api/v1/transfers/by-idempotency-key` checks the canonical request hash. Transfer retries preserve key/body; bounded persisted client intentions support ambiguous-outcome reconciliation. No generator financial SQL mutation was found.

Profiles include `smoke`, `nominal`, read/write-heavy, burst, hot accounts, step ramp and soak. Closed-loop users and the logical operation pacing ceiling are not promised HTTP arrival RPS. Warmup is retained separately. `load-reports` contains the lock, state, immutable profile/manifest, interval observations and verifier reports; injector reads it only.

The ordinary nominal safety policy can stop on integrity UNKNOWN during DB unavailability. The explicitly selected `dependency_recovery` policy allows a bounded UNKNOWN grace, still stops on FAIL, and is the profile used for retained DB recovery-under-load qualifications. An ordinary nominal outage that safety-stops load must be reported as recovery after load removal, not sustained-load resilience.

## Read-only investigation inventory

These are existing data sources and reserved observation names, **not a deployed model-facing executor**. The future executor remains outside this audit.

| Reserved name | Existing read-only sources | Existing bounds / error states | Handoff restriction |
|---|---|---|---|
| `inspect_api` | Named HTTP metric queries; live/ready/dependency endpoints | HTTP timeouts; unhealthy/unknown, missing or stale query data | Allowlisted query names/routes only |
| `inspect_database` | DB observer and independent verifier | SELECT-only role; bounded connection/pool/statement waits; PASS/FAIL/UNKNOWN/DEGRADED | No migrator/runtime write credentials or arbitrary SQL |
| `inspect_redis` | Dependency reachability, cache/Redis operation metrics | Null/missing data versus observed failure | No arbitrary Redis administrative commands |
| `inspect_workers` | Worker/relay lag, pending, retries, event outcomes | Process health differs from productive progress; timestamped metrics | Preserve distinction between outbox age and consumer lag |
| `collect_more_evidence` | Bounded Loki/Tempo queries in current adapters | Bounded log/trace counts and HTTP deadlines; missing evidence explicit | No raw Workbench artifacts, broad metric queries or fault annotations |
| `escalate` | Future investigator output | No current mutation action | Output only; cannot override watchdog or stop load |

Existing adapter bounds are implementation details, not a security-enforced investigator budget. Phase 4 read-only mode requires a bounded auditable executor and isolated credentials/network/files before model use. Raw Prometheus carries scenario labels; operator Workbench exposes privileged metadata and ground truth. Neither is a safe general-purpose investigator endpoint.

## Executed commands and evidence

All Python/tests ran in Docker. No build, reset, application reconfiguration, fault injection, watchdog interruption or live abort was performed. Two finite headless workloads used real HTTP and then stopped their own traffic/helpers.

```sh
docker compose --profile observability --profile chaos config --quiet
docker compose -f compose.yaml -f compose.load.yaml -f compose.chaos.yaml -f compose.toxiproxy.yaml --profile observability --profile chaos --profile chaos-proxy config --quiet
docker compose -f compose.yaml -f compose.chaos.yaml --profile chaos run --rm --no-deps -T -v /Users/ravik/src_git/FLOW:/workspace:ro --entrypoint pytest chaos-runner -c /dev/null -p no:cacheprovider -q chaos/tests
docker compose run --rm --no-deps -T -v /Users/ravik/src_git/FLOW:/app:ro tests pytest -q
docker compose -f compose.yaml -f compose.load.yaml run --rm --no-deps -T -v /Users/ravik/src_git/FLOW:/workspace:ro load-controller pytest -q load_generator/tests
docker compose exec -T verifier python -m verifier.main --once
LOAD_IMAGE_PREBUILT=true PROFILE=nominal DURATION=120 WARMUP=30 USERS=20 RATE=20 sh scripts/load-run.sh
```

The exact optional telemetry-test command, two workload executions, read-only helper commands, exit codes and outputs are retained in `artifacts/audits/phase3/audit-20261011T161813Z-ae620f81/commands.md` and `runs/`. Discovery inventory includes no secret values or complete resolved environment configuration. Final readiness findings are in [phase3-readiness.md](phase3-readiness.md).
