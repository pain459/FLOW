# Call investigations implementation plan

> **For agentic workers:** Use superpowers:executing-plans; implement inline on the existing branch. No branch/worktree, commit, push, reset, or fault injection is required.

**Goal:** Select an actual HTTP call in Investigations and ask Laya for a bounded, evidence-linked suggestion only on explicit request.

**Architecture:** Reuse the current API completion logs, Loki, Tempo, evidence-reader, controller, durable decision schema and investigation UI. Add bounded call lookup and call-time measurement projection behind the existing trust boundaries. Keep inference and diagnostic permissions unchanged.

**Tech Stack:** Existing Python/FastAPI/Pydantic/asyncpg/Alembic, vanilla JS/CSS, Docker, Loki/Tempo/Prometheus and pinned Laya.

**Spec:** `docs/superpowers/specs/2026-10-12-call-investigations-design.md`.

## Global constraints

- Laya analysis only on explicit Explain/Re-analyze or existing explicit replay/CLI actions.
- All runtime/testing in Docker; retain existing resource ceilings and branch.
- No fault injection or financial data reset; no autonomous diagnostics/remediation.
- IDs and fault ground truth excluded from model input; preserve exact-input validation and sealed exports.
- Existing financial routes, CLI, replay/history and artifacts remain compatible.

## Review focus

- Reused request IDs must not merge separate retry attempts or asynchronous effects.
- A recovered dependency must not replace the measurements available at the selected call time.
- Failed telemetry lookup must not become an empty healthy inventory or successful diagnosis.
- Concurrent requests and cancelled inference must not create additional model work.
- Cookie transport, trace attributes, arbitrary route/log text and linked URLs must preserve existing safety boundaries.

## Tasks

### Task 1: Complete request records

Files: `apps/pulsepay/main.py`, `shared/logging.py`, transfer/worker correlation metadata; tests `tests/unit/test_call_records.py`.

- [x] Write tests for one completion per success/rejection/exception/timeout, distinct attempt IDs and safe fields; run RED in the tests container.
- [x] Emit generated call ID, stable route template, status, UTC timestamps/duration and registered error signals in one finally-path record; propagate call ID in event metadata.
- [x] Run the focused tests GREEN; record command/output.

### Task 2: Read-only call evidence

Files: new `decision_engine/models/calls.py`, `adapters/calls.py`, `adapters/call_metrics.py`; extend evidence gateway. Tests `decision_engine/tests/test_calls.py`.

Interfaces: `list_calls(query, client=None) -> dict`, `call_detail(call_id, client=None) -> dict`, `call_state(detail, client=None) -> LiveModelState`; fixed internal gateway/client methods list/detail/state.

- [x] Test metadata projection/pagination, absent sources, trace hierarchy, precise async correlation, historical metrics and canary redaction; run RED.
- [x] Implement fixed GET-only bounded Loki/Tempo/Prometheus reads; historical query time is the selected call completion; no current health enters model state.
- [x] Run focused contract tests GREEN.

### Task 3: Authorized, deduplicated on-demand analysis

Files: API auth/call routes, controller/store, forward-only decision migration `di0003`; tests `decision_engine/tests/test_call_integration.py`.

Interfaces: GET calls/detail/trace lookup; POST `/calls/{id}/explain` with idempotency key and optional `reanalyse`; GET/POST/DELETE-equivalent session auth via GET/POST logout routes. Opaque call analysis references persist independently of model observations.

- [x] Test browsing zero inference, explicit click one inference, duplicate reuse, one-session Busy, saved result reuse, explicit re-analysis, missing call, auth/CSRF and no leakage; run RED.
- [x] Implement database-serialized admission/ref persistence and frozen call-state collection. Preserve bearer CLI compatibility and sealed exports.
- [x] Run integration tests GREEN against isolated decision test DB.

### Task 4: Calls workspace

Files: existing Investigations HTML/JS/CSS and browser tests. Preserve financial UI.

- [x] Update browser checks to the approved workflow: auth once, list/detail/trace, no automatic analysis, explicit Explain, saved history/replay and responsive rendering.
- [x] Replace the questionnaire landing with Calls, History and Recorded replays, safe DOM rendering, evidence/unknowns and explicit Laya actions.
- [x] Execute browser tests in Docker; save screenshots and network/inference counts.

### Task 5: Release verification and operations

- [x] Build/restart only affected services in the existing stack; migrate decision schema through Docker.
- [x] Run decision suite, application suite, load/chaos regression suites, relevant browser suite and independent verifier; preserve real outputs under `artifacts/phase4/call-investigations/`.
- [x] Perform a real harmless HTTP call and one explicitly requested Laya demonstration; export sealed evidence; review changes independently.
- [x] Update operations/acceptance/docs with actual outcomes, limitations and exact commands.

## Progress ledger

Preflight: clean repository, branch `feat/pulsepay-dashboard`, HEAD `f4233d5`; user approved the design and explicitly requested execution. Existing stack running. No additional services/resource ceilings needed. Tests will fail before implementation for each new behavior.

Completion: all five tasks implemented and verified in Docker. Final decision tests 103 PASS; application 66 PASS/22 gated skips; workload 66 PASS; chaos safety 157 PASS; explicitly enabled browser/deployed-call checks 13 PASS. Independent verifier: all 12 checks PASS and zero violations. Schema `di0003` applied; only affected processes recreated with unchanged resource limits. Review findings were reproduced with failing checks and corrected; fresh exported trace tests exposed and fixed the middleware/OTel UUID mismatch. One explicit final CPU inference, zero automatic browsing inference, saved reuse and shared-trace transfer/replay/event correlation were observed. Fourteen sealed session files, exact SDK input and secret-value scan verified. Documentation and actual outputs are in `docs/call-investigations.md`, the additive release section of `docs/phase4-acceptance.md` and `artifacts/phase4/call-investigations/`. No faults, resets, new branch or autonomous diagnostics. Diagnostic accuracy is not qualified; the real model proposal was unsupported and safely withheld.
