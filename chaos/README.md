# PulsePay framework experiments

Chaos Toolkit sequences the native YAML in `experiments/`; pinned Pumba jobs inject container, network and resource faults. Optional Toxiproxy changes only explicitly routed clients. There is no custom experiment engine or autonomous decision system.

`make up` starts PulsePay, idle Locust at localhost:8089 and **Chaos Workbench at localhost:8090**, with the reviewed gateway and independent watchdog in the same stack. No traffic or fault starts automatically. Workbench links from PulsePay and offers scenario selection, native preflight, confirmed Run, Abort/restore, history and evidence. Use the existing Load & Capacity Grafana dashboard at localhost:3000. Keep measured HTTP load running before, during and after experiments.

```sh
make status
make verify
make load-run PROFILE=nominal
# In another terminal, after at least 15 seconds of measured stable reads/writes:
make chaos-list
make chaos-validate SCENARIO=002-worker-pause
make chaos-preflight SCENARIO=002-worker-pause
make chaos-run SCENARIO=002-worker-pause
make chaos-report
make chaos-abort
make chaos-restore
```

`chaos-validate` validates without starting the authorization/watchdog services. First build with `docker compose -f compose.yaml -f compose.chaos.yaml build chaos-runner`. Subsequent commands can use `CHAOS_IMAGE_PREBUILT=true`. `chaos-preflight` creates only bounded read-only/dry-run helpers, including a `tc` capability probe in its own isolated loopback namespace. It never pauses an application target. Pumba's dry-run still waits its configured duration.

Database interruption requires explicit `ALLOW_DATABASE_CHAOS=true` for both the operator invocation and gateway configuration. The gateway independently enforces this; a runner cannot grant itself permission. Proxy scenarios require a deliberate opt-in routing overlay, documented in [operations](../docs/phase3-operations.md).

Evidence is retained in `chaos-evidence` and exported to `artifacts/chaos/<run-id>/`. A framework journal, zero exit code or later health alone cannot establish PASS: required method and rollback activities, actual impact, restored target state, same fresh active workload and full independent verification must all agree. Recovery after workload removal is explicitly recorded and cannot PASS a sustained-load hypothesis. Final files have SHA-256 checksums. Later recovery acknowledgements are additional evidence and do not rewrite the original verdict.

Only the private authorization gateway mounts the local Docker socket. Its authority volume is absent from Workbench/runner and read-only to the watchdog. Pinned helpers cannot mount host paths, choose arbitrary commands/targets, delete volumes or affect unrelated containers. Its watchdog has a separate authenticated private listener and cannot be blocked by a frozen runner's lock. Browser actions require local same-origin session/CSRF checks and reviewed IDs. Abort cancels its browser job, invokes native abort and verified restore/report/release, and blocks new starts until it finishes. This is a trusted local synthetic lab boundary; Docker administrators remain trusted.

After experiments, use `make chaos-stop` and `make load-stop`. These retain the application, idle Locust UI, data volumes and reports. Runtime limits and supported-platform/capability evidence are in [acceptance](../docs/phase3-acceptance.md).
