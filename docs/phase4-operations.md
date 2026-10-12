# Investigation operations

Docker/Compose and the existing local `.env` are required. Work stays in the `chaosloop` project. Tested host: macOS Docker Desktop, Linux ARM64, CPU. Windows/WSL2, native Linux and GPU are NOT_RUN. Inspect [resource ceilings](resources.md) before provisioning: inference is capped at 3 GiB/two CPUs; controller at 384 MiB/0.5 CPU; ingress at 128 MiB/0.25 CPU.

```sh
make intelligence-setup  # Generates only missing private credentials, migrates decision schemas, downloads/reviews cache once
make up                  # Whole stack, including idle Locust/Workbench and shadow investigation console; no automatic traffic/faults
make intelligence-status
make intelligence-test   # Separate disposable pulsepay_decision_test DB; never financial baseline data
```

Open **http://127.0.0.1:8092/** or the PulsePay sidebar's Investigations link. Enter the local `DECISION_API_TOKEN` from your private `.env`. **Ask Laya now** accepts a recent error/trace excerpt, request ID or trace ID and returns one suggestion using fresh system measurements and correlated call evidence. You can also select an opaque recording and start a shadow replay. The token is used for authenticated POSTs and is never saved in browser storage or report artifacts. The console shows observation quality, subsystem probabilities, ordinal severity/P(true), model recommendations, policy overrides, rankings, evidence and frozen rules decisions. Hypotheses are not confirmed causes; autonomous tool execution remains disabled. See [manual questions](phase4-live-questions.md).

`make up` never downloads weights. On a new machine, run `make intelligence-setup` first. An absent, changed or incompatible cache leaves inference UNAVAILABLE, with an honest health response. The separate setup job is the only intended downloader. Do not run provisioning while the provider is actively using its cache. Runtime reload verifies the pinned configuration and weights, even after offline restarts.

```sh
docker compose -f compose.yaml -f compose.phase4.yaml --profile intelligence --profile chaos --profile observability config --quiet
docker compose -f compose.yaml -f compose.phase4.yaml exec -T incident-controller python -m decision_engine.cli list
make intelligence-ask
sh scripts/phase4/ask.sh --request-id <actual-request-id>
make intelligence-replay DATASET=dataset-c89adf888d98c954
docker compose -f compose.yaml -f compose.phase4.yaml exec -T incident-controller python -m decision_engine.cli replay --qualified
make intelligence-report # Evaluator-only comparison; nonzero for missing/incomplete evidence
make intelligence-export # Copy sealed sessions into artifacts/phase4/sessions; refuse differing overwrite
make verify
make status
make down                # Includes model/controller/ingress; retains all named volumes
```

The API namespace is `/api/v1/intelligence`: health, datasets, tools, ask, replays, investigations, investigation detail/timeline and authenticated cancellation. POST start requires Bearer authorization and `Idempotency-Key`; same request/key returns the original session, changed content conflicts. `mode=readonly` returns 423. No infrastructure-control endpoint exists. API docs are available only on the internal controller; published ingress serves fixed console/API paths and blocks arbitrary URLs.

Source recordings are immutable sanitized files; session history is PostgreSQL and `chaosloop_decision-evidence`. Every sealed export contains input hashes, actual provider/version, question/policy identifiers, raw validated answers, normalization, policy/rankings, paired baseline, source references, metrics, conclusion and checksums. Failed/interrupted records remain visible. An unsealed partial export remains on the evidence volume and is counted as partial, never a completed evaluation. Evaluator outputs are separate local `artifacts/phase4/evaluations/<id>/` files and DB records accessible only with evaluator privileges.

To stop a replay, use its console Cancel button or authenticated `POST /api/v1/intelligence/investigations/<opaque-session-id>/cancel`. Cancellation affects the investigation only. It never cancels load, faults or restoration. Interrupted controller sessions escalate on startup; source hash may be UNKNOWN for incomplete restart exports. Reports survive service recreation. Stop and restart just the model with Compose when inference exceeds its deadline indefinitely; readiness is then UNAVAILABLE, later callers receive safe rejection and no diagnostics execute.

```sh
docker compose -f compose.yaml -f compose.phase4.yaml restart laya-service
make intelligence-status
```

Retention is operator-managed: no evidence or cache is silently deleted. Keep model/cache, evidence-volume and PostgreSQL disk usage within available Docker storage. Archive exported bundles explicitly before choosing any deletion. The guarded `CONFIRM_RESET=chaosloop make reset-lab` deletes this entire disposable lab's named volumes, including model cache and investigation history; it was not executed during implementation. A normal `make down` preserves them.

Live read-only investigation remains blocked by [the dependency audit](audits/phase3-completion.md). Qualifying the isolated diagnostic executor, new real diagnostic evidence and approved operating mode are separate follow-up work. No fault injection was run for this implementation. Existing operator load/chaos commands remain independent.
