# PulsePay investigation intelligence

CPU Laya 0.4.3 with strict `choice`, expected ordinal `score` and P(true) `noul` normalization. The current release supports manual live first-response suggestions and chronological shadow replay; the independent audit has not granted autonomous read-only execution.

Use `make intelligence-setup`, `make up`, then open localhost8092. `make intelligence-test` runs isolated Docker tests. Replay a recorded dataset with `make intelligence-replay DATASET=<opaque-id>`, generate paired comparison with `make intelligence-report`, and export sealed bundles with `make intelligence-export`.

Use the [Calls workspace](../docs/call-investigations.md) to select a real HTTP attempt, then explicitly press **Explain this call**. Browsing and saved-result views never run inference. [Manual API/CLI contracts](../docs/phase4-live-questions.md) remain compatible for request/trace IDs and excerpts. Neither flow exposes fault truth or executes model-selected actions.

See [architecture](../docs/phase4-architecture.md), [operations](../docs/phase4-operations.md), [evaluation](../docs/phase4-evaluation.md), [acceptance](../docs/phase4-acceptance.md) and [remaining blockers](../docs/phase4-blockers.md). The runtime model/controller exclude evaluator labels and mutating tools. Mock inference exists only in the trusted test image and is marked CI fixture data.
