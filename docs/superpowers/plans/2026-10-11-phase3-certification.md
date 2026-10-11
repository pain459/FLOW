# PulsePay chaos readiness completion plan

> Execute inline on the existing `feat/pulsepay-dashboard` branch. Use test-driven fixes and a final independent review. Do not create a branch or implement a decision model.

**Goal:** Close the readiness-audit failures and qualify supported chaos scenarios with fresh Docker evidence.

**Architecture:** Preserve native Chaos Toolkit/Pumba/Toxiproxy, immutable operator journals, the existing watchdog and public-HTTP workload. Correct sanitized observations and publish them into a separate volume. A minimal standard-library read-only feed has only that volume and an isolated internal network; it has neither experiment code/credentials nor connectivity to operator services. Existing privileged Workbench remains an operator interface.

**Baseline:** `docs/audits/phase3-readiness.md`, user framework specification and existing implementation.

## Constraints

- Existing branch, no new worktree, commit, push, reset or old-evidence rewrite.
- Docker-only execution; synthetic lab project/target allowlists; no volume removal or unrelated mutations.
- Reader 128 MiB / 0.25 CPU / 32 PIDs, non-root/read-only; existing ceilings preserved.
- Duration 3–300 seconds, independent TTL/watchdog; reviewed default exposures for qualification.
- No Phase 4 model, investigation executor, custom operator or scheduler.

## Review focus

- Stale, missing, future-dated and non-finite observations must not imply healthy fresh data.
- Outbox age, consumer undelivered count and pending delivery idle age have different units.
- Reader must reject privileged fields, symlinks, oversized files, unsafe identifiers and arbitrary endpoints.
- Historical labels require hashes/provenance and may retain UNKNOWN; old results cannot be relabelled.
- Interrupted fault/traffic must restore and verify without relying on the model or experiment process.

## Task 1 — Observation correctness

Files: `chaos/adapters/observations.py`, new pure `chaos/observation_contract.py`, observation regression tests.

- [x] Write and execute failing cases for exported freshness, stale/missing/future samples, non-finite values and distinct consumer/outbox units.
- [x] Implement schema 1.1 with source/window/quality fields and real consumer count/pending age; unavailable consumer lag seconds stays null.
- [x] Run focused and full framework suites in Docker; record results.

## Task 2 — Restricted observation export

Files: `chaos/observation_feed.py`, reader Dockerfile, publisher integration, Compose mounts/network, tests and resource/contract documentation.

- [x] Test reader-only routes, bounded replay, strict schema, symlink/size rejection and unrelated endpoint denial.
- [x] Publish pre/during/post snapshots into separate `chaos-observations`; mount it read-only in reader. No private evidence/control/authority/code catalogs or runtime credentials in reader.
- [x] Add reader to ordinary stack and preserve all existing service ceilings.
- [x] Build/start in Docker; prove no path/network access to Workbench, Prometheus, gateway, DB or privileged artifacts.

## Task 3 — Historical provenance

Files: minimal `chaos/evaluator.py`, fixture tests, new versioned derived evaluator bundle.

- [x] Test derivation from sealed original artifacts, invalid/missing evidence and source hash rejection.
- [x] Write a derived evaluator index for legacy missing truth with field provenance and explicit UNKNOWN, never touching originals.
- [x] Recheck all original root seals and the new derived seal.

## Task 4 — Qualification and handoff

- [x] Build frozen final images; run application/load/framework/quality/browser and telemetry regressions in Docker.
- [x] With healthy preflight, run supported API, worker, Redis, DB, latency and partition cases under bounded existing HTTP load; capture repeat effect direction.
- [x] Run scoped runner-kill/manual-abort, negative-target and double-run drills. Restore topology between direct/proxy datasets and stop only owned traffic.
- [x] Independently verify integrity, restoration, no leftover fault helpers/leases, reader boundary and full bundles.
- [x] Generate a new readiness matrix, report and hashes; preserve original audit. CPU remains SKIPPED_UNSUPPORTED with actual backend evidence.
- [x] Obtain final independent code review and resolve important findings with regression tests.

## Execution ledger

Setup: prior audit and source inspected; root causes confirmed. The user's request authorizes remediation and the remaining bounded synthetic-lab qualification. Work remains on the existing branch. Original audit stays immutable. Phase 4 read-only executor remains future work; successful completion will qualify shadow observations, not claim an unimplemented executor exists.

Completion: supported qualification PASS; 26 PASS / 1 SKIPPED_UNSUPPORTED. Seven real supported scenarios plus a repeat, runner-kill and manual abort, final healthy nominal run, independent funds verification and original-evidence preservation passed. New readiness-v1 seal verified 464 files at 2026-10-11T18:41:16.529811Z. Detailed evidence and remaining supported-platform/Phase 4 limits are in docs/audits/phase3-completion.md. No commit or new branch was created.
