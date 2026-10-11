# PulsePay framework experiment operations

Use the synthetic `chaosloop` Docker project only. `make up` runs PulsePay, idle Locust at http://127.0.0.1:8089 and Chaos Workbench at http://127.0.0.1:8090 with its private gateway/watchdog. There is no automatic load or fault injection. The UI links from PulsePay's sidebar; all services belong to one Compose project. Toolkit CLI runner/Pumba helpers remain one-shot tools in `compose.chaos.yaml`.

## Browser workflow

Start Locust from its UI, leave its PulsePay API target unchanged, and let the configured warmup finish. Preflight then requires at least 100 actual requests, 20 confirmed writes and a productive, error-free measured window of at least 15 seconds. Select **worker pause** in Workbench, click **Check preflight** and inspect the exact resolved target in the output. Click **Run experiment** and confirm the selected scenario. Run repeats native preflight before arming the independent watchdog. **Abort & restore** remains available during an active run; **Verify restoration** invokes the existing restoration/independent verification command. History shows actual failure/unknown verdicts, journals, timeline and JSON evidence.

The workload prerequisite is visible before injection. Run stays disabled while Locust is idle, warming up, stale, or lacking productive measured reads/writes. Preflight remains available for diagnostics. `LOAD_NOT_ACTIVE` includes the Locust link and a next step; native INVALID summaries include safe reason/remediation rather than just an exception class. Old history reads the preserved failure artifact without rewriting it.

Manual Locust evidence is measured and suitable for the existing experiment gates, but its performance report remains `INCOMPLETE` with `MANUAL_UI_SESSION_NOT_A_QUALIFIED_BENCHMARK`. Use versioned headless commands for capacity qualification. Controls accept only the eight reviewed scenario IDs, never uploaded YAML, arbitrary flags, targets or commands. CPU is shown as unavailable; database interruption needs `ALLOW_DATABASE_CHAOS=true` for both Workbench and gateway. Proxy scenarios refuse direct dependency routing.

`LOAD_BASELINE_ERRORS` means one of the recent measured transport/contract counters increased before injection. Inspect the Locust Errors tab and retained workload report; earlier lifetime errors alone do not block a later clean window. Wait for at least 35 seconds of productive error-free measured traffic after the last error, then check preflight again. A 2026-10-11 paced-100-user connection-reset race is fixed by retiring four-second-idle client sockets before the API closes them at five seconds; genuine failures continue to block the gate. [Keep-alive evidence](../artifacts/baseline/keepalive-v1/README.md) preserves the failed session, reproductions and new validation.

Workbench uses a non-root read-only image, 384 MiB / 0.5 CPU / 64 PIDs, 64 MiB tmpfs, bounded 4 KiB JSON actions and 128 KiB command output, health checks and graceful child termination. The independent watchdog continues restoration if its browser or process disappears. Its HTTP API requires an allowed local Host, matching Origin, same-site session cookie and CSRF header for changes. Ports bind to host loopback; no public ingress is supported. Browser history is intentionally operator evidence, including fault ground truth; sanitized future observations remain separate.

`make chaos-stop` disables the private control services, preserving the Workbench history and application. `make up` restores controls. `make down` first aborts/restores and waits for lease release before stopping the stack, retaining named volumes. Plain `docker compose up --build -d` starts the Workbench with controls unavailable unless the `chaos` profile is explicitly included; the supported complete-stack command is `make up`. Gateway/watchdog definitions live in `compose.yaml`; `compose.chaos.yaml` adds the on-demand native CLI runner under `chaos-jobs`, so enabling controls never runs an experiment by itself.

## Start and select a scenario

```sh
make up
make status
make verify
docker compose -f compose.yaml -f compose.chaos.yaml build chaos-runner
docker compose -f compose.yaml -f compose.chaos.yaml config --quiet
make chaos-list
make chaos-validate SCENARIO=002-worker-pause
make load-run PROFILE=nominal DURATION=600 USERS=20 RATE=20
```

Keep the load command running. In another terminal, wait until measured traffic has at least 100 requests, 20 committed transfers and a recent productive, error-free window of at least 15 seconds. Warmup is not eligible. `chaos-preflight` refuses missing/stale load, unavailable monitoring, unhealthy dependencies or non-PASS independent verification.

```sh
CHAOS_IMAGE_PREBUILT=true make chaos-preflight SCENARIO=002-worker-pause
CHAOS_IMAGE_PREBUILT=true make chaos-run SCENARIO=002-worker-pause
make chaos-report
```

