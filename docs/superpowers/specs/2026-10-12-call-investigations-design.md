# Call-focused investigations

Approved in conversation: a separate Investigations workspace, reached from PulsePay, for understanding individual HTTP calls. The user approved implementation after requiring strictly on-demand Laya analysis.

## Operator flow

The existing localhost:8092 console opens on Calls. The operator filters recent requests, selects a call, sees its outcome and execution timeline, and explicitly presses **Explain this call**. Browsing, selection, refresh, trace lookup, history, and incident detection never invoke the model. Saved answers reopen without inference; **Re-analyze** is a separate explicit action. History and recorded replays remain separate tabs. The old questionnaire leaves the default interface; its API and CLI remain compatible.

The financial transaction UI keeps its existing business focus. Grafana remains available for full traces/logs. A trace-ID shortcut selects an observed call; it never starts analysis automatically.

## Evidence and identity

Each server HTTP attempt emits one bounded structured completion record containing a generated call UUID, route template, method, start/completion timestamps, duration, HTTP status, registered error code/class, request ID and trace ID. No request bodies, account balances, credentials, raw URLs or idempotency keys enter this record. Retried attempts have distinct call IDs even if request IDs repeat. A call ID is propagated through existing outbox trace metadata for precise asynchronous correlation.

Loki supplies the bounded, paginated recent-call inventory; Tempo supplies bounded span hierarchy. Only documented operation names, registered errors, IDs, times and durations are displayed. Follow-up event traces are labelled asynchronous and correlated explicitly; absent evidence is UNKNOWN. Older logs lacking completion metadata and client failures that never reach the API cannot be represented as complete server calls.

Evidence for an analysis is frozen at the selected call's completion time. Historical Prometheus queries evaluate a preceding 30-second window. Current health is shown separately and never used to explain a past call. Source freshness is evaluated relative to that window. Missing historical verifier/metrics remain UNKNOWN. Raw IDs, route strings, trace attributes, logs, fault labels and control-plane metadata never reach inference. Existing compact model input and SDK truncation checks remain in force.

## Authorization and bounds

Operator authorization is entered once per browser session, exchanged for an expiring HttpOnly, SameSite=Strict signed cookie. State-changing cookie requests enforce same-origin checks. Existing bearer-token CLI authorization remains. No token is stored in browser storage or exposed in logs. The console never executes model-selected diagnostics or remediation.

Only one inference-bearing session is admitted at a time for operator call analysis; other requests receive Busy. Database serialization prevents duplicate clicks and accidental concurrent sessions. Call-to-session references survive restarts, and a repeated request reuses its saved result unless explicitly requesting re-analysis. Existing CPU/memory limits and single-inference model gate remain unchanged. Reads and evidence collection are bounded and read-only.

## Verification

Docker tests prove completion logs cover success, rejection, timeout and exceptions; retry identities differ; telemetry failure is explicit; evidence timestamps and redaction are preserved; historical queries cannot use future health; browsing performs zero inference; a click performs exactly one; duplicates, Busy, cancellation, cached results and re-analysis are safe; cookie authorization rejects cross-origin requests. Browser tests cover call selection, traces, result/history navigation and mobile layout. Existing application, load/chaos safety and decision tests plus independent ledger verification guard regressions. Real inference is a functional demonstration, not evidence of diagnostic accuracy.
