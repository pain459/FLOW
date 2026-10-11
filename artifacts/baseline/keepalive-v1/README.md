# PulsePay paced-user transport regression

Recorded on 2026-10-11 on the existing macOS Docker Desktop Linux arm64 stack and branch `feat/pulsepay-dashboard`. No new branch, commit, fault or data reset was needed.

User attempt `chaos-20261011T065742Z-7a297eb3` was INVALID before injection because its running 100-user workload had new connection failures in the measured window. The original session `load-ui-18a2370cb3f24f80b5c10a572d3b04f9` retains 12,166 measured HTTP attempts, 106 failures, 4,774 confirmed transfers, zero final unknown outcomes and independent pre/post integrity PASS. Its FAILED verdict is preserved.

The client mislabeled every synthetic Locust status-0 response as a timeout. Actual Requests exceptions were `ConnectionError` with `ProtocolError` and `RemoteDisconnected`/`ConnectionResetError`, finishing in roughly 11–19 ms. At the selected pacing ceiling, 100 users issue an operation about every five seconds, coinciding with the API's explicitly configured five-second keep-alive expiry.

A bounded read-only diagnostic issued 700 health requests using 100 sessions: the 350 requests on default reused connections had **54** resets; the 350 requests asking for fresh connections had **zero** failures. An earlier 70-request diagnostic did not reproduce the race; its insufficient sample is recorded rather than treated as proof of health.

The production fix retires only sockets idle for at least four seconds; shorter idle periods keep reuse. No HTTP request is hidden or silently retried. Real timeouts retain their category, while disconnects/reset failures use the infrastructure category and controlled exception-class diagnostics. Existing same-key transfer retry and independent integrity policies remain unchanged. Regression tests use real HTTP sockets to verify active reuse, idle retirement and retained reset failures.

`checks/stable-100-users.json` retains the new 100-user session at the existing 20 logical operations/sec pacing ceiling. It passed without HTTP errors and maintained LOAD_READY for a further 30 seconds after satisfying warmup/sample/window prerequisites. Traffic remained running for the operator, subject to its existing 630-second session cap. This is a functional readiness check, not a qualified performance baseline. Older sealed bundles remain unchanged.

All regression commands ran in Docker: **66 workload tests PASS**, **56 application tests PASS / two default live opt-ins skipped**, and **71 native framework/safety tests PASS**. Ruff/format PASS across 135 files and mypy PASS across 88 runtime files. The new real-socket tests failed before the fix. Requests stubs are pinned for the existing full-source type checker.

Redis-outage preflight passed twice with `injected=false`: CLI `chaos-20261011T075814Z-f3e81c58` and the actual Workbench action `chaos-20261011T080037Z-43143f50`. The Workbench job is COMPLETED, LOAD_READY is true and independent integrity is PASS under traffic. `native-views/` contains decoded JSON from the existing reviewed HTTP artifact interface; original byte archives stay on their private volume. No filesystem permission or mutation-authority change was made. `runs/` retains the original failed session and a snapshot of the active corrected session, whose final timed-run report was not yet available at capture.
