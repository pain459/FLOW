# PulsePay Dashboard Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline and test-driven development. A final independent review checks the complete change.

**Goal:** Deliver a working operator dashboard connected to the existing FastAPI laboratory.
**Architecture:** Same-origin static UI; bounded PostgreSQL read models; optional independent health/report intake; existing financial endpoints for writes.
**Tech Stack:** Python/FastAPI/async SQLAlchemy; HTML/CSS/native ES modules; Docker Chromium/Playwright.
**Spec:** `docs/superpowers/specs/2026-10-10-dashboard-design.md`.

## Global constraints

- Docker-only runtime/tests, non-root application, no Docker socket or external frontend assets.
- Integer minor units; dashboard JSON money as exact decimal strings. No ledger mutation outside existing services.
- Read-only independent verifier; missing/stale evidence UNKNOWN. Baseline financial API contracts/tag unchanged.
- Native implementation in current repository; authorized scope includes the UI and necessary bounded read APIs.

## Review focus

- Amounts above JavaScript's safe-integer range must retain exact digits through display/submission (tasks 1/2/3).
- Response lost after commit must retry the original key/payload without a second debit, including reload (tasks 2/3).
- Database/signals outage must label retained data stale/UNKNOWN and never show a fresh healthy zero (tasks 1/3).
- Arbitrary account refs/errors must render as text, not HTML; rapid searches must not let older replies replace newer results (tasks 2/3).
- Long lists and narrow screens must preserve bounded queries, keyboard dialog access and usable scrolling (tasks 1/3).

## Task 1 — Read models and static delivery

Files: `application/dashboard_service.py`, `schemas/dashboard.py`, `api/v1/dashboard.py`, `main.py`, `shared/config.py`, `tests/integration/test_dashboard.py`.

Interfaces: GET `/api/v1/dashboard` => currency/observed_at/totals/activity/recent_transfers; GET `/dashboard/accounts` and `/dashboard/transfers` => items/next_cursor; GET `/dashboard/accounts/{id}/ledger` => string-money ledger page; GET `/dashboard/transfers/{id}` => transfer/event/ledger/correlation; GET `/dashboard/signals` => bounded optional verification/activity observations. `/` and `/ui/*` serve the dashboard.

- [x] Write tests asserting exact snapshot totals, cursor boundaries, search, BIGINT string precision, details and UNKNOWN/stale signals; observe missing endpoints FAIL in Docker.
- [x] Implement readonly SQL services, typed response models, fixed-target optional signal intake and routes; add static shell route and config.
- [x] Run focused and full Docker suite; record actual outcomes.

## Task 2 — Dashboard and write flows

Files: `ui/index.html`, `ui/styles.css`, `ui/api.js`, `ui/app.js`.

Interfaces: native modules consume task 1 read APIs and existing POST `/accounts`, POST `/transfers`; `api.js` retains exact integer tokens and pending idempotent intents.

- [x] Write browser assertions for live read cards/tables, dialogs, exact amount and response-loss retry; observe absent UI behavior FAIL.
- [x] Build four responsive views, flow/chart, account/transfer drawers and safe write dialogs. Add poll/pause/error/stale and fresh verification states.
- [x] Run browser workflow against isolated DB/real HTTP; inspect desktop/mobile screenshots and fix observed failures.

## Task 3 — Docker browser gate, documentation and review

Files: `Dockerfile.browser-tests`, `compose.yaml`, `Makefile`, `tests/ui/test_dashboard_browser.py`, `docs/dashboard.md`, README/API/acceptance docs, `artifacts/dashboard/`.

- [x] Add opt-in Chromium runner using matched Playwright package/image; no host dependencies. Browser fixtures use isolated existing lab fixture databases and independent verifier reports.
- [x] Exercise real writes, lost-response/reload retry, optional signal outage, API outage, long refs/text safety, responsive layout and keyboard dialogs. Save screenshots/diagnostics.
- [x] Run full standard suite, lint/types, browser gate and real deployed dashboard smoke; update evidence and link UI startup URL.
- [x] Request final readonly review, fix material findings with regression tests, preserve the original baseline tag and report the working dashboard.

## Execution ledger

- Existing repository clean at `f06bec3`, baseline tag preserved. User authorized adding dashboard to the existing lab. Same-origin native assets selected to avoid extra frontend runtime.
- Shared-interface review: read models use string money; write helper submits exact integer JSON with the same retry intent. Optional signals never control core transactions. No conflicts found.
- API RED: five absent read-model tests failed; implemented bounded SQL and report intake. Browser RED: four missing-interface tests failed. Final Docker image regression 53 passed; browser workflows 7 passed; Ruff/format/mypy passed. Opt-in live observability passed separately.
- Review fixes: persisted intent before every POST (storage-failure regression), contradictory reports rejected as UNKNOWN, genuine UNKNOWN counts retained, delayed create replies guarded by dialog generation. Second review found no material remaining issues.
- Live checks: five screenshots captured and visually inspected at desktop/mobile sizes; verifier PASS, activity HEALTHY, no browser errors. Internal HTTP required secure random UUID fallback; regression and live capture passed.
- Live UI exposed baseline heartbeat timestamp binding defect; worker-principal regression reproduced asyncpg string/datetime mismatch. Fixed conversion; final live reports show relay and consumer HEALTHY with fresh timestamps. All artifacts and limits documented in docs/phase1-acceptance.md.
