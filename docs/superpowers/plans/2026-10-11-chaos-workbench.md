# PulsePay Chaos Workbench implementation plan

> Execute inline with executing-plans and test-driven-development; one independent final review. Preserve the existing branch and working tree.

**Goal:** Operate and inspect native framework experiments through a local UI in the same stack.
**Architecture:** Non-root FastAPI/browser adapter delegates fixed commands to existing chaos.cli; independent gateway/watchdog remain authoritative. Locust publishes observed manual-session evidence for existing integrity/load gates.
**Tech stack:** Existing pinned FastAPI/uvicorn/Toolkit image, plain HTML/CSS/JavaScript, Docker Compose, pytest and Chromium.
**Spec:** [design](../specs/2026-10-11-chaos-workbench-design.md).

## Constraints and review focus

No arbitrary commands/targets, no new engine, no socket in web/app/load containers, no automated fault/traffic, no relaxed preflight, no forged/missing-zero observations. Confirm state changes with Origin/Host/session/CSRF checks. Preserve native exclusive lease, watchdog TTL and immutable evidence. CPU remains disabled. Single browser job except abort; shutdown must not orphan fault authority. Bound reads/output and reject path traversal/symlinks. Manual load stays distinct from benchmarks.

## Execution ledger

- [x] 1. RED API tests (initial missing module; subsequent missing assets/output helper) and manual evidence test (missing helper) observed in Docker. GREEN: 7 workbench tests, 1 manual evidence test. Native CLI remains sole framework entrypoint; process output bounded to 128 KiB.
- [x] 2. Base/combined Compose validate; app/Locust/Workbench built and only changed services restarted. Loopback8090 and healthy gateway/watchdog confirmed. Normal budget6016MiB/10.5CPU; no automatic faults or load. Fixed common CLI profile activation after actual `no such service` failure.
- [x] 3. Chromium catalog/history/disabled-CPU + native preflight/worker-pause workflow:2passed. Actual run `chaos-20261010T191532Z-36abf3a2`:PASS, real impact, RESTORED, pre/postPASS, same manual load RUNNING/productive. First browser attempt failed before injection due incorrect metrics URL/label parsing; fixed against actual9101 endpoint. Main dashboard mobile overflow from new sidebar link reproduced and fixed;7browsertests pass.
- [x] 4. Fresh review completed; reproduced cancellation/finalization/overlap bugs fixed RED→GREEN. Live active-fault browser Abort1passed: `chaos-20261010T191940Z-f409ec98`ABORTED/RESTORED/pre+postPASS/same loadRUNNING/released lease. Full `make up` exit0,17persistent services in one project, all CPU/memory bounded, only gate holds socket. Final smoke and read-only verifier PASS; Locust idle and no active experiment. Curated workbench-v1 evidence preserves native bundles, manual reports, snapshots and screenshots; previous framework-v1 unchanged.

Ruling: user explicitly requires UI integration and previously authorizes action on this branch. Do not add proprietary services, redundant approval stages, a new branch or commits. UI is a thin adapter over existing Toolkit, not a second chaos operator.

Independent review found pre-lease Abort race, recovery finalization/overlap and native-summary field mismatches. Reproductions observed RED; fixes use fixed native abort→restore and deny new starts throughout pending abort. Framework66passed; load37passed; application52+resilience3passed; main browser7passed; Workbench browser3passed. No deferred review findings. CPU containment/PostgreSQL client ambiguity remain earlier framework limitations, not unreported UI failures.
