# Investigating an HTTP call

Open **Investigations** at http://127.0.0.1:8092/. The default **Calls** tab shows real PulsePay API attempts. Generate requests with the ordinary dashboard or Locust, choose a recent call, and inspect its HTTP outcome, execution path and correlated events. The financial dashboard remains focused on accounts, balances and transfers.

Browsing, changing filters, selecting a call, refreshing evidence, opening measurements and viewing history perform read-only telemetry requests. **They never invoke Laya.** Sign in once using the generated `DECISION_API_TOKEN` from your local `.env`, then press **Explain this call** when you want an analysis. Only one call analysis is admitted at a time. A saved result opens without inference; **Re-analyze** explicitly requests a new result. Active saved analyses continue polling their status after reopening, without starting additional inference. Cancellation stops the investigation, not any load or experiment.

The response separates observed facts from possible explanations, shows alternative scores, states missing evidence and suggests a human investigation. It executes no diagnostics or remediation. An answer can be inconclusive; scores are not calibrated probabilities of a confirmed cause. Chaos scenario names, commands, targets and fault truth are not available to Laya.

## Finding and understanding calls

Use the time window, outcome and endpoint filters. **Older calls** pages through metadata; filters apply before inference and do not invoke it. **Open by trace ID** accepts an actual lowercase 32-character W3C trace ID and selects matching calls. Several attempts can share a request ID or trace; each has a separate generated `X-Call-ID`. The timeline selects the exact call's tagged span and descendants rather than combining every span in a shared trace.

The execution path uses safe operation labels, parent relationships, durations and error signals. Full trace/log links open the provisioned Grafana sources. Outbox publication and consumer processing are shown as asynchronous follow-up events, with their related trace IDs. Independent worker traces retain separate boundaries; use Grafana to inspect their full hierarchy. A committed transfer's replay is a separate HTTP attempt and does not inherit the original attempt's publication effects.

Expand **System measurements at this call's time** to inspect the preceding 30-second historical window. Laya receives a frozen projection at the selected call's completion, with source freshness and missingness. Current recovery cannot replace evidence from the earlier call. Events/spans completed later are excluded from that call-time model input. IDs, raw log text, SQL, bodies, route strings, credentials and arbitrary span attributes are discarded from model input. Full sanitized observations and the exact compact SDK input remain auditable.

This inventory requires the existing Loki/Tempo/Prometheus services. Metadata starts with this release; older records lacking call metadata are unavailable. Calls are discoverable for up to 24 hours, within telemetry retention. Requests that never reached the API have no server completion record. Missing/delayed logs or traces are **UNKNOWN**, not healthy. Each page returns at most 50 calls; equal-timestamp cursor exclusions are bounded to 100 IDs, with an explicit unknown/limit notice if exhausted. Narrow filters in that case. Saved decisions remain available in **History** after telemetry expires.

## Docker operations and interfaces

```sh
make up
make intelligence-status
make intelligence-test
make intelligence-export
make verify
```

The usual `make up` provisions the decision roles, applies the forward-only decision migration and starts the existing investigation services. This release adds `di0003` for opaque call-to-analysis references; the financial schema remains `0002`. There are no additional services. Existing caps remain: Laya **3 GiB / 2 CPUs**, controller **384 MiB / 0.5 CPU**, reader and UI each **128 MiB / 0.25 CPU**.

Public interfaces under `/api/v1/intelligence`:

| Method / path | Behavior |
|---|---|
| `GET /calls` | Bounded inventory: `lookback_seconds`, `limit`, opaque `cursor`, registered `route`, `outcome`, optional `trace_id` |
| `GET /calls/{call_id}` | HTTP facts, exact trace branch, safe logs/events, saved analysis and fixed Grafana links |
| `GET /calls/{call_id}/measurements` | Historical read-only measurements; no inference |
| `POST /calls/{call_id}/explain` | Authorized explicit analysis, mandatory `Idempotency-Key`, body `{}` or `{"reanalyse": true}` |
| `GET /investigations/{id}/timeline` | Saved model answer, policy, evidence, distributions and call-time context |
| `POST /auth/session` | Same-origin operator token exchange for an eight-hour HttpOnly, SameSite=Strict cookie |
| `GET /auth/session`, `POST /auth/logout` | Authorization state / local sign-out |

Unknown query/body fields, unsafe filters and non-boolean re-analysis flags return 422. Busy analysis returns 429; an unobserved call returns 404. Cookie mutations require same-origin headers; existing bearer CLI authorization remains supported. No token is stored in browser local/session storage. The retained `/ask` API/CLI, recorded replays and existing session exports remain compatible; the questionnaire is deprecated in the default screen.

Release evidence is under `artifacts/phase4/call-investigations/`. Model-selected diagnostic execution remains disabled. Real inference checks establish the interface and safety properties, not diagnostic accuracy or complete autonomous investigation qualification.
