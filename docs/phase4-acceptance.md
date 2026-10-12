# Decision intelligence acceptance

**Verdict: shadow implementation and operator-requested live suggestions verified; full Phase 4 INCOMPLETE.** The independent dependency audit grants shadow GO and autonomous read-only NO-GO. Manual questions now collect fresh bounded observations and correlated call evidence, without granting model-selected diagnostic execution. No autonomous incident executor, chaos injection or remediation was enabled. The next stage requires independent executor qualification, richer observations and new untouched evaluation data. The original evidence below describes the initial shadow release; the additive manual release has separate evidence at the end.

| Checkpoint | Status | Evidence and scope |
|---|---|---|
| A: discovery, pinned CPU provider and strict outputs | PASS | Official Laya 0.4.3/source/wheel verified; real offline choice/ordinal score/P(true); reviewed SHA pins and read-only cache; invalid/unavailable/timeout tests |
| B: observation pipeline and durable sessions | PASS | Sanitized schema 1.1, causal chronology/quality, own schema/version, actual restricted role, idempotency/concurrency/canary tests |
| C: shadow decisions/rankings | PASS | Eight qualified real recordings, 50 valid answers, frozen questions/policy, proposal/override/baseline traces; zero diagnostics |
| D: autonomous read-only investigation | BLOCKED | Independent read-only readiness not granted; live diagnostics NOT_RUN; API returns 423 and registry denies execution |
| E: paired shadow evaluation | PASS, exploratory only | Eight sealed sources/sessions; three applicable windows: Laya 0 correct, rules 1; five excluded; tiny correlated sample and exposed nominal holdout disclosed |
| F: console and release checks | PASS for shadow scope | localhost8092, two Chromium tests, real bounded replay, documented startup/status/test commands, offline restart/history retention; full live release BLOCKED by D |

Machine-readable gates: `artifacts/phase4/checks/gates.json`; exact commands/exits: `checks/commands.md`; environment/revisions: `checks/manifest.json`. Source remains on `feat/pulsepay-dashboard`, base commit `94cfb14`. No branch creation, commit, push or reset occurred.

## Executed verification

| Check | Actual result | Evidence under artifacts/phase4 |
|---|---|---|
| make intelligence-test | 52 PASS, isolated pulsepay_decision_test | checks/decision-tests-final.txt, checks/operator-test.txt |
| Application regression | 57 PASS, 16 optional SKIP, one dependency deprecation warning | checks/application-regression.txt |
| Workload regression | 66 PASS | checks/load-regression.txt |
| Native chaos safety regression | 157 PASS; no faults injected | checks/chaos-regression.txt |
| Published-ingress Chromium desktop/mobile + unauthorized start | 2 PASS | checks/browser.txt, desktop/mobile screenshots |
| Ruff check/format, shell syntax, git whitespace | PASS | checks/commands.md |
| All-profile Compose validation | exit0 | checks/commands.md |
| Independent verifier after documented startup | 12 PASS | checks/verifier-after-startup.txt |
| Actual role/image/network/resource boundary | PASS | checks/runtime-isolation.jsonl, checks/persistence-before.txt, review.md |
| Evidence credential scan | 519 text artifacts; zero local secret-value matches | checks/evidence-secret-scan.txt |
| Installed SDK scratch tamper rejection | PASS; real cache untouched | checks/sdk-digest-negative.json |
| Offline restart/history retention | model HEALTHY; 35 retained sessions; zero active/tool records | checks/status-after-restart.txt, checks/persistence-after.txt |

Verifier `2918f2b1-70fb-4e5a-ae2e-66ded5b02626` confirms 200 accounts, 113973 transfers, 228146 ledger entries, and conserved 20000000 synthetic minor units. Outbox pending, overdue projections and quarantine are zero. API/DB/Redis/relay/worker are healthy. Instrumentation export confirmation remains UNKNOWN in the API health contract; it was not relabelled healthy. Locust is idle, no new fault was injected, and only the chaosloop Compose project is running.

Initial stopped-stack verification returned UNKNOWN/exit2. Normal startup restored access without changing financial data. Core migration marker remains 0002; decision marker is di0001. The decision role cannot read/mutate core financial tables or use the evaluator schema. An attempted read of public migration state was correctly denied; independent readiness/verifier evidence establishes financial readiness instead.

