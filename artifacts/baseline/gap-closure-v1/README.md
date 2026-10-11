# PulsePay fault-readiness and recovery evidence

Captured on 2026-10-11 in the existing macOS Docker Desktop Linux arm64 lab, branch `feat/pulsepay-dashboard`, HEAD `680d097`. This bundle supplements the sealed framework-v1/workbench-v1/workload-v3 records; it never rewrites them.

The rejected user run `chaos-20261011T035003Z-005d521b` failed before injection because no active steady HTTP workload existed. Its original `failure.json` contained the safe reason, while the old browser showed only `ValueError`. Shared read-only readiness and actionable native/browser diagnostics now expose the actual prerequisite.

## Executed results

| Evidence | Actual result |
|---|---|
| Application regression | 56 passed; two live checks skipped in the default suite |
| Workload regression | 61 passed |
| Native framework/safety regression | 71 passed; upstream Starlette deprecation warning |
| Quality | Ruff PASS; 135 files formatted; mypy PASS across 88 runtime source files |
| Worker pause through Chromium under an existing workload | PASS: `chaos-20261011T051021Z-4c7c81a6` |
| PostgreSQL outage under the same sustained workload | PASS: `chaos-20261011T051149Z-4267a1dd` |
| PostgreSQL repeat on the post-review image | PASS: `chaos-20261011T054327Z-0759842d`; same load remained RUNNING, restoration and pre/post integrity PASS |
| Original recovery workload | FAILED as a healthy benchmark, correctly retaining 211 infrastructure responses; integrity pre/post PASS; all 51 measured unresolved intentions reconciled separately |
| Final-image six-minute healthy functional run | PASS: `load-20261011T053002Z-3ccb11ea`; 20.1 HTTP requests/sec, 2,869 measured commits, zero unresolved outcomes |
| Post-review 180-second recovery workload | FAILED as a healthy benchmark, retaining 226 infrastructure responses; all 66 measured ambiguous outcomes recovered, final unknown count zero and independent integrity PASS |
| CPU containment | Unsupported: bounded idle helper failed before execution with an invalid cgroup-v2 domain-controller state; no stressor ran |
| Three frozen-image nominal repetitions | PASS: median 20.175 HTTP requests/sec, p50/p95/p99 26/47/57 ms; zero measured HTTP failures or unknown outcomes; independent pre/post PASS on every run |
| Final independent handoff verifier | PASS: 83,579 transfers, 200 accounts, 20,000,000 minor units conserved, zero violations/pending events |
| Final deployment/resource boundary | One project, 17 running services, 6,016 MiB / 10.5 CPU ceilings; only gateway has socket; idle Locust and no chaos lease |
| Historical seals and credential scan | PASS: original framework/workbench bundles unchanged; no known credentials in this bundle |

`checks/` retains exact regression output and command/time/exit metadata, final health/resources and independent verifier. `runs/` retains original native journals, full workload reports, intentions and verifier evidence. `qualification/baseline.json` records three new matching nominal repetitions; their complete bundles and invocation logs are retained. Every primary measurement was 120 seconds after 30 seconds of warmup, with 20 users and a 20 logical operations/sec pacing ceiling. Achieved HTTP RPS ranged 20.1750–20.2167; p50 23–31 ms, p95 44–50 ms, p99 53–60 ms. No current-image hour-long soak or saturation claim is made. Earlier qualified performance records remain tied to their original images/data volume.

The existing workflow `RESUME_QUALIFICATION=true QUALIFICATION_NOMINAL_ONLY=true sh scripts/load-qualify.sh` exited 0 and stopped its temporary deployment automatically. Original volumes/reports are retained. A final Locust idle check was rerun alone after an overlapping smoke transfer invalidated its initial count; the unchanged test passed. That harness failure remains explicit in `checks/live-checks.json`. Source hashes identify the uncommitted build without creating a branch, commit or tag.

The new recovery path fsyncs each original intention before HTTP, validates original-key/hash lookup, and permits one same-key/body completion only after an independent PASS barrier and a valid full not-found envelope. Recovery commits stay outside measured RPS/latency/commit counts. Unavailable, malformed or truncated evidence remains UNKNOWN. Total HTTP deadlines, response ceilings, sticky independent integrity expiry and bounded Stop finalization have reproducing Docker regressions.

Older ambiguous outcomes cannot be retrospectively resolved without their original intention bodies. Native Linux and WSL2 were not available. CPU pressure stays disabled; no broader cgroup privilege was granted.

`acceptance.json` distinguishes completed fixes from these limits. `checksums.json` seals every retained file with SHA-256; the checksum verification command ran in Docker. The original sealed bundles remain untouched.
