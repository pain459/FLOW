"""Ledger, financial core, outbox, and durable consumer evidence."""

from alembic import op

revision = "0002"
down_revision = "0001"

DDL = [
    """CREATE TABLE accounts (
        id uuid PRIMARY KEY, external_ref text UNIQUE NOT NULL,
        currency char(3) NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
        balance_minor bigint NOT NULL CHECK(balance_minor>=0),
        status text NOT NULL CHECK(status IN ('active','suspended','closed')),
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())""",
    "CREATE INDEX accounts_status_date ON accounts(status, created_at)",
    """CREATE TABLE transfers (
        id uuid PRIMARY KEY, source_account_id uuid NOT NULL REFERENCES accounts,
        destination_account_id uuid NOT NULL REFERENCES accounts,
        amount_minor bigint NOT NULL CHECK(amount_minor>0), currency char(3) NOT NULL,
        idempotency_key text NOT NULL UNIQUE, request_hash text NOT NULL,
        status text NOT NULL CHECK(status='committed'),
        created_at timestamptz NOT NULL DEFAULT now(), committed_at timestamptz NOT NULL DEFAULT now(),
        CHECK(source_account_id<>destination_account_id))""",
    "CREATE INDEX transfers_source_date ON transfers(source_account_id,created_at,id)",
    "CREATE INDEX transfers_destination_date ON transfers(destination_account_id,created_at,id)",
    """CREATE TABLE seed_runs (
        id uuid PRIMARY KEY, version text NOT NULL UNIQUE, account_count integer NOT NULL CHECK(account_count>0),
        balance_per_account bigint NOT NULL CHECK(balance_per_account>0), currency char(3) NOT NULL,
        issued_minor bigint NOT NULL CHECK(issued_minor>0), created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE ledger_entries (
        id uuid PRIMARY KEY, transfer_id uuid REFERENCES transfers, seed_run_id uuid REFERENCES seed_runs,
        account_id uuid NOT NULL REFERENCES accounts, entry_kind text NOT NULL,
        signed_amount_minor bigint NOT NULL, currency char(3) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK ((entry_kind='provisioning' AND transfer_id IS NULL AND seed_run_id IS NOT NULL AND signed_amount_minor>0)
          OR (entry_kind='transfer_debit' AND transfer_id IS NOT NULL AND seed_run_id IS NULL AND signed_amount_minor<0)
          OR (entry_kind='transfer_credit' AND transfer_id IS NOT NULL AND seed_run_id IS NULL AND signed_amount_minor>0)))""",
    "CREATE UNIQUE INDEX ledger_transfer_kind ON ledger_entries(transfer_id,entry_kind) WHERE transfer_id IS NOT NULL",
    "CREATE UNIQUE INDEX ledger_provisioning ON ledger_entries(seed_run_id,account_id) WHERE entry_kind='provisioning'",
    "CREATE INDEX ledger_account_date ON ledger_entries(account_id,created_at,id)",
    """CREATE TABLE outbox_events (
        id uuid PRIMARY KEY, aggregate_type text NOT NULL, aggregate_id uuid NOT NULL REFERENCES transfers,
        event_type text NOT NULL, schema_version integer NOT NULL, payload jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
        publish_attempts integer NOT NULL DEFAULT 0, last_error text,
        claim_token uuid, lease_until timestamptz, next_attempt_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE(aggregate_id,event_type))""",
    "CREATE INDEX outbox_pending ON outbox_events(published_at,created_at)",
    """CREATE TABLE consumer_receipts (
        consumer_name text NOT NULL, event_id uuid NOT NULL REFERENCES outbox_events,
        processed_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(consumer_name,event_id))""",
    """CREATE TABLE event_projections (
        event_id uuid PRIMARY KEY REFERENCES outbox_events, transfer_id uuid NOT NULL REFERENCES transfers,
        projection_type text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE(transfer_id,projection_type))""",
    """CREATE TABLE event_quarantine (
        stream_id text PRIMARY KEY, original jsonb NOT NULL, reason text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE service_heartbeats (
        service text PRIMARY KEY, status text NOT NULL, observed_at timestamptz NOT NULL DEFAULT now(),
        last_success_at timestamptz, last_failure_at timestamptz, reason text)""",
    """CREATE FUNCTION immutable_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'ledger is immutable'; END $$""",
    "CREATE TRIGGER ledger_immutable BEFORE UPDATE OR DELETE ON ledger_entries FOR EACH ROW EXECUTE FUNCTION immutable_ledger()",
    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO pulsepay_verifier",
    "GRANT SELECT ON accounts,transfers,ledger_entries,seed_runs,outbox_events,service_heartbeats,consumer_receipts,event_projections,event_quarantine TO pulsepay_app",
    "GRANT INSERT ON accounts,transfers,ledger_entries,seed_runs,outbox_events TO pulsepay_app",
    "GRANT UPDATE(balance_minor,status,updated_at) ON accounts TO pulsepay_app",
    "GRANT SELECT ON outbox_events,transfers,consumer_receipts,event_projections,event_quarantine,service_heartbeats TO pulsepay_worker",
    "GRANT UPDATE(published_at,publish_attempts,last_error,claim_token,lease_until,next_attempt_at) ON outbox_events TO pulsepay_worker",
    "GRANT INSERT ON consumer_receipts,event_projections,event_quarantine,service_heartbeats TO pulsepay_worker",
    "GRANT UPDATE ON service_heartbeats TO pulsepay_worker",
]


def upgrade():
    for sql in DDL:
        op.execute(sql)


def downgrade():
    raise RuntimeError(
        "Financial baseline migrations are forward-only; reset disposable lab instead"
    )