## Real inference and evaluation

Laya 0.4.3 CPU checkpoint `convaiinnovations/laya-multilingual`, revision `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67`; weight SHA-256 `9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204`. Exact reviewed weight, model/encoder config and tokenizer digests are passed to the installed SDK. Runtime cache is read-only/offline. Weight is 643835514 bytes; regular cache files/metadata total 678283931 bytes, excluding symlink aliases.

Initial load 3019.16 ms, first prediction 3353.73 ms, two warm probes 3199.58/3219.01 ms. Eight-run/50-answer replay: p50 7040.45 ms, p95 7245.36 ms, max 7301.39 ms. These input sizes differ from probes; this is single-host characterization, not an SLA. A resource spot sample showed model 196.63% CPU and 2.193 GiB under two CPU/3 GiB caps; controller 62.36 MiB/384 MiB; ingress 54.14 MiB/128 MiB. Offline restart load 3077.52 ms. Retained: checks/inference-summary.json, resource-sample.jsonl and discovery/provider-probe.json.

Example actual validated answer: subsystem **worker**, option probability **0.897**, uncalibrated; severity expected ordinal **2.1414**, most likely legend level moderate; evidence-insufficiency **P(true)=0.99**. This is a hypothesis, not confirmed cause. Full distributions: `sessions/91560ae0-5c62-4679-9d4b-b3eb4f04e3ec/model-answers.jsonl`.

Evaluation `a31c1427-6824-4f0c-b974-ca687a91fca7` is COMPLETE_SHADOW_COMPARISON: development 0/1 Laya vs 0/1 rules; nominal holdout 0/2 Laya vs 1/2 rules. Top-two coverage and model abstentions were zero on those three comparison frames. Five recordings failed the frozen sustained detector and remain excluded. Eight pre-fault control samples show zero sustained false alarms, with only one frame per run. All eight sessions end INCONCLUSIVE with zero diagnostics. Native independent recovery/integrity PASS in all eight sources; session recovery UNKNOWN. Diagnostic yield, causal accuracy, calibration and recovery benefit remain null. See [methodology](phase4-evaluation.md).

Questions/rules remained frozen. A preliminary incomplete aggregate was viewed before correcting causal replay selection and a misselected dataset. The nominal holdout is therefore exploratory; collect new untouched runs before generalization. Incomplete comparisons and failed attempts remain retained. The result does not reach the localization research goal.

## Failure discoveries and corrections

TDD first failed eight contract and six observation tests for absent implementation, then passed. Initial offline load failed LocalEntryNotFoundError: Router defaulted to bundled repositories; source-verified standalone_repos=True fixed routing. Integration tests initially used the normal decision DB and interrupted a replay; tests now use a separate disposable DB, and interrupted records remain escalated. Financial data was untouched.

An insecure-context browser lacked crypto.randomUUID; a CSPRNG fallback corrected submission. Independent review reproduced cancellation evidence loss, mutable cache, omitted controls, unpublished all-internal host port and healthy readiness during expired CPU work. Five new tests failed before correction; 50 then passed, followed by two export tests for 52. Idempotent shielded cancellation, hardcoded SDK digests/read-only cache, full-source causal verification and a credential-free localhost ingress closed these findings. Ranking eligibility uses policy repeat context. Final independent review found no outstanding shadow blockers.

## Explicit limitations

- Live read-only executor/security qualification and live end-to-end investigation are BLOCKED. No model-controlled writes/fault tools exist.
- Five recordings did not meet the frozen detector; Laya localized poorly on the three applicable cases.
- Actual tools/results, diagnostic yield, live incident polling/refresh, central decision-service metrics/log delivery and untouched holdout qualification remain pending.
- Stuck SDK work fails readiness and blocks more inference; operator restart is required. Hard worker termination is deferred.
- Fresh empty-volume bootstrap, long soak, GPU, native Linux and Windows/WSL2 are NOT_RUN. Only existing macOS Docker Desktop/Linux ARM64 was exercised.
- Reset was reviewed/updated and **not executed**. Full-stack shutdown was not exercised; targeted decision restart, history retention and merged lifecycle configuration were verified.

See [operations](phase4-operations.md) and [blockers](phase4-blockers.md). Verified shadow software is not full live-investigation certification.

## Operator-requested first response, 2026-10-12

