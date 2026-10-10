# PulsePay framework experiment acceptance

**Overall verdict: INCOMPLETE.** Six distinct fault scenarios have qualified results with independently verified financial integrity. PostgreSQL outage exposed a workload safety-stop and client-outcome limitation; CPU pressure remains disabled because kernel containment is unproven. Neither is recorded as a passing resilience test.

Executed on 2026-10-10/11 using Docker Desktop's Linux arm64 VM on macOS. Existing branch `feat/pulsepay-dashboard` is preserved, with no new branch, commit, tag or push. Git HEAD is `ebb71ac5fb13038bc61447293651782176231f94`; actual image IDs, scenario hashes and manifests identify uncommitted builds. Native Linux and Windows/WSL2 were unavailable and remain unverified.

See the [discovery matrix](phase3-discovery.md), [operator guide](phase3-operations.md), [implementation ledger](superpowers/plans/2026-10-10-pulsepay-chaos.md) and [durable evidence](../artifacts/baseline/framework-v1/README.md). Original reports and checksums are retained, including failed and interrupted attempts.

## Framework and deployment checks

Chaos Toolkit 1.21.4 owns native YAML sequencing and rollbacks. Pinned Pumba release image 1.2.1 supplies real faults; its binary reports 1.2.0, checked against actual help and command behavior. Toxiproxy 2.12.0 affects only explicitly routed dependency clients. Images and dependencies are pinned. No custom experiment language, workflow engine or decision model is implemented.

All eight native YAML definitions validate in Docker. Combined application/load/chaos/Toxiproxy overlays pass `docker compose config --quiet`. Following the explicit UI request, `make up` includes Workbench and its private control services, with no automatic experiment. Bare Compose startup leaves controls disabled unless their profile is enabled. Only the authorization gateway receives the Docker socket; exact target/helper policies reject unrelated containers, image/volume mutations, arbitrary commands and host namespaces. Application, Workbench, load, runner and watchdog receive no socket. Every service/helper has finite [CPU/memory ceilings](resources.md).

## Actual fault demonstrations

Each PASS includes injector confirmation, observed impact, scoped restoration, independent pre/post PASS and the same active workload. Exact UTC timestamps, full target IDs, load links, intensity, metric samples and journals are in the evidence bundle.

| Scenario | Run ID | Result | Evidence |
|---|---|---|---|
| API pause, 10 s | `chaos-20261010T173513Z-4f19fcaf` | PASS | Availability impact, unpause and successful requests afterward |
| Worker pause, 20 s | `chaos-20261010T173155Z-f54acfc6` | PASS | Projection backlog peaked at 158, then caught up |
| Worker pause repeat | `chaos-20261010T173609Z-16a4cfad` | PASS | Backlog peaked at 167; repeated effect direction |
| Redis outage, 15 s | `chaos-20261010T174221Z-0caa7065` | PASS | Persistence retained, deferred events caught up, ledger correct |
| API network delay, 150 ms / 15 s | `chaos-20261010T180303Z-0dc9e29e` | PASS | Real Pumba netem, latency rise, owned qdisc removed |
| API→PostgreSQL latency, 150 ms / 15 s | `chaos-20261010T181949Z-bdbd407d` | PASS | Owned toxic removed; productive HTTP/write recovery window verified |
| Redis dependency partition, 15 s | `chaos-20261010T182127Z-a368dc4b` | PASS | Explicit proxy restored, productive load recovered, separate ground-truth artifact |
| PostgreSQL outage, 8 s, explicit opt-in | `chaos-20261010T182510Z-32f8f95b` | RESILIENCE_FAILURE | Database/financial integrity restored; workload safety-stopped |
| CPU diagnostic | `chaos-20261010T175523Z-fda99b71` | INVALID / unsupported | No stress injected; kernel containment unproven |

Failed network attempts remain retained. Early unsupported command forms were refused before injection; two later attempts restored correctly but failed an HTTP impact probe during observed latency. Prometheus established the detector problem; the corrected detector qualified a new run. Proxy preflights retain normalized-listener and oversized-load-file failures. Fixes never rewrite those records.

## Safety and recovery

- Forced runner SIGKILL: `chaos-20261010T174041Z-eb8faa38`, experiment **ABORTED**, safety test **PASS**. Watchdog `RUNNER_HEARTBEAT_LOST` restored the worker 15 seconds after the kill, before natural expiry. Post-verification PASS; the same load remained RUNNING. Missing complete native journal remains explicit.
- Explicit abort: `chaos-20261010T182309Z-08c818c4`, experiment **ABORTED**, safety test **PASS**. `OPERATOR_ABORT` restored the worker in 4 seconds; pre/post PASS and load RUNNING. Its historical summary misclassifies an active but unverified productive window as external intervention. That classification is fixed/tested; the sealed original is preserved with this note.
- Live protected-verifier/unknown-target mutations, volume prune and image creation returned **403**. The verifier remained running and unpaused. A simultaneous second experiment was refused as **INVALID** by the exclusive lease.
- Toxiproxy administration was inaccessible from the runner using both service DNS and its private control IP.
- Tests cover private watchdog authority, first-injection deadlines, restart revocation, bounded nonblocking files/locks, concurrent restore, full evidence disk and hostile symlinks. Repeated calls cannot extend fault lifetime or promote capability probes to injection.

