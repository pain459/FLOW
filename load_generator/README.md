# PulsePay workloads

The generator is an opt-in HTTP client subsystem. It imports API response schemas, configuration and the independent read-only verifier, but never mutates financial tables. The operator's shell invokes Docker; containers have no Docker socket or lifecycle privileges.

From the repository root:

```sh
make up
make load-preflight PROFILE=nominal
make load-smoke
make load-run PROFILE=write_heavy DURATION=120 USERS=20 RATE=20 WORKERS=2
make load-stop
make load-report
make load-test
```

Reports persist in the project's `load-reports` Docker volume and are exported under gitignored `artifacts/load-runs/`. See [operator guide](../docs/phase2-load-generator.md) and [methodology](../docs/workload-methodology.md). `WORKERS=2` uses pinned Locust's local master/worker processes inside the same bounded container. All processes share the container's CPU/memory ceiling. Separate-host workers are a future deployment choice, not a claimed tested feature.


Locust's UI is part of normal `make up`, at http://127.0.0.1:8089. It stays idle until Start and remains available after Stop. `make load-ui` ensures the service is running; `.env` defines LOCUST_PROFILE and LOCUST_DURATION_SECONDS. UI sessions share a traffic lock with headless profiles. There is no automatic background activity client. See [resource ceilings](../docs/resources.md).