The named scenario must be a reviewed native Chaos Toolkit YAML. The operator cannot supply arbitrary container IDs, regexes, URLs, images, shell code or Pumba flags. Parameters are bounded by the authorization policy: 3–40 seconds nominal exposure, 60–180 seconds total lease, fixed validated 150 ms network latency, one target. The independent cleanup deadline is nominal duration plus 15 seconds from first injection (at most 55 seconds), capped by TTL; repeated calls cannot extend it. The extra time permits framework observation and cleanup, and exceeding it is an ABORTED safety intervention. TTL includes preflight. Actual interfaces and full container IDs are discovered rather than guessed. Pumba dry-run waits the configured duration but does not mutate application containers.

| Scenario | Nominal exposure | Injector | Restore requirement |
|---|---:|---|---|
| `001-api-pause` | 10 s | Pumba pause | Original API unpaused, readiness and same active workload |
| `002-worker-pause` | 20 s | Pumba pause | Original worker unpaused, projection backlog catches up |
| `003-redis-outage` | 15 s | Pumba stop/restart | Redis AOF retained, cache/transport returns, ledger PASS |
| `004-api-network-delay` | 15 s / 150 ms | Pumba netem | Only experiment-owned qdisc removed, clean interface confirmed |
| `005-db-network-delay` | 15 s / 150 ms | Toxiproxy | Only the run-owned latency toxic removed |
| `006-cpu-pressure` | Disabled | Pumba stress-ng definition only | Refused on every backend pending kernel containment proof |
| `007-redis-network-partition` | 15 s | Toxiproxy | Original explicit Redis proxy enabled/configuration restored |
| `008-postgres-outage` | 8 s | Pumba stop/restart | Explicit opt-in, original DB/volume, full reconciliation |

`chaos-list` reports observed capability state. Network support requires actual isolated Linux `tc` probing. CPU injection is currently always refused with `KERNEL_CGROUP_MEMBERSHIP_UNVERIFIED`: Docker configuration echoes and coincident memory deltas do not prove containment. Its diagnostic uses a bounded read-only helper, never a stressor. The acceptance document records what actually ran on the available platform.