## PostgreSQL resilience finding

The actual outage used explicit permission at both gateway and invocation. Pumba restored the original container without deleting its volume; readiness, workers and independent reconciliation recovered. Workload `load-20261010T181731Z-659bf7a2` independently stopped on `SUSTAINED_INFRASTRUCTURE_ERROR_RATE`: 451.86 measured seconds, 5,080 valid reads, 3,455 confirmed commits, 245 failed HTTP attempts (230 infrastructure failures, 15 timeouts), and **51 unknown logical transfer outcomes**.

Same-key bounded retries exhausted during the outage. No public idempotency-key lookup or durable client-intent reconciliation resolved those individual outcomes. Both integrity snapshots PASS; final delivery backlog zero. Conservation does not resolve client ambiguity. Recovery after traffic removal does not prove sustained-load recovery. Thresholds were not weakened and load was not restarted to conceal the finding.

Follow-up: prove kernel cgroup containment before CPU stress; design durable client-outcome reconciliation and separately qualify PostgreSQL recovery under an intentionally chosen workload safety policy. Financial write semantics remain unchanged.

## Regression commands and outcomes

All commands run in Docker. Exact logs are retained under `framework-v1/checks`.

| Check | Actual outcome |
|---|---|
| `make chaos-test`: native/safety/rollback/evidence suite | **56 passed** |
| Containerized application unit/integration/concurrency/resilience suites | **55 passed**, one upstream Starlette deprecation warning |
| Containerized workload suite | **36 passed** |
| `sh scripts/ui-test.sh`: real browser workflows | **7 passed** |
| Live Locust idle/Start/Stop/repeated-session test | **1 passed**, UI retained after Stop |
| Live Prometheus/Loki/Tempo/Grafana check under bounded workload | **1 passed**, 62 panel queries, three provisioned datasources, correlated HTTP/SQL/outbox/consumer traces/logs |
| Ruff lint/format and mypy | PASS, 127 formatted files and 47 typed source files at the check |
| Eight native YAML validations, combined Compose config, shell syntax, whitespace | PASS |
| Final smoke and independent ledger verifier | PASS |

Reproduce the live load-panel check with a measured headless run active:

```sh
LOAD_IMAGE_PREBUILT=true PROFILE=nominal DURATION=90 WARMUP=10 USERS=5 RATE=20 sh scripts/load-run.sh
# In another terminal while measured traffic is active:
docker compose run --rm --no-deps -e OBSERVABILITY_TEST=true -e LOAD_OBSERVABILITY_TEST=true tests pytest -q tests/e2e/test_observability.py
```

Final bounded run `load-20261010T184109Z-67498a30` **PASS**: 90 measured seconds, 1,102 valid reads, 681 confirmed commits, achieved 20.033333 HTTP requests/s, pre/post integrity PASS and no failures. It is a final functional check, not a replacement capacity baseline.

Initial final checks caught a stale zero-failure query in the older Workload dashboard; it now uses the explicit outcome counter. An additional check without a measured headless run correctly lacked generator-only RPS/resource data; that failed invocation is retained. The final run supplies the required real data rather than fabricating idle measurements.

The outage also exposed a negative pool gauge from unmatched SQLAlchemy check-ins after failed checkout. A reproducing unit test failed before correction. The gauge now reads actual pool occupancy; regression passes and the handoff sample is zero. This metrics-only fix changes image provenance from the earlier baseline; no performance-equivalence claim is made.

## Prior gaps closed

Full-hour soak `load-20261010T161333Z-974fd66b` **PASS**: 3,600 measured seconds, 43,218 valid reads, 28,687 confirmed transfers, zero unknown outcomes, independent pre/post PASS, achieved 20.133333 HTTP requests/s, p50/p95/p99 46/84/103 ms. Three identical-dataset, frozen-image nominal repeats PASS: median 20.175 HTTP requests/s and p95 48 ms. [workload-v3](../artifacts/baseline/workload-v3/README.md) retains full evidence. These are actual host-specific observations, not capacity promises.

Read-only database connections, lock waits, deadlocks, slow-query counts and aggregate `pg_stat_statements` timing are now observed without SQL text. Generator Linux network counters and missing-data handling are tested. Grafana exposes these signals and experiment annotations. The [sanitized observation contract](observation-contract.md) excludes privileged fault ground truth; no decision model is implemented.

## Handoff and remaining limits

