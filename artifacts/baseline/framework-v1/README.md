# PulsePay framework experiment evidence

Qualification: **INCOMPLETE for the full catalog; six distinct scenarios qualified.** Actual Docker Desktop Linux arm64 results, 2026-10-10/11. See [acceptance](../../../docs/phase3-acceptance.md), [operations](../../../docs/phase3-operations.md) and `qualification.json` for exact outcomes, load links, image/source provenance and missing-evidence notes.

`evidence/experiments.tar.gz` retains the original exported run directories, including failed, invalid and interrupted attempts. Existing per-run SHA-256 seals were verified before packaging. `evidence/sustained-loads.tar.gz` contains complete linked workload evidence. These are privileged operator bundles: fault names, target truth, journals and injector details must never be given to a future decision-model observation consumer. Only the sanitized observation contract is intended for that boundary.

`checks/` retains exact test logs, live authorization checks, watchdog kill/abort results, dashboard evidence, final read-only verifier, health/resource ceilings, Docker environment and single-project cleanup proof. Top-level checksums cover the final curated files. Original histories are preserved; later interpretation or recovery acknowledgements never rewrite a sealed experiment.

Limits: CPU stress is disabled pending kernel containment proof; PostgreSQL outage restored financial integrity but safety-stopped its workload, with 51 unresolved client transfer outcomes. Early reports predate standalone ground-truth output, while evidence remains in metadata/timeline/injector/audit files. SIGKILL has a partial native journal and an ABORTED verdict. Native Linux and WSL2 remain untested.

The healthy reference is [workload-v3](../workload-v3/README.md), including three comparable nominal repeats and a full-hour soak. Final metrics/dashboard corrections change image provenance; those historical measurements are not a controlled performance comparison with the final image.
