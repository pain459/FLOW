# Investigation readiness boundary

The completed independent audit in `docs/audits/phase3-completion.md` grants shadow GO and explicitly withholds autonomous read-only GO until an isolated, bounded executor is independently qualified. The implementation supports real Laya inference, chronological shadow replay and operator-requested live suggestions through a bounded GET-only observation gateway. This gateway does not qualify the autonomous executor. No model-selected diagnostics, fault control or remediation executes. Autonomous read-only requests return 423 and the tool registry cannot execute any tool.

Checkpoint D and its live acceptance gate are BLOCKED, not PASS. Before enabling them:

1. Implement a separately isolated diagnostic executor and fixed, parameterized tools with per-tool row/time/cost limits, provenance and sanitizers.
2. Qualify a dedicated diagnostic SQL role, telemetry gateway, read-only permissions (including mutating procedure denial), and network exclusions. Raw operator Prometheus, Loki and Workbench remain outside investigator access.
3. Complete independent per-tool security review, budget/cancellation/repeat-action tests and the Phase 3 read-only readiness gate; obtain approved operator read-only mode.
4. Run authorized live investigations with genuine new evidence while the existing watchdog restores faults independently; evaluate evidence yield and diagnosis against private labels.

Current shadow-only reports cannot prove live diagnostic usefulness, causal diagnosis, recovery benefit, calibration or an 85% generalization target. No development or held-out result overrides this boundary.

Additional measured gaps:

5. Five of eight qualified recordings did not meet the frozen incident detector. Extend sanitized availability, latency/error and stream symptoms before live trigger qualification. Missing signals must remain unknown.
6. Three applicable windows localized 0/3 with Laya and 1/3 with rules. Acquire new untouched whole-run holdout data; a preliminary aggregate was seen before correcting replay selection, so the current nominal holdout is exploratory.
7. An expired SDK CPU thread fails readiness and blocks further inference, but requires operator restart if stuck. Hard worker-process termination is deferred.
8. Actual diagnostic evidence yield, causal diagnosis, calibration, live model/load contention, fresh empty-volume bootstrap and native Linux/WSL2/GPU are NOT_RUN. Central decision-service metrics/log delivery is not separately qualified; DB/files are the decision audit source.

The review findings for cancellation, cache integrity, causal controls, console ingress and ranking eligibility are fixed and regression-verified.