On this Docker Desktop cgroup-v2 host, an explicitly bounded 15-second idle helper with the API's exact cgroup parent failed before execution: OCI reported that a cgroup with domain controllers was in an invalid state. No stressor ran. The failed daemon setup changed the parent's controller mode, so the API was recreated from its unchanged 1 CPU / 384 MiB Compose ceiling; its cgroup returned to `domain` with no delegated subtree. CPU pressure stays unavailable. See the [kernel's cgroup-v2 constraints](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html) and [Docker's cgroup-parent interface](https://docs.docker.com/engine/containers/run/). Native Linux/WSL2 remains untested.

## Explicit database recovery qualification

Default nominal traffic still stops immediately on unknown integrity evidence. To deliberately test recovery under sustained traffic, select `dependency_recovery`: at most 20 users, 600 measured seconds, a recorded 20-second uncertainty grace with independent expiry, and the existing 30% infrastructure-error threshold over 60 seconds. UNKNOWN is never PASS; a proven invariant FAIL always stops. Use separate terminals:

```sh
# Arm only this conservative database scenario; retain normal direct dependency routing.
ALLOW_DATABASE_CHAOS=true docker compose --profile chaos up -d --no-deps docker-gate chaos-watchdog chaos-workbench
LOAD_IMAGE_PREBUILT=true PROFILE=dependency_recovery DURATION=360 WARMUP=30 USERS=20 RATE=20 sh scripts/load-run.sh
# Once Workbench reports ready, in another terminal:
ALLOW_DATABASE_CHAOS=true CHAOS_IMAGE_PREBUILT=true sh chaos/scripts/experiment.sh run 008-postgres-outage
# After the run and verification, restore the ordinary opt-in state:
ALLOW_DATABASE_CHAOS=false docker compose --profile chaos up -d --no-deps docker-gate chaos-watchdog chaos-workbench
make verify
```

Native experiment PASS requires real impact, the same workload still running after productive recovery, restoration and independent integrity PASS. A workload containing injected HTTP errors remains FAILED as a healthy benchmark. Post-run client intention recovery resolves original keys through HTTP, records recovered commits separately, and does not erase those failures. Older sealed outcomes without intention bodies remain unresolved historical evidence.

## Explicit dependency routing

Proxy experiments require an intentional routing change before starting measured traffic. Stop any existing load first and verify normal state. Apply the overlay explicitly:

```sh
docker compose -f compose.yaml -f compose.chaos.yaml -f compose.toxiproxy.yaml \
  --profile chaos-proxy up -d toxiproxy
docker compose -f compose.yaml -f compose.chaos.yaml -f compose.toxiproxy.yaml \
  --profile chaos up -d --wait api outbox-relay event-worker docker-gate chaos-watchdog
make verify
make load-run PROFILE=nominal
CHAOS_PROXY_ROUTING=true CHAOS_IMAGE_PREBUILT=true make chaos-run SCENARIO=005-db-network-delay
CHAOS_PROXY_ROUTING=true CHAOS_IMAGE_PREBUILT=true make chaos-run SCENARIO=007-redis-network-partition
```

Only API→Postgres and API/relay/consumer→Redis use `toxiproxy:15432` and `toxiproxy:16379`. Migrations, seed, verifier and database observer keep direct PostgreSQL connections. The administrative listener binds a private control interface at `10.254.251.2:8474`, reachable by the authorization gateway alone; it is not host-published or present on application/runner networks. This reserved small subnet may need a reviewed adjustment if it overlaps an existing Docker network on another host.

After proxy experiments, restore fault state and stop traffic before returning to direct routing:

```sh
CHAOS_PROXY_ROUTING=true make chaos-restore
make load-stop
CHAOS_PROXY_ROUTING=true make chaos-stop
docker compose --profile observability up -d --wait api outbox-relay event-worker
docker compose -f compose.yaml -f compose.chaos.yaml -f compose.toxiproxy.yaml stop toxiproxy
make verify
```

These commands deliberately recreate selected clients as routing changes; an active experiment never changes their routing or restarts the load generator to conceal impact.

## Database opt-in

Before the PostgreSQL-outage scenario, explicitly grant the gate and invocation permission. This does not grant broader targets or filesystem access:

```sh
ALLOW_DATABASE_CHAOS=true docker compose -f compose.yaml -f compose.chaos.yaml \
  up -d --wait docker-gate chaos-watchdog
ALLOW_DATABASE_CHAOS=true CHAOS_IMAGE_PREBUILT=true make chaos-run SCENARIO=008-postgres-outage
docker compose -f compose.yaml -f compose.chaos.yaml up -d --wait docker-gate chaos-watchdog
```

The existing load controller's integrity/error safeguards remain authoritative. A database outage may trigger its independent safety stop; the experiment records that external intervention and cannot claim recovery under sustained load. Financial records are never altered to force a passing result.

## Abort, interrupted runner and manual recovery

```sh
make chaos-abort       # stop the fault; preserves load
make chaos-restore     # scoped state restore and independent verification
make chaos-report
make load-stop        # separate explicit traffic cancellation
make chaos-stop       # remove socket authority from active runtime
```

The independent watchdog checks every 0.5 seconds and restores on explicit abort, TTL or fault-deadline expiry, or runner heartbeat loss over 12 seconds. It uses its own authenticated listener, cannot be a fault target and revokes new injection before cleanup. A gateway restart permits cleanup only for any surviving lease. Bounded mailbox reads and nonblocking regular-file writes/locks prevent hostile runner files from suppressing cleanup. Recovery requires the original full target ID/name/labels, running and unpaused state, original restart policy, no owned helper/toxic/qdisc, fresh health and independent verifier PASS. Pre-existing foreign network/toxic state is not erased.

If recovery cannot be confirmed, the lease stays blocked and the report requires manual acknowledgement. Fix the evidenced condition, then run `make chaos-restore`. A completed historical report is sealed with SHA-256 checksums; later recovery evidence is written separately under `recovery/<original-run-id>/`. It does not rewrite the original failure verdict. No volume-delete or broad Docker prune command is part of restoration.

## Evidence and interpretation

Each run retains native experiment YAML, immutable configuration/target identity, qualified baseline reference, same workload run/profile, framework journal/output, gateway audit, actual Pumba/Toxiproxy confirmation, timeline, before/during/after Prometheus and HTTP signals, bounded Loki logs/Tempo traces, independent integrity and restore reports, and checksums. Full bundles export into `artifacts/chaos/<run-id>/`; named volumes survive container removal. Preserve partial INVALID/ABORTED/INCONCLUSIVE results.

`PASS` requires actual injected impact, successful required native activities/rollbacks, strict restoration, fresh telemetry, independent PASS and the same productive load still running. An intentionally unavailable component during exposure is expected evidence, not a failed post-restore check. Missing signals remain unknown. Framework exit code or journal `completed` alone cannot establish recovery.

Use the existing Grafana **Load & Capacity** dashboard for load, DB, queue and resource measurements. Privileged operator annotations use bounded scenario labels and exposure/restore states. Future decision consumers receive only the sanitized `observation.json` contract, excluding scenario names, injector commands, target ground truth and expected root cause. `ground-truth.json`, journals and annotations remain privileged operator artifacts. Consumer accounts, permission enforcement and model integration are future work; this implementation supplies the output contract only.

Framework behavior follows the [official Toolkit run/rollback reference](https://chaostoolkit.org/reference/usage/run/), [Pumba source and command reference](https://github.com/alexei-led/pumba) and [Toxiproxy API](https://github.com/Shopify/toxiproxy). Exact pinned image help/source and acceptance evidence take precedence over examples for a different release.
