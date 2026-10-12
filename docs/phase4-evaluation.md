# Shadow evaluation methodology and results

Evaluation `a31c1427-6824-4f0c-b974-ca687a91fca7` uses eight existing, sealed native experiments with PASS, confirmed injection, observed effect and independent recovery/integrity PASS. Four development runs cover API pause, worker pause, Redis outage and API delay. Four nominal holdout runs cover PostgreSQL outage/delay and two Redis partitions. Whole runs are split, not individual frames; repeated partitions are correlated.

Each model/rules decision uses the same sanitized frame available at that historical step. The frozen detector requires two consecutive observed impaired windows. Decision budgets begin at that causal trigger. Non-triggering manual controls are retained but excluded from positive localization. Evaluator-only code checks the source recording hash, causal slice, session seal and native source seal, and selects the first complete real replay with the declared qualification version. It does not select the most accurate replay. Unsupported/ineffective native experiments and incomplete/fixture/older qualification attempts remain explicitly excluded.

| Group | Native runs | Triggered/applicable | Excluded | Laya top-1 correct | Rules correct |
|---|---:|---:|---:|---:|---:|
| Development | 4 | 1 | 3 | 0 | 0 |
| Nominal holdout | 4 | 2 | 2 | 0 | 1 |
| Total | 8 | 3 | 5 | 0 | 1 |

The three applicable windows were Redis outage, PostgreSQL outage and repeated Redis partition. Laya's top choices were PostgreSQL, worker and PostgreSQL respectively. Neither top-two coverage nor abstention occurred on those comparison frames. This is a negative localization result, not evidence of improved investigation. Five recordings had no sustained incident under the frozen detector; producer missingness, sparse samples and symptoms outside that rule are coverage limitations, not successfully detected incidents. All eight sessions terminate INCONCLUSIVE because no diagnostic evidence was executed.

Descriptive 95% Wilson upper bounds for Laya accuracy are 79.35% (0/1 development) and 65.76% (0/2 nominal holdout). These tiny correlated samples do not establish generalization, calibration or the 85% research target. There were eight recorded pre-injection control samples and zero sustained false alarms; one frame per experiment is insufficient to characterize healthy false-alarm behavior.

The question library and deterministic rules were frozen before evaluation. A preliminary aggregate was viewed before correcting selection of the qualified dataset and causal replay start. That methodological correction did not tune questions, thresholds or rules, but the nominal holdout is now exploratory. Collect new untouched whole-run holdout data before any statistical qualification. Prior INCOMPLETE comparisons and failed attempts are retained rather than rewritten.

Diagnostic evidence yield, unnecessary diagnostic rate, time to defensible causal diagnosis, calibrated confidence and recovery benefit are **unknown**. Recommending a tool is not equivalent to executing it or obtaining evidence. Option suitability scores are uncalibrated probabilities over choices; severity is an expected ordinal index; `noul` is P(true). No causal or recovery probability is claimed. Independent native recovery is PASS in all eight source experiments, while investigation session recovery remains UNKNOWN and cannot be model-owned.

The first real offline provider characterization measured load 3019.16 ms, first prediction 3353.73 ms and two warm predictions 3199.58/3219.01 ms. The post-review offline startup measured 3413.21 ms. These few calls are characterization only. Model resource ceilings, actual runtime image hashes and session inference samples accompany the evidence. CPU-resource spot checks cannot establish a saturation envelope.

Evaluator ground truth and `evaluation.json` remain outside investigator bundles and APIs. Inputs use typed numerical symptoms and quality flags, not native scenario titles, file names or injector commands. Canary/rejection tests assert the model-visible history remains clean. Session seals and source references permit replay audit without disclosing privileged truth to inference.

Next qualification: richer sanitized API availability/latency/error observations; representative delayed/ambiguous/healthy controls; independent safe read-only executor; actual time-indexed tool results; new untouched whole-run holdout; then evidence-yield and efficiency comparison. Version any changed detector/question before collecting new evaluation data. No tuning is hidden in the current reported result.
