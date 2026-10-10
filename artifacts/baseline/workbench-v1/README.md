# PulsePay Chaos Workbench acceptance evidence

Actual Docker Desktop/macOS Linux arm64 validation on 2026-10-10/11, existing branch `feat/pulsepay-dashboard`.

- Browser catalog/history/disabled-CPU and preflight→worker-pause→recovery: **2 passed**. Run `chaos-20261010T191532Z-36abf3a2`: **PASS**, observed impact, RESTORED, independent pre/post PASS, same manual workload still productive/RUNNING.
- Browser active-fault Abort: **1 passed**. Run `chaos-20261010T191940Z-f409ec98`: **ABORTED**, observed impact, RESTORED, independent pre/post PASS, same load RUNNING, no active lease afterward. Interrupted framework completion remains explicit; ABORTED is not a qualified resilience PASS.
- Framework/native/safety regression: **66 passed**, including ten Workbench tests. Workload: **37 passed**. Application unit/integration/concurrency: **52 passed**, resilience: **3 passed**. Main dashboard Chromium: **7 passed** after reproducing/fixing mobile navigation overflow.
- First Workbench browser attempt: **1 passed, 1 failed**, before injection, because the test queried Locust UI port8089 for metrics instead of actual9101 and incorrectly expected an unlabelled series. The failure is retained. Corrected native summary fields use string `restoration` and `load.after_state`.
- Independent review reproduced early Abort and overlapping recovery races. Failing regressions preceded fixes. Browser Abort now cancels its associated job, delegates fixed native abort→verified restore, blocks new actions during finalization, and retains the independent watchdog.

`evidence/` retains complete native experiment bundles and actual manual load reports. Manual performance remains `INCOMPLETE` with `MANUAL_UI_SESSION_NOT_A_QUALIFIED_BENCHMARK`; it is not a new capacity baseline. `browser/` contains actual Chromium screenshots/JSON reports. `checks/` retains command output and sanitized runtime snapshots. `acceptance.json` and `checksums.json` identify collected artifacts.

The sealed older `framework-v1` baseline is unchanged. CPU containment and PostgreSQL sustained-load/client-outcome findings remain unresolved there; this UI addition does not relabel them. All services remain in one Compose project with finite resources and idle traffic at handoff.