**Manual feature verdict: PASS for interface, bounded evidence collection, real inference and safety; diagnosis accuracy NOT_RUN.** The operator can ask about the current system, paste a recognized error/OTel trace excerpt, or select a recent request/trace ID at localhost8092. No active experiment or historical snapshot is required. Model input excludes injected fault identifiers, actions, target metadata and arbitrary log/SQL strings. Manual collection is a human-selected fixed GET-only observation read, not an autonomous diagnostic executor; checkpoint D remains BLOCKED.

| Verification | Actual result | Evidence under artifacts/phase4/live-questions/manual-live-v1 |
|---|---|---|
| Investigation contracts, authorization, idempotency, cancellation, completeness, freshness and leakage | 77 PASS | checks/decision-tests-final.txt |
| Application regression and exact reset scope (fake Docker only) | 57 PASS, 20 optional SKIP | checks/application-regression-final.txt |
| Published Chromium desktop/mobile, existing replay, unauthorized submission and real manual call | 4 PASS | checks/browser-final.txt, browser-final/ |
| Genuine read-only API 404 → matching Loki/Tempo → actual CPU Laya → durable answer | PASS | browser-final/manual-question-e2e.json |
| Documented current-system CLI question | exit0, valid suggestion/abstention | checks/ask-current-system.json |
| Independent ledger verifier | 12 PASS, zero violations | checks/verifier.json, run c96e0be5-2124-4114-a062-0416b1c7c6c7 |
| Actual SDK input completeness and sealed export reproduction | Two live sessions PASS, 14 files each verified, zero dropped tokens | checks/evidence-validation.json |
| Local secret-value scan | 59 text files, zero matches | checks/evidence-validation.json |
| Real resources, privilege boundary, model/DB/feature health | PASS | checks/runtime-isolation.txt, checks/health-final.json |
| Compose config, image builds, Ruff, whitespace | exit0 | checks/compose.txt, build-release.txt, lint-final.txt; commands.md |

Release session `1f848667-9981-4885-ba70-822a5b413afd` correlated a real HTTP404/ACCOUNT_NOT_FOUND with Loki and Tempo. Laya chose insufficient_evidence (0.7969), suggested worker, and returned evidence-insufficiency P(true)=0.9963; this did **not** establish the correct reason. Inference was 8388.99ms, with 808 state tokens and zero dropped tokens. The current-system question `c0c425ef-3a4e-4900-bf60-9b2697b49abd` took 5751.59ms, 576 state tokens, zero dropped tokens; an unsupported no_observed_failure model proposal was withheld as insufficient evidence. These are two functional probes, not an accuracy benchmark. Both have zero model-selected diagnostic executions and independently UNKNOWN session recovery. Original exports remain unchanged; the new sealed sessions are under artifacts/phase4/sessions/<session-id>/.

Review reproduced and fixed: SDK truncation hiding call evidence; old errors labelled FRESH beside healthy new records; an HTTP503 span lost during bounded sampling because its span error flag was UNSET; an Ask button stranded by history selection; and input hashes changing after JSONB reordered source dictionaries. Live input is now compact, call-first, canonical and verified against actual SDK usage. Missing or partial usage is rejected. Full sanitized observations and exact compact model input both remain auditable. Cancellation without an answer safely exports null quality. All relevant regressions passed; independent review found no remaining manual-flow blockers.

The initial application regression in checks/application-regression.txt failed two reset tests because the fake Docker parser did not recognize Compose overlay flags. Only the stub was corrected; acknowledgement/project isolation requirements were preserved and no real reset ran. Earlier failed/truncated attempts remain retained rather than relabelled successful.

Historical replay inputs did not retain SDK completeness metadata. Their original measured results remain preserved, but full-input completeness is UNKNOWN; do not treat them as proof of complete-context model performance. The new guard is qualified for the manual suite. No chaos incident was injected to evaluate the new reason question, no holdout was tuned, and useful causal diagnosis is still unproven. New source images/resources are captured separately; evidence-reader adds 128MiB/0.25CPU within fixed stack ceilings. Decision schema is now di0002, financial schema remains unchanged. Native Linux, WSL2 and GPU remain NOT_RUN.

## Calls workspace release — 2026-10-12

