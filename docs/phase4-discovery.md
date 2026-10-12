# Decision intelligence integration inventory

Discovery: 2026-10-12, branch `feat/pulsepay-dashboard`, source commit `94cfb14`.
The checkout was clean. No branches, resets, or existing evidence were changed.

| Contract | Actual implementation | Integration |
|---|---|---|
| Readiness authority | `docs/audits/phase3-completion.md`, `artifacts/baseline/readiness-v1/gates.json` | Supported qualification 26 PASS / 1 unsupported; shadow GO; autonomous read-only NO-GO |
| Application | Compose `api:8080`, `/health/ready`, localhost 8080 dashboard | Preserve business code and routes |
| Invariants | `verifier.main --once`, separate `pulsepay_verifier`, RR READ ONLY | PASS/FAIL/UNKNOWN, exit 0/1/2 |
| Workload | `locust`, localhost 8089, `scripts/load-run.sh`, `load-reports` | Operator-controlled, no automatic traffic |
| Framework | Chaos Toolkit 1.21.4, Pumba 1.2.1, optional Toxiproxy 2.12.0 | Independent of decision service |
| Public evidence | `observation-feed:8091/api/v1/observations/{opaque-id}/sequence`, schema 1.1 | Only sanitized, timestamped observations |
| Public offline captures | `artifacts/baseline/readiness-v1/public-observations/` | Read-only mount, no parent baseline mount |
| Evaluator truth | `readiness-v1/runs/*/ground-truth.json` | Separate one-shot evaluator only; never controller/model |
| Monitor | Prometheus 9090, Loki 3100, Tempo 3200, Grafana provisioned dashboards | Raw operator endpoints withheld from inference |
| Networks | internal, edge, chaos-control, investigation, optional proxy-control | Model isolated on decision-model; controller on investigation + decision-store + decision-model + decision-ui; credential-free ingress bridges decision-ui to localhost |
| Privileged controls | `docker-gate` sole socket holder; watchdog independent | No decision component on chaos-control, no control mounts |
| Core migrations | Alembic public version exactly `0002` required by API/verifier | Separate decision schema/version table prevents changing financial marker |
| Runtime | Docker Desktop Linux ARM64, CPU only | No claims for native Linux/WSL2/GPU |

The named Phase 3 specification/checklist files are absent; the supplied user specifications, repository contracts and completed audit are authoritative. Application containers were stopped at discovery; the first verifier returned UNKNOWN (DB DNS unavailable), rather than PASS. Existing Compose startup was requested without wiping volumes.

Official Laya PyPI release verified: **0.4.3**, wheel SHA-256 `1cd9c33ab0b2b12f0122e6bf643fb4ead70309983ffb68f8db854d7a8f412d50`. Retrieved wheel source confirms `Router(device=..., max_loaded=1, revision=...)`, `predict(state, questions, model=..., max_len=...)`; upstream HTTP is `/v1/systemone`. Project wraps this SDK behind its own bounded provider endpoint and strict answer normalization. `choice` includes probabilities; `score` is an expected ordinal value; `noul` is P(true). Sources: [official question contract](https://github.com/NandhaKishorM/laya/blob/main/docs/questions-and-answers.md), [official Docker guidance](https://github.com/NandhaKishorM/laya/blob/main/docs/docker.md). Local wheel metadata/source retained under `artifacts/phase4/discovery/`.

Initial CPU checkpoint: `convaiinnovations/laya-multilingual`, immutable revision `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67`. Provision once into a named cache; runtime is offline. Read-only execution remains gated off. Historical snapshots are assessed against their recorded observation time, not misrepresented as fresh live data.
