# PulsePay framework experiment acceptance

**Overall catalog verdict: INCOMPLETE; seven supported scenarios have qualified recovery evidence.** The 2026-10-11 follow-up below fixes the hidden idle-load rejection, adds durable client-outcome recovery and qualifies PostgreSQL restoration under an explicitly bounded recovery workload. CPU pressure remains unavailable on this Docker host; native Linux/WSL2 remains unverified. Historical failed runs and their unresolved client outcomes are preserved, rather than relabeled.

Latest gap-closure work uses existing branch `feat/pulsepay-dashboard` at `680d097`, without a new branch, commit, tag or push. Actual image/source hashes identify the working-tree build. See [gap-closure evidence](../artifacts/baseline/gap-closure-v1/README.md) and [its implementation ledger](superpowers/plans/2026-10-11-fault-readiness-and-gap-closure.md). The original framework-v1 evidence and limitations below describe its historical build.

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

## Fault-readiness and recovery follow-up — 2026-10-11

The user-reported `chaos-20261011T035003Z-005d521b` was INVALID before injection: `Scenario requires existing active steady HTTP load`. Its preserved failure artifact already contained this reason; the browser hid it behind the exception-only summary. The Workbench now shares the real preflight workload gate, displays readiness/remediation, disables Run while prerequisites fail, and reads historical failure details without rewriting records. An actual idle Chromium preflight now shows `LOAD_NOT_ACTIVE` and the Locust next step.

The compatible read-only `GET /api/v1/transfers/by-idempotency-key` checks the original canonical hash. Load clients persist bounded fsynced intentions before submission. Finalization looks up ambiguous intentions and permits one original-key/body completion only after an independent PASS barrier and validated complete not-found evidence. Recovery writes get a subsequent cooldown and verifier. Malformed/unavailable evidence remains UNKNOWN; original HTTP failures and measured throughput are not rewritten.

| Executed gate | Actual outcome |
|---|---|
| Application unit/integration/concurrency/resilience | **56 passed**; two explicit live gates skipped by the default command |
| Workload contracts/instrumentation/reconciliation/lifecycle | **61 passed** |
| Native framework/safety/rollback/evidence | **71 passed**; upstream Starlette warning |
| Ruff check/format; expanded runtime mypy | PASS; 135 formatted files, 88 checked runtime source files |
| Main dashboard Chromium; Workbench catalog and idle rejection | PASS; no implicit fault or load startup |
| Live Locust Start/Stop/repeated session | PASS; UI retained and final integrity independently checked |
| Live metrics/logs/traces/Grafana gate | **1 passed**, real workload samples and provisioned panel queries |
| All Compose overlays, shell syntax, whitespace | PASS |
| HTTP smoke and independent verifier | PASS |

Docker regression outputs, original journals, intentions and exact verifier reports are retained in [gap-closure-v1](../artifacts/baseline/gap-closure-v1/README.md). Relevant commands include:

```sh
docker compose run --rm --no-deps tests pytest -q tests --ignore=tests/ui
docker compose -f compose.yaml -f compose.load.yaml run --rm --no-deps load-controller pytest -q load_generator/tests
make chaos-test
make lint
docker compose run --rm --no-deps -e WORKBENCH_UI_TEST=true ui-tests pytest -q tests/ui/test_workbench_browser.py -k idle_fault_preflight
make smoke
make verify
```

Worker pause `chaos-20261011T051021Z-4c7c81a6` passed through the browser while preserving an already active headless workload. PostgreSQL outage `chaos-20261011T051149Z-4267a1dd` then passed under that same workload: real eight-second exposure, restoration verified, pre/post financial PASS and productive recovery under sustained traffic. Its workload correctly reports FAILED as a healthy benchmark because it observed 211 infrastructure responses. All 51 measured ambiguous intentions were resolved separately; no original transport failure was hidden.

The post-review PostgreSQL repeat `chaos-20261011T054327Z-0759842d` also **PASS** under unchanged active workload `load-20261011T054159Z-50866465`. The workload completed all 180 measured seconds, retained 226 infrastructure responses and a FAILED benchmark verdict, and reconciled **all 66** measured ambiguous intentions with the same original keys/bodies. Final unknown count is zero; independent pre/post integrity PASS. Recovery occurred before traffic ended, with no safety intervention or generator restart. Both runs deliberately selected the capped `dependency_recovery` policy; ordinary nominal UNKNOWN-stop behavior is unchanged.

