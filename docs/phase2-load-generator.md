# PulsePay workload operations

PulsePay's dashboard, financial services and workload tools form one application lab. Historical specification filenames remain for traceability; runtime images, UI and dashboards use PulsePay names.

## Start and run

Docker Engine/Desktop and Compose are the only runtime prerequisites. Existing setup remains `make bootstrap; make up; make seed`. `make up` includes observability; traffic remains idle until an explicit workload command.

```sh
make status
make verify
make load-preflight PROFILE=nominal
make load-smoke
make load-run PROFILE=write_heavy
make load-run PROFILE=nominal DURATION=120 WARMUP=30 USERS=20 RATE=20 WORKERS=2
make load-stop
make load-report
make load-test
make load-ui
```

Select smoke, low, nominal, read_heavy, write_heavy, burst, hot_accounts, step_ramp, soak, journeys, or the explicit dependency_recovery policy. Overrides are validated before traffic. Burst/step durations scale proportionally; USERS caps every declared stage. RATE controls logical-operation pacing, not guaranteed HTTP RPS. Multi-hour selection requires `ALLOW_LONG_RUN=true`. Runs never seed automatically; there is no background traffic client.

The optional overlay is `compose.load.yaml`. Normal `docker compose up` does not start it. Its one-shot non-root, readonly controller container has a writable reports volume, 1 CPU/768 MiB defaults, no Docker socket and no external targets. Headless commands do not publish ports. The ordinary stack already publishes the persistent UI on localhost:8089. WORKERS uses Locust 2.46.6 local master/worker processes; scaling shares this ceiling. LOAD_CPU_LIMIT and LOAD_MEMORY_LIMIT configure it explicitly. The generator's /metrics endpoint on 9101 is internal only; Prometheus scrapes its Compose alias while a run exists. A down load scrape while idle is expected.

## Locust in the application stack

`make up` starts the persistent Locust service at **http://127.0.0.1:8089**. It is idle until Start; stopping traffic keeps the web UI available. `make load-ui` ensures that service is running. Enter users and spawn rate, retain `http://api:8080`, leave the runtime field blank, and click Start. Each Start checks funded accounts, dependency health, independent integrity and the shared execution lock before sending financial requests. One finite session uses one local worker.

Configure `LOCUST_PROFILE=nominal`, `LOCUST_DURATION_SECONDS=600`, `LOCUST_WARMUP_SECONDS=30`, and `LOCUST_UI_PORT=8089` in `.env`, then recreate the service with `docker compose up -d locust`. Users can be adjusted within the profile cap. Stop in Locust or use `make load-stop`. No automatic breathing traffic remains.

Manual sessions retain typed outcomes, histograms, CSV and independent pre/post verifier reports in the shared reports volume. Their benchmark verdict is INCOMPLETE because user-controlled scheduling and partial environment observations are not a qualified comparison. Integrity is reported independently. Use `make load-run` for reproducible headless measurements; its one-shot controller is independent of the persistent idle UI, and both share an exclusive traffic lock.

See [resource ceilings](resources.md). All Locust processes are bounded; a fail-closed supervisor and independent finite watchdog stop sessions even if reporting fails. Disk failure retains the recovery pointer and releases the lock.

## Lifecycle and artifacts

The controller persists CREATED, VALIDATING, PREFLIGHT, READY, WARMUP, RUNNING, STOPPED, COOLDOWN, VERIFYING, REPORTING and terminal status. A guard container reserves the operator workflow before traffic starts; the controller also holds a file lock. Finite Locust runtime, bounded requests/inflight shutdown and Docker PID isolation bound traffic even if the controller disappears.

`make load-stop` persists cancellation, stops new traffic, and waits for a retained terminal report. Its finite wait is derived from the validated profile: `115 + 2 × cooldown_seconds + reconciliation_seconds` seconds, at most 595 seconds. This includes final verification and bounded outcome recovery. If no report appears before that limit, it fails with a STOPPING message; cancellation remains persisted and completion is not claimed. It never stops PulsePay. Interrupted runs are not benchmarks. After a crash, reporting or a subsequent locked controller marks abandoned evidence INTERRUPTED with unknown postflight evidence. If an operator wrapper was killed without cleanup, remove only its scoped reservation/resource helper containers after confirming traffic stopped; do not prune Docker:

```sh
docker rm -f chaosloop-load-guard chaosloop-load-resources
```

Every run has immutable profile/hash in manifest.json, summary.json/md, measured locust-stats.csv, native locust-all CSVs, time-series.json, exact verifier-pre/post JSON, bounded errors.jsonl, lifecycle/workload events, worker evidence and container-resources.jsonl. Raw artifacts are gitignored and never silently rotated. Exported reports survive container removal. `make down` retains both database and load reports volumes.

