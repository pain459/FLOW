# Operations and failure boundaries

Docker/Compose are required. `make` is a convenience; every script invokes Docker/Compose and ordinary shell utilities, never host Python/PostgreSQL/Redis. Generate local credentials with `sh scripts/bootstrap.sh`. Bootstrap never overwrites an existing `.env`; it is mode 0600 and ignored by Git/Docker build context. Generated secrets are URL-safe hex and role-specific. Changing passwords in `.env` alone does not change an existing PostgreSQL role: update the role intentionally or reset a disposable lab.

Core idle: `docker compose up --build -d`. Seed: `make seed`. Breathe: `make breathe` seeds, overrides ACTIVITY_ENABLED=true, enables activity+observability and starts the read-only verifier. `make stop-breathe` stops only HTTP activity. `make verify` runs the read-only CLI once (exits 0/1/2/3). `make down` retains all volumes. `make status`, `make logs`, `make smoke`, `make test`, `make lint`, `make observe-test`, `make baseline` provide operator checks. Verify mode should follow stop-breathe for a quiescent snapshot; the verifier is also safe while writes run.

Activity modes: off disables requests; steady uses uniform low-rate pacing; mixed adds mild deterministic-seed jitter. Total HTTP rate is capped at the configured 1–5 RPS range, concurrency 1–4; default 2 RPS, 60% reads/40% writes, 200 seeded accounts, uniform 1–100 minor-unit amounts. Reads are split among balances/history/summary; random bidirectional transfers avoid one-way draining. Client balance hints use seed manifest and authoritative HTTP reads; PostgreSQL always independently checks actual funds. Deliberate retries keep identical payload/key, at most three attempts with bounded backoff. Errors remain in metrics/logs; an exhausted request does not terminate the process.

| Service | Health semantics | Persistence / restart / shutdown | Budget |
|---|---|---|---|
| api | live has no dependency calls; ready requires DB/schema; dependencies shows cache degradation and heartbeat ages | no local financial state; unless-stopped; 20s grace, uvicorn 15s graceful budget | 384 MiB / 1 CPU; DB pool 8, no overflow |
| postgres | pg_isready plus API schema readiness | pg-data volume; unless-stopped; 30s grace, WAL recovery | 768 MiB / 1 CPU |
| redis | PING plus worker/cache signals | redis-data AOF/fsync always, noeviction; unless-stopped; 15s grace | 256 MiB / 0.5 CPU; data cap 128 MiB |
| outbox-relay | live independent; productive status + durable heartbeat; pending age/count | leased PostgreSQL outbox; retry forever with bounded per-attempt backoff; unless-stopped; 20s grace | 384 MiB / 1 CPU; batch 25 |
| event-worker | live independent; productive status, PEL idle/lag + heartbeat | receipts/projections/quarantine in PG; Redis PEL reclaimed; unless-stopped; 20s grace | 384 MiB / 1 CPU; batches ≤50 |
| verifier | live process; latest report/metrics PASS/FAIL/UNKNOWN/DEGRADED, timestamp | SELECT-only full snapshot every 15s; no writes; unless-stopped; 20s grace | 384 MiB / 1 CPU; one DB connection/check |
| activity | live process independent of API; own outcome/freshness signals | no authoritative state/DB credentials; unless-stopped; 20s grace | 384 MiB / 1 CPU; four HTTP connections |
| prometheus | `/-/ready`, scrape up and collector metrics | prom-data; unless-stopped; 20s grace; 24h/256 MiB retention | 384 MiB / 0.5 CPU |
| grafana | `/api/health`, provisioned datasource checks | grafana-data; unless-stopped; 20s grace | 384 MiB / 0.5 CPU |
| otel-collector | health extension 13133 and export-failure metrics 8888 | bounded memory queue; unless-stopped; 15s grace | 256 MiB / 0.5 CPU |
| tempo | `/ready`, trace search/read | tempo-data; unless-stopped; 20s grace; 24h retention | 384 MiB / 0.5 CPU |
| loki | `/ready`, ingestion and query responses | loki-data; unless-stopped; 20s grace; 24h retention | 384 MiB / 0.5 CPU |
| log-collector | HTTP 2020, Forward ingestion, Loki delivery metrics | log-buffer ≤64 MiB; unless-stopped; 10s grace | 128 MiB / 0.25 CPU |
| migrate / seed / tests | exit code of one-off job; migrate must complete before serving | no restart; explicit Docker jobs; tests use disposable DBs only | 384 MiB / 1 CPU |
| telemetry-init | one-off exit code; ownership of only lab telemetry volumes | no restart | 32 MiB / 0.25 CPU |

Docker Compose/Desktop enforces mem_limit/cpus in the tested engine; desktop VM capacity must also accommodate the stack. Process health is distinct from productive progress. DB/Redis dependency outages never fail API liveness. A stale (>30s) worker heartbeat is UNKNOWN. Full functionality may be DEGRADED while core transfers remain ready. Missing instrumentation acknowledgement is reported UNKNOWN, not assumed delivered.

Application logs are JSON to stdout. Infra logs remain available with `docker compose logs <service>`; infrastructure uses bounded JSON-file logging (10 MiB × 3). Worker SIGTERM cancels polling after finishing/cancelling the current async operation: leases expire and unacknowledged deliveries can be reclaimed. Receipt commit before ACK and publish-before-marker can cause repeated delivery; they do not repeat money movement.

Recovery: restart a service with `docker compose restart <service>`. During Redis outage, transfers still commit and outbox ages grow; restore Redis, wait for relay retries and worker lag to drain, then run `make verify`. During DB outage, live remains 200, ready becomes 503, verifier becomes UNKNOWN. Restore DB and wait for schema-ready status before retrying writes with the same keys. No automatic chaos or remediation controller exists.

Destructive reset is deliberately opt-in:

```sh
CONFIRM_RESET=chaosloop make reset-lab
make bootstrap
make up
make seed
```

The reset script checks acknowledgement AND effective Compose project name `chaosloop`, then removes only project containers/volumes. It never prunes the Docker daemon. Retain baseline artifacts first; those files are outside Docker data volumes. The accepted recovery tests retain Redis persistence. Deleting only the Redis volume can lose already-published messages; PostgreSQL evidence survives, but no automatic replay or replay command is supplied in Phase 1. Treat that deliberate data deletion as a separate operator investigation, not ordinary restart recovery.

If a gate fails, retain test output, safe JSON logs, verifier report and Compose state in artifacts. Do not print `docker compose config` or raw environment/DSNs to logs: they contain local passwords. Runtime roles must never be replaced by the owner/migrator credentials.