An independent six-minute healthy check on the final images, `load-20261011T053002Z-3ccb11ea`, **PASS**: achieved 20.1 HTTP requests/sec, 2,869 measured confirmed transfers, zero unknown outcomes, pre/post integrity PASS. It is a functional check, not a new three-repeat capacity baseline. Original frozen-image performance evidence remains valid only for its recorded environment/data volume.

One fresh review identified five important gaps and they were reproduced before correction: sticky independent integrity deadline, malformed journal handling, total HTTP deadline/body ceiling, complete not-found envelope validation, and Stop's finalization wait. The focused tests changed from 10 failures/17 passes to 28 passes, then the complete workload suite passed. Broadened typing also exposed malformed business-code/helper-body handling; both received failing regression tests and fail-closed fixes. No mutation authority or default safety gate was relaxed.

CPU containment is now an observed backend limitation rather than an assumed capability. A capped, read-only, network-isolated idle helper with the exact API cgroup parent failed before executing: OCI rejected an invalid cgroup-v2 domain-controller state. No stressor ran. The API was recreated with unchanged fixed ceilings to clear the failed daemon setup; CPU injection remains disabled. Native Linux/WSL2 was unavailable. Older ambiguous client outcomes lack original intention bodies and remain unresolved historical evidence. These explicit catalog/platform limits retain the overall INCOMPLETE verdict; the Workbench error, new client-outcome path and conditional PostgreSQL recovery gaps are closed.

The handoff retains one ordinary stack with idle Locust, no active chaos lease, database-fault opt-in false and all persistent resource ceilings intact. Original sealed artifacts are untouched.

### Final matching-image qualification and handoff

The existing Docker-only qualification workflow completed three new comparable nominal repetitions, each from the identical supported seed snapshot, on one frozen generator/application configuration. Each had 30 seconds of warmup and 120 measured seconds, 20 users and a 20 logical operations/sec pacing ceiling. All three reports **PASS** with independent pre/post integrity PASS, zero failed measured HTTP requests and zero unknown outcomes. Median/range: achieved HTTP **20.1750 requests/sec (20.1750–20.2167)**, **p50 26 ms (23–31)**, **p95 47 ms (44–50)**, **p99 57 ms (53–60)**. The retained [qualification JSON](../artifacts/baseline/gap-closure-v1/qualification/baseline.json) identifies all three runs and their comparison key. This is a new bounded nominal reference, not a repeat of the historical full-hour soak or a saturation claim.

Executed command: `RESUME_QUALIFICATION=true QUALIFICATION_NOMINAL_ONLY=true sh scripts/load-qualify.sh`, exit **0**. Its temporary `chaosloop-load-baseline` project stopped automatically without deleting volumes/reports. Final `docker compose ls` shows only `chaosloop`, with **17** running persistent services, fixed **6,016 MiB / 10.5 CPU aggregate ceilings**, no paused/privileged service and socket access only in the gateway. Locust is stopped with zero users; no active experiment lease exists. Core health and both control services are healthy. The API's unconfirmed exporter-delivery signal remains explicitly UNKNOWN; the separate live metrics/logs/traces/dashboard gate passed.

Final read-only verifier `51767386-aa31-4387-bfbb-1c9da7ded1a3` **PASS** at `2026-10-11T06:06:15Z`: 200 accounts, **83,579** transfers, all checks zero violations, total balances/provisioning **20,000,000** minor units, no pending outbox or overdue projection. Original framework/workbench checksum seals verified unchanged, and the new bundle passed the credential scan. Exact resource, health, source hashes and verifier evidence are included in the new bundle.

One final Locust idle assertion initially failed because a simultaneously executed smoke transfer changed the count from 83,417 to 83,418. The unchanged test reran alone and **PASS** in 37.34 seconds; this harness failure is retained in `checks/live-checks.json`. No test or integrity requirement was weakened.

## Paced-user preflight regression — 2026-10-11

User run `chaos-20261011T065742Z-7a297eb3` correctly refused injection with LOAD_BASELINE_ERRORS. The existing 100-user Locust session had repeated connection resets; every status-0 transport failure was misleadingly classified as a timeout. A controlled 700-request diagnostic reproduced 54 resets among 350 requests using default reused sockets and none among 350 requests using fresh sockets. Actual exception chains were Requests ConnectionError → ProtocolError → RemoteDisconnected/ConnectionResetError, with millisecond durations. At the configured rate cap, user pacing coincided with the API's five-second idle connection expiry.

Clients now retire sockets after four seconds idle, preserve shorter-period reuse, and retain real reset/timeout categories and controlled error classes. Existing transfer identities, retries, resource limits and financial write behavior are unchanged. Real-socket and classification regressions failed before the fix; full workload **66 PASS**, application **56 PASS / two default live checks skipped**, framework **71 PASS**, Ruff/format and mypy **PASS**. Only idle Locust was recreated; no new deployment or fault was started.

