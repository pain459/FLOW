# Independent integrity checks

For account a: `stored_balance(a) = sum(ledger signed amounts for a)`.
For successful internal transfer t: one debit on its source and one credit on its destination, both in its currency, with magnitudes equal to its amount; `sum(entries(t)) = 0`.
Across all accounts, including suspended/closed: `sum(balances) = sum(explicit provisioning)`.

Provisioning must match each seed run's account count, amount per account, currency and total issuance. Transfers require positive amount, distinct accounts, unique IDs/keys and consistent currency. Each transfer must have exactly one well-formed outbox event with matching ID and payload. Durable event schema/metadata corruption is FAIL immediately. A projection must have a matching atomic `projection-v1` receipt and authoritative transfer identity; duplicate logical effects are FAIL.

`verifier/invariants/` contains independent SQL, not application models or services. All cross-table scans execute in one PostgreSQL REPEATABLE READ, READ ONLY transaction using the SELECT-only principal. The report includes actual transaction settings, check/run times, inspected record counts, violation counts, totals and operational lag.

Statuses/CLI exits/metric values: PASS=0, FAIL=1, UNKNOWN=2, DEGRADED=3. Unreachable/incompatible database replaces every check with UNKNOWN and no totals; it never reuses an old PASS. A future expensive scan may sample/incrementally reconcile, but Phase 1 scans every financial row. Sampling must not be presented as a full proof.

Unpublished outbox age over 30 seconds, overdue projections over 30 seconds, or quarantine evidence produce DEGRADED, distinct from fund corruption. Fresh unprocessed asynchronous events are expected during a valid transfer; receipts/projections are checked when present. Quarantine remains visible for operator investigation. There is no end-to-end exactly-once transport claim.

Tests create a fresh `pulsepay_test_<uuid>` database per test, migrate it, execute financial operations using the app role, and drop only that generated database in teardown. Negative fixtures use an elevated test connection to disable protections ONLY there. Tested faults include imbalance, missing outbox, duplicate projection, invalid account state, redistribution of provisioning with unchanged global totals, and malformed durable event metadata/keys/version. They never corrupt the normal lab database.
