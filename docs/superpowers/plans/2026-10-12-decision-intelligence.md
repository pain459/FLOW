# PulsePay decision intelligence implementation plan

The user's full Phase 4 specification supplies the approved design. Work inline on the current branch. No live fault injection, new chaos operator or remediation. Tests and dependency inspection run in Docker.

- [x] A: discover audited gate and installed Laya interface; build pinned CPU provider, immutable model provisioning, strict typed answers and failure tests; record actual cold/warm inference.
- [x] B: normalize whitelisted observation 1.1; opaque identifiers; immutable persistence with separate decision schema/version; idempotency, freshness and canary tests.
- [x] C: versioned questions, deterministic baseline, bounded shadow replay, ranked choices and policy timeline; reserve run-level holdout; authorized API.
- [ ] D: fixed diagnostic catalog, budgets and rejection tests. Keep executor disabled because current independent audit grants shadow only; document what is needed for live read-only GO.
- [x] E (exploratory shadow comparison only): evaluator-only source mount, confirmed-effect labels, fair paired replay scoring with uncertainty; durable evidence/export and model resource measurements.
- [x] F (shadow release only): thin investigation console linked from existing dashboard, Docker commands, restart/persistence, regression tests and honest acceptance matrix.

Files: `decision_engine/{models,providers,questions,controller,adapters,tools,evaluation,api,tests}`, `compose.phase4.yaml`, `migrations/decision*`, `scripts/phase4/`, `docs/phase4-*`. Add no Laya fields to financial tables.

Verification: run contract tests red before implementation, then green; provider unavailable/invalid distributions, nonfinite output, unsafe input, stale data, future replay, duplicate start, cancellation, budget exhaustion, API authentication, mount/network separation, read-only role and immutable artifacts. Use existing tests image for controller contracts; separate model image carries CPU PyTorch. Full application/workload/framework regressions before completion. Unknown or unexecuted gates retain their actual status.