Transfer intentions are fsynced to per-worker append-only `intent-journal/*.jsonl` before HTTP submission. Storage is capped at 32 MiB per worker, four workers, 2 KiB per record and 50,000 intentions per reconciliation. The existing report-volume budget also applies. Storage failure stops traffic; malformed or incomplete records produce UNKNOWN. Terminal commit evidence requires a valid transfer UUID.

After inflight completion and an independent verifier barrier, `reconciliation.json` records read-only original-key/hash lookups. Only a valid full 404 error envelope and a PASS barrier permit one replay of the original key/body. Recovery requests have a total 1–120 second budget and 16 KiB response ceiling, including trickling headers and bodies. Recovery writes are followed by another cooldown and verifier. Recovered outcomes are counted separately from measured commits/RPS/latency; HTTP failures remain failures. Legacy runs without durable intentions cannot be retroactively resolved.

The intentionally selected `dependency_recovery` profile caps users at 20 and duration at 600 seconds. Its uncertainty deadline is 20 seconds after an UNKNOWN observation; the evidence remains UNKNOWN. A separate deadline watcher stops traffic even while verifier communication waits, and expiry cannot be cleared by a late PASS. Periodic verification and its communication timeout remain separate bounds. Proven FAIL stops immediately. Other profiles retain zero grace and the ordinary error threshold. This policy supports bounded fault-recovery tests and cannot turn an outage into a healthy benchmark.

The HTTP client retires connections after four seconds of idle time, before the API's configured five-second keep-alive expiry. This prevents a connection-reset race when 100 users are paced at 20 logical operations/sec. Shorter idle periods still reuse connections. Transport failures remain failed requests: real Requests timeouts use `timeout`, while resets/disconnects use `infrastructure_failure`. Bounded error samples retain a controlled `error_class`, and transfers keep their original idempotency key/body on every retry. Historical reports are unchanged; no reset is silently retried inside the HTTP adapter.

## Healthy-state qualification

Qualification builds the generator once and pins a retained `pulsepay-load:qualified-<UTC>` image for every repetition/trial. This keeps exact image provenance stable even when a Docker build's attestation metadata would change image IDs with cached layers. LOAD_IMAGE and LOAD_IMAGE_PREBUILT=true can deliberately select an already built image for reruns; its actual image ID and source hash are still checked and recorded.

`make load-qualify` deliberately creates the separate fixed `chaosloop-load-baseline` project. It uses loopback ports API 18080, Prometheus 18090, Grafana 18000 and logging 34224. It seeds through the supported lab job, captures a database snapshot, and restores that snapshot only in this disposable project before repetitions/trials. Normal lab data remains unchanged. Snapshot restoration and Redis clearing exist solely in this qualification wrapper; workload containers perform HTTP operations only.

The wrapper refuses to replace an existing snapshot. It runs three 120-second nominal measurements after 30-second warmups, then bounded read-heavy, write-heavy, hot-account and capped burst trials. Reports and snapshots remain under artifacts/load-runs and named volumes. `RESUME_QUALIFICATION=true make load-qualify` deliberately reuses the same snapshot with new run IDs and timestamped logs; old evidence is retained. Stop the temporary project after qualification without deleting its volumes:

```sh
COMPOSE_PROJECT_NAME=chaosloop-load-baseline docker compose -f compose.yaml -f compose.load.yaml \
  --profile observability --profile load down
```

Qualification summarizes distinct matching runs with the containerized baseline command:

```sh
docker compose -f compose.yaml -f compose.load.yaml run --rm --no-deps load-controller \
  python -m load_generator.controller.cli baseline \
  --run-id load-... --run-id load-... --run-id load-...
```

No chaos operator, privileged orchestration, model decisions or autonomous remediation is included.

## Troubleshooting

Invalid YAML/limits fail before traffic. Missing funded accounts require explicit seed/setup. Readiness 503, unhealthy required workers/Redis, unknown verifier evidence or stale Prometheus stop qualification. Retryable transport failures preserve idempotency; schema errors are contract failures. Dataset depletion, missing workers, sustained infrastructure error rates and integrity failures stop safely. Unwritable reports fail nonzero before traffic. Generator saturation or incomplete resource/telemetry evidence produces INCOMPLETE, preserving performance separately from financial correctness. Partial crash evidence is retained.

## Future observation and abort contract

Schema v1 manifest identifies run ID, immutable profile hash, dataset/config/image revisions and exact UTC boundaries. events.jsonl and workload-events.jsonl identify warmup/running/target stage/cooldown/stopped transitions. latest-observation.json contains timestamped throughput counters, user counts, latency histograms, transfer outcomes, generator health, resource values and missing signals. Verifier artifacts reference independent business evidence. The cancel file/stop CLI is deterministic and independent of any future decision model. These are observation/abort contracts only.


The native Locust form's Profile field is a session label; leave it blank when following the documented workflow. The versioned workload mix is selected by LOCUST_PROFILE on the persistent service, or PROFILE on `make load-run`. Native users/spawn controls change concurrency within that mix.
