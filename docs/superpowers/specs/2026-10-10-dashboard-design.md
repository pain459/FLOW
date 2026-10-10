# PulsePay operator dashboard

The user requested a UI connected to FastAPI to understand the working system. This extends Phase 1 with an operator interface, preserving the existing financial and worker boundaries. Implementation is authorized by that request; routine layout/technology choices are resolved inline.

## Approach

Serve self-contained HTML, CSS and native JavaScript modules from the existing API at `/`. This keeps one origin, one image and the existing port; no extra frontend runtime, external CDN or host tooling. A separate React/Vite service would add a build/runtime boundary without helping these four views; Grafana alone cannot provide an account/transfer workspace. Retain Grafana for deep metrics/logs/traces, linked from the dashboard.

## Experience

- Overview: truthful snapshot of accounts, synthetic funds, committed transfers, pending events; transaction activity chart from PostgreSQL timestamps; clickable system flow and independent verification panel.
- Accounts: bounded searchable/paginated listing, status/currency/authoritative balances, create zero-balance account, inspect cursor-paginated immutable ledger.
- Transfers: bounded recent transfer listing, source/destination refs, amount, event delivery status, details/correlation IDs and ledger pair. New transfer uses the existing atomic POST API.
- System: API/database/cache/relay/worker states with freshness/reasons, HTTP activity state, independent verifier results and links to Grafana, Prometheus and OpenAPI.
- Dark navy console, teal accent, clear typography, restrained motion, responsive desktop/mobile layout, keyboard-accessible dialogs and explicit loading/empty/error/stale states. All money is labeled synthetic.

## Boundaries and data

New read-only `/api/v1/dashboard` endpoints own bounded operator read models; services perform SQL, handlers serialize. Global aggregates/chart use a REPEATABLE READ READ ONLY snapshot. Cursor lists cap at 100, search length at 128, details/history cap at 100. No migrations or extra privileges.

Dashboard money fields are decimal strings to retain BIGINT precision in browsers; rendering/submission uses BigInt. Transfer payload encodes a validated exact integer JSON token. Existing public financial API contracts remain unchanged.

Optional signals are fetched server-side from fixed configurable verifier/activity URLs with bounded timeouts. Missing, malformed or stale verification is UNKNOWN, never inferred PASS. Verifier report is forwarded, not recomputed with application services. Dependency health uses the existing endpoint. No credentials or arbitrary proxy target reaches the browser.

Poll reads every ten seconds without overlapping cycles; pause/refresh controls. Failed refresh marks retained data stale and shows errors without substituting healthy zeros. Backend outage leaves independently observable signals visible where available.

Create-account and transfer dialogs submit only through existing HTTP endpoints. A pending transfer persists its key and exact payload in tab session storage. Network failure/5xx keeps that intent locked for an identical retry, including reload; success/replay clears it. Definitive 4xx errors show the safe error envelope. The UI never approves transfers from displayed balances, provisions funds or controls Docker/activity processes.

## Verification

Docker API tests cover empty/seeded aggregates, consistent conservation, pagination/search/cursor errors, exact BIGINT strings, transfer details/ledger, static serving and unavailable/stale verifier signals. Containerized Chromium tests use throwaway databases and a real HTTP server: browse/create/transfer, commit-then-response-loss identical retry, unavailable/stale states, keyboard dialog behavior and responsive overflow checks. Retain screenshots and actual results. Run the full financial suite, Ruff/mypy and smoke afterwards.

Baseline tag `phase1-breathing-v1` remains unchanged. Native execution in the requested repository preserves the user's established workspace preference. No later-phase machinery or banking/auth integration.