The fresh 100-user session `load-ui-4745f8d2f7cf430c8c973397e04518a2` passed its bounded functional check without HTTP errors, maintained LOAD_READY for another 30 seconds and remained available to the operator under its 630-second lifetime cap. Independent financial verification PASS. CLI Redis-outage preflight `chaos-20261011T075814Z-f3e81c58` and the actual Workbench preflight `chaos-20261011T080037Z-43143f50` both **PASS**, explicitly `injected=false`. Original failed reports retain their verdicts, and the mandatory healthy-window gate is intact. See [keepalive-v1 evidence](../artifacts/baseline/keepalive-v1/README.md). This new-image functional check does not relabel earlier frozen capacity measurements or establish a new nominal/soak qualification.

## Manual exposure selection — 2026-10-11

Workbench now accepts **3–300 whole seconds** per scenario. Its confirmation and job retain the chosen value, as do native YAML, metadata/hash and reports. Make `DURATION` and native CLI `--duration-seconds` use the same policy. Presets remain 8/10/15/20 seconds. Explicit overrides derive a TTL of at least exposure plus **120 seconds**, up to **420 seconds**; browser execution budgets cover that TTL and reporting. Frozen fault deadlines cannot renew, missing heartbeat still restores after the existing 12-second threshold, and all target/proxy/database/resource restrictions remain in effect. Pumba's no-mutation targeting check now lasts three seconds so preflight does not consume a long selected fault's lease.

Executed Docker checks:

| Check | Actual result |
|---|---|
| Initial duration regressions before implementation | 20 failed / 8 passed |
| Dry-run timer regression before correction | 3 failed / 2 passed |
| Framework/native/authorization/watchdog/Workbench suite | **105 passed**, 19.39 s |
| Workload regression suite | **66 passed**, 5.75 s |
| Application regression suite | **56 passed / 2 default live checks skipped**, 26.14 s |
| Chromium duration payload/confirmation, desktop/mobile controls, idle rejection | **3 passed**, 4.41 s |
| Actual browser preflight → 60-second worker pause → recovery | **1 passed**, 166.29 s |
| Native Docker validation at 300 seconds | **PASS**, selected 300 / TTL 420 |
| Native Docker validation at 301 seconds | Rejected, exit **2**, no injection |
| `make chaos-validate SCENARIO=002-worker-pause DURATION=60` | **PASS**, selected 60 / TTL 180 |
| Ruff check/format, mypy | **PASS**, 136 formatted files / 88 typed runtime files |
| Main/chaos Compose config | **PASS** |

Live run `chaos-20261011T083533Z-f33045fd` **PASS**: Pumba recorded actual pause at **08:35:40Z** and unpause at **08:36:40Z**, with selected exposure **60 seconds** and TTL **180 seconds**. Observed projection backlog peaked at **447**; recovery and independent pre/post integrity PASS, original worker restored, no missing required observations, and the same workload `load-ui-9aaf5ca5fe264f54b5aa9afe87fda442` remained RUNNING/productive after restoration. The test then explicitly stopped only its own load: **3,219 completed HTTP requests, zero failed**. These are functional observations, not capacity measurements.

The browser screenshot diagnostic initially failed: full-page capture/resize reproduced a Chromium renderer crash without cgroup OOM events. Bounded panel screenshots and separate desktop/mobile pages preserve all control/history/cancellation/recovery assertions and actual images within the unchanged 1 GiB browser-test limit. Docker archive copying cannot see Workbench's tmpfs export, although the file exists; exporting through the existing evidence volume succeeded without permission changes. Initial failures remain in the new [exposure evidence bundle](../artifacts/baseline/exposure-v1/README.md).

Independent final snapshot at **08:42:10Z**, check `58505ff4-8ca0-4b0f-9797-bd7f63e04f4d`: **PASS**, 200 accounts, 94,771 transfers, zero violations, balances/provisioning **20,000,000 minor units**, pending outbox and overdue projections **0**. Gateway/watchdog healthy, no active lease, Locust stopped/zero users. All four earlier framework/workbench/gap-closure/keepalive checksum seals match. No new branch or deployment project was created.

The five-minute ceiling is configuration/authorization-tested; the new live fault was sixty seconds. Longer availability/database interruptions can still stop load through its independent safeguards. Existing CPU containment, database opt-in, proxy routing and untested-platform limitations retain their earlier verdicts.
