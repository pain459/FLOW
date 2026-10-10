# Phase 1 architecture

PulsePay is a synthetic transaction laboratory. Every unit is fake; no banking/payment/authentication integration exists.

```mermaid
flowchart TD
  Activity[HTTP activity client] --> API[FastAPI]
  API --> PG[(PostgreSQL)]
  API --> Cache[(Redis cache)]
  PG --> Relay[Leased outbox relay]
  Relay --> Stream[(Redis Stream)]
  Stream --> Worker[Consumer group worker]
  Worker --> PG
  Verify[Independent read-only verifier] --> PG
  API --> OTEL[OTel Collector]
  Relay --> OTEL
  Worker --> OTEL
  OTEL --> Tempo
  Docker[Docker Fluentd log driver] --> FluentBit[Fluent Bit]
  FluentBit --> Loki
  Prometheus --> API
  Prometheus --> Relay
  Prometheus --> Worker
  Prometheus --> Activity
  Prometheus --> Verify
  Grafana --> Prometheus
  Grafana --> Loki
  Grafana --> Tempo
```

API handlers validate/serialize; application services own transactions. PostgreSQL atomically commits balances, a transfer, two ledger entries and an outbox row. The HTTP result does not wait for event projection. Redis is never consulted to approve money movement. Cache invalidation happens after commit and can fail independently.

The relay leases up to 25 pending rows using `FOR UPDATE SKIP LOCKED`, commits the claim, publishes outside the DB transaction, then marks the row published. Expired 30-second leases recover interrupted claims. Publication may repeat after a crash; the consumer uses the stable event ID. Receipts and a notification projection commit together before XACK. XAUTOCLAIM reclaims deliveries idle for 10 seconds. A fresh group starts at stream ID 0, preserving existing events. Invalid messages are durably quarantined with original evidence before acknowledgement.

PostgreSQL, Redis, workers and telemetry backends use the internal network. API, Grafana, Prometheus and the log collector also use an edge network for loopback-only published ports. Docker 29 does not publish ports for an internal-only network in the tested Desktop environment. No application container mounts the Docker socket, runs privileged, or joins host namespaces.

Runtime app/worker/verifier credentials differ from migration and owner credentials. The activity container has no working DB credentials and only calls HTTP. The verifier has independent SQL and no imports of application models/services. Shared configuration, metrics and process hosting do not supply business logic.

Redis uses AOF with `appendfsync always` and `noeviction`: confirmed writes must be durable for the local transport guarantee; memory pressure rejects writes instead of silently evicting stream state. Stream transport remains at-least-once, with exactly-once logical projection effects. PostgreSQL evidence remains available after transport interruption.

Design references: [PostgreSQL row lock ordering](https://www.postgresql.org/docs/17/explicit-locking.html), [Redis XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/), [Docker Fluentd logging driver](https://docs.docker.com/engine/logging/drivers/fluentd/), [Fluent Bit Loki output](https://docs.fluentbit.io/manual/data-pipeline/outputs/loki/).

## Future contracts (definitions only)

Observation snapshot v1 is represented by `shared.contracts.ObservationSnapshot`: version, UTC observation time, window seconds, system, health, signals, freshness, and missing signal names. The illustration in the supplied spec is not a measurement. Missing/stale signals must remain UNKNOWN; do not infer health from an empty vector. Independent experiment IDs will live outside financial IDs. No hidden fault truth belongs in decision inputs.

Future load clients use public APIs. A future chaos operator remains outside the app stack and owns restoration safety privately. Laya receives observations and enumerated permitted choices, without Docker credentials or arbitrary shell powers. An approximator's estimates must be compared to observed outcomes. The verifier remains independent. No later-phase directories, decision/action loop, fault injection or autonomous remediation is implemented.

Future action envelope v1 is a documentation contract: `schema_version`, `action_id`, `experiment_id`, `idempotency_key`, enumerated `action_type`, allowlisted `target_service`, bounded `parameters`, `preconditions`, `expires_at` and `authorization_scope`. An executor must reject unknown actions, stale authorization, out-of-scope targets and missing preconditions. Results carry `action_id`, start/end times, outcome and safe evidence references. Permitted choices are supplied per experiment; Phase 1 neither enumerates executable chaos actions nor supplies an executor. Experiment/fault truth stays private to the external operator and does not enter observation inputs.
# Operator dashboard

The existing FastAPI service serves `/` and same-origin `/ui/*` assets. The browser consumes bounded read-only dashboard APIs and uses the original transactional write APIs for account creation and transfers. Independent verifier/activity reports remain separate processes, fetched through fixed server-side URLs with deadlines and freshness validation. See [dashboard boundaries](dashboard.md).