The earlier CLI-only handoff stopped temporary `chaosloop-load-baseline` including observability/verifier profiles, retaining volumes/reports; qualification cleanup handles all profiles on exit. `framework-v1/checks` records that historical state with gateway/watchdog/Toxiproxy stopped. The newer Workbench handoff below supersedes runtime startup instructions while preserving all sealed evidence and resilience findings.

CPU stress remains disabled on every backend until real containment is proven; Docker configuration echoes and memory deltas are insufficient. PostgreSQL sustained-load resilience and 51 client outcomes remain unresolved. Native Linux/WSL2 are untested. Early runs predate standalone `ground-truth.json`; their privileged evidence remains in metadata, injector, timeline and audit records. Future consumer permissions are not implemented. These explicit limits retain the overall **INCOMPLETE** verdict despite six qualified scenarios and passing financial checks.

## Chaos Workbench addition — UI acceptance PASS

The explicit follow-up asks for the available UI in the same stack. The official Toolkit visual offering, [Reliably](https://chaostoolkit.org/offering/), is proprietary. A free local PulsePay Workbench instead delegates fixed native framework entrypoints; it adds no alternate scenario language, chaos engine or decision system. It is available at **http://127.0.0.1:8090** and linked from PulsePay. Locust remains at 8089; no traffic or fault starts automatically. `make up` includes the UI, gateway and watchdog in the one `chaosloop` project; on-demand CLI jobs remain an overlay. Every component has finite resources: persistent total **6,016 MiB / 10.5 CPU ceilings**, Workbench **384 MiB / 0.5 CPU / 64 PIDs**.

Actual additional validation on 2026-10-10/11:

| Command/check | Outcome |
|---|---|
| `make up` with all ordinary stack UIs/control services | Exit 0; one Compose project, 17 running persistent services |
| Framework safety/native tests including Workbench | **66 passed** |
| Load-generator tests including manual traffic evidence | **37 passed** |
| Application unit/integration/concurrency and resilience | **52 + 3 passed** |
| Main PulsePay Chromium workflows | **7 passed** |
| Workbench catalog/history/disabled-CPU and actual preflight→Run→report | **2 passed** |
| Browser Abort during an observed active worker fault | **1 passed** |
| Complete Compose overlays, Ruff for touched Python, shell syntax, whitespace | PASS |
| Final smoke and independent read-only reconciliation after stack restart | PASS |
| Runtime limits and socket boundary | 17 services capped; only gateway mounts socket; no privileged/paused target |

Browser Run `chaos-20261010T191532Z-36abf3a2` **PASS**: actual worker pause/backlog impact, native journal, RESTORED, independent pre/post PASS and the same manual workload RUNNING/productive at recovery. Browser Abort run `chaos-20261010T191940Z-f409ec98` **ABORTED**: actual impact, watchdog restoration, independent pre/post PASS, same load RUNNING, verified release of the lease and Run re-enabled. Interrupted completion/injector-exit evidence remains explicit; ABORTED is not a qualified resilience PASS.

The first browser attempt failed before injection because its test read the UI port rather than actual metrics port 9101 and expected an unlabelled metric. Corrected checks parse the measured labelled series. The new sidebar link also reproduced mobile horizontal overflow; wrapping fixes it and all seven dashboard tests pass. Independent review found early Abort before lease publication and recovery/start overlap. Tests failed before fixes: cancel the associated browser process group, delegate fixed native abort→verified restore/report/release, and block subsequent starts until finalization finishes. Native string restoration/load.after_state fields now display their actual verdicts. Qualification uses a separate Workbench port 18091 to avoid collision with the ordinary stack; its temporary project does not enable fault authority.

The browser guards enforce local Host, matching Origin/session/CSRF, bounded JSON, reviewed action/scenario IDs and explicit Run confirmation. CPU remains visibly disabled, database opt-in and explicit proxy routing remain enforced, original failed/unknown reports remain visible, and no frontend receives socket/authority credentials. Actual manual load samples satisfy existing fresh/productive preflight gates; their capacity report remains INCOMPLETE with `MANUAL_UI_SESSION_NOT_A_QUALIFIED_BENCHMARK`.

Evidence: [workbench-v1](../artifacts/baseline/workbench-v1/README.md), including complete native run/load bundles, screenshots, browser output, health/integrity snapshots and sanitized resources. Reproduce UI acceptance deliberately against an idle synthetic lab:

```sh
docker compose build ui-tests
docker compose run --rm --no-deps \
  -e WORKBENCH_UI_TEST=true -e WORKBENCH_FAULT_TEST=true \
  ui-tests pytest -q tests/ui/test_workbench_browser.py
```

This explicit test starts bounded manual HTTP traffic and worker faults, then stops its traffic. Default tests never inject. Final handoff keeps one 17-service stack, direct PostgreSQL/Redis clients, healthy Workbench/gateway/watchdog and idle Locust; Toxiproxy and all injector helpers remain stopped/absent. Existing CPU/PostgreSQL/platform limitations preserve the overall framework **INCOMPLETE** verdict.
