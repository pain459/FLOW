# Manual first-response questions

The operator can ask Laya about a call while PulsePay is running, whether or not an experiment exists. This extends the approved suggestion flow; it does not grant autonomous diagnostic execution or infrastructure control.

Open `http://127.0.0.1:8092/`, enter your local `DECISION_API_TOKEN`, and use **Ask Laya now**. Supply an error/trace excerpt, a response's `X-Request-ID`, a 32-character lowercase W3C trace ID, or no correlation reference to inspect the current window. Request/trace lookups are bounded to 1–15 minutes; system metrics use a separate 30-second window. Re-ask after fresh evidence arrives. Each submission reserves an idempotent, durable session and makes exactly one model decision.

```sh
make up
make intelligence-status
make intelligence-ask  # Current system; no fault knowledge
sh scripts/phase4/ask.sh --request-id <actual-request-id>
sh scripts/phase4/ask.sh --trace-id <actual-32-hex-trace-id>
sh scripts/phase4/ask.sh --error 'HTTP 503 DATABASE_UNAVAILABLE'
make intelligence-test
make intelligence-export
```

The API is `POST /api/v1/intelligence/ask` with Bearer authorization and `Idempotency-Key`. Body fields are `request_id`, `trace_id`, `error_excerpt` (maximum 4,096 characters), and `lookback_seconds` (30–900, default 600). Unknown fields, URLs, unsafe correlation syntax and excessive lookbacks are rejected. Response 202 identifies a `live_question` session. Read its existing detail/timeline routes; timeline includes `first_response` after valid inference. Repeated key/payload returns the original session; changed payload conflicts. Cancel uses the existing authenticated route.

The response includes ranked reasons, uncalibrated model scores, suspected subsystem, supplied/current evidence, missing observations, severity as an expected ordinal, evidence-insufficiency P(true), and a suggested human check. A suggested reason without a matching observed symptom is withheld as insufficient evidence; the original model proposal and override remain visible. There is no confirmed-cause claim. Current metrics may show recovery while an earlier trace shows failure; historical call evidence is labelled separately. An empty or delayed trace lookup is UNKNOWN, not proof that the call succeeded.

`evidence-reader` is a protected, non-root, read-only container with **128 MiB / 0.25 CPU** ceilings, dropped capabilities, no host port, no secret/DB principal, no mounts and no Docker/chaos-control access. It accepts only validated correlation selectors. Its code permits fixed bounded **GET** reads of approved Prometheus queries, API dependency health, the independent verifier's report, selected application logs and a specific hex Tempo trace. A single collection is limited to ten seconds, six outbound connections, 100 log records, eight projected spans and bounded responses. The controller reaches this gateway on `decision-observations`; it cannot reach the raw telemetry network. Model inference retains its isolated model network, read-only offline cache and resource ceilings.

Only numeric/boolean measurements, registered error classes/codes, fixed service/operation enums and timestamps pass the reader. Log messages, SQL, raw span names/attributes, payloads, credentials, IDs and arbitrary labels are discarded. Pasted excerpts are reduced to the same controlled signals and marked **operator-reported**, never trusted live measurements. Known OpenTelemetry JSON trace excerpts can contribute bounded projected spans; unsupported text is not sent to the model. Malicious instructions and experiment labels do not become model instructions. Neither model nor controller receives a scenario ID, injector action, fault title or privileged journal. The collector never queries Workbench, Toxiproxy or Docker.

Each session preserves full sanitized observations, provenance, hashes, validated answers, policy/ranking, state transitions and sealed export. `live-input-v1` supplies a compact model input with the operator/correlated call evidence first. SDK usage must establish zero dropped tokens and no truncation for every question; missing, malformed or incomplete usage escalates rather than accepting a partial answer. The exact compact input, hash and verified token usage are exported alongside the full observation. JSONB key reordering cannot change that hash. Older errors remain HISTORICAL beside newer healthy samples, and HTTP failures are retained even when span error flags are absent. `first-response-v1` is separate from the frozen `investigation-v1` replay suite. The additive `di0002` migration permits `live_question`; it changes no financial tables or grants. `recovery_status` stays independently UNKNOWN. Manual collection is an operator-selected fixed read; every model-selected diagnostic record remains zero. This is not qualification of the autonomous executor.

Upstream failures yield explicit missingness or an escalated session. Budgets are one decision, zero model-selected tools, ten seconds for collection, fifteen seconds for inference and thirty seconds for session decisions. Busy inference, absent model cache or invalid output fails safely. The existing limitation on terminating a stuck SDK CPU thread remains: readiness fails, resource limits apply and the operator restarts the model if necessary.

Validation evidence is retained under `artifacts/phase4/live-questions/`. Existing sealed replay/evaluation artifacts and historical acceptance measurements stay unchanged. Real fault-response accuracy, diagnostic usefulness and calibrated cause confidence require separate authorized incident trials; manual interface validation does not establish those research outcomes.