**Feature verdict: PASS for the approved call-selection and explicit-analysis workflow. Full autonomous Phase 4 remains INCOMPLETE.** [Calls](call-investigations.md) replaces the questionnaire landing screen. Inventory/detail/history/trace lookup and refresh make zero model requests. One explicit Explain makes one decision; saved results reopen without inference, and Re-analyze is explicit. Signed operator cookies authorize once, with same-origin mutation checks. The financial dashboard keeps its business focus.

Evidence root: `artifacts/phase4/call-investigations/`. The final source stays uncommitted on `feat/pulsepay-dashboard`, based on `f4233d5006a3000c6e5d9f09aed3d0da1e5a5117`. Docker image hashes, fixed ceilings and real test outputs are retained. Decision migration `di0003` was applied inside Docker; financial migration remains `0002`.

| Executed check | Outcome | Evidence |
|---|---|---|
| Compose config and affected image build/start | PASS | checks/build.txt, final-config.txt, final-deployment.txt, runtime-release.txt |
| Decision contracts/auth/idempotency/historical evidence | 103 PASS | checks/final-decision-tests.txt |
| Application financial/concurrency/negative tests | 66 PASS; 22 gated checks skipped in this invocation | checks/release-application.txt |
| Workload regressions | 66 PASS | checks/load-tests.txt |
| Native chaos/safety unit regressions; no live faults | 157 PASS | checks/chaos-tests.txt |
| Chromium desktop/mobile: Calls, auth, saved/reopened active results, real CPU Laya, financial UI, transfer/event correlation | 13 PASS | checks/release-browser.txt, browser/*.png and *.json |
| Ruff and diff whitespace checks | PASS | checks/final-lint.txt; final command log |
| Independent post-release reconciliation | All 12 checks PASS, zero violations; repeatable-read/read-only | verifier-post.json |
| Durable session export | PASS; 2 new bundles copied, 39 unchanged, zero partial | checks/export-release.txt |

The browser suite separately enabled its gated tests; the skipped application-suite checks must not be treated as passed. Nine other gated application checks were not rerun in that invocation. Dependency deprecation warnings remain visible. No fault injection, resource ceiling increase, financial reset, branch change or autonomous diagnostic execution was performed.

Review reproduced and corrected: malformed call filters becoming 503; coerced re-analysis flags; filtered/tied-timestamp pagination losing calls; spans from another HTTP attempt in a shared trace; early 413 records losing their endpoint template; and reopened active sessions failing to poll. A fresh real browser run then exposed a tracing integration mismatch: middleware and the OTel hook generated different IDs. Two ordering tests and the deployed checks now prove one ASGI attempt ID reaches headers, logs, the tagged root and outbox metadata. The failed initial browser output remains in `checks/browser-final.txt`; the corrected run passed all 13 tests. The real transfer/replay produced one transfer, distinct attempt IDs, distinct exact trace branches and asynchronous effects attached only to the committing attempt.

Actual final CPU inference session: `8c8082d5-2dd5-46d4-80d5-c07ef1e92a4c`; HTTP404 / ACCOUNT_NOT_FOUND call `92061c99-11b6-40f4-b374-557af2de7ebc`. Inference took **8652.07 ms**, with 811 state tokens and zero dropped tokens. The model proposed database connectivity (uncalibrated score 0.4975) despite no supporting symptom; policy withheld it as **insufficient evidence**. This is a functional and safety PASS, **not a successful diagnosis or accuracy qualification**. No tools executed. The saved response survived reload without another inference. Its sealed export is `artifacts/phase4/sessions/8c8082d5-2dd5-46d4-80d5-c07ef1e92a4c/`; release validation checks hashes, exact SDK input completeness, ID exclusion and secret-value absence.

Post-release verifier run `c725da62-7249-4345-a882-87237b1f96df` inspected 200 accounts and 115,094 transfers, with no violations, no pending outbox rows, no overdue projections and no quarantine. Global synthetic funds still match issuance. Historical model input excludes current recovery and later async events. Current model/controller availability is independent of the selected call's evidence; financial health is visible in the existing System/Grafana views.

Remaining limits: call metadata begins with this release and discovery is bounded to 24 hours/retention; requests never reaching the API are unavailable; separate worker trace hierarchies open through Grafana rather than the compact call view; diagnostic usefulness/calibration and autonomous executor qualification remain unresolved research gates. No new fault-response evaluation or new platform qualification was claimed.
