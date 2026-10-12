"""Separate investigation history and evaluator privileges; public ledger untouched."""

from alembic import op

revision = "di0001"
down_revision = None


def upgrade():
    op.execute("REVOKE ALL ON SCHEMA decision_intel,decision_evaluation FROM PUBLIC")
    op.execute("""CREATE TABLE decision_intel.investigation_sessions (
        id uuid PRIMARY KEY, incident_key text NOT NULL, chaos_run_ref text, mode text NOT NULL CHECK(mode='shadow'),
        state text NOT NULL, requester text NOT NULL, idempotency_key text NOT NULL, request_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
        policy_version text NOT NULL, model_version text NOT NULL, budget jsonb NOT NULL,
        dataset_ref text NOT NULL, last_error text, recovery_status text NOT NULL DEFAULT 'UNKNOWN',
        UNIQUE(requester,idempotency_key))""")
    op.execute("CREATE INDEX sessions_date ON decision_intel.investigation_sessions(created_at,id)")
    op.execute("""CREATE TABLE decision_intel.observation_snapshots (
        id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES decision_intel.investigation_sessions,
        step int NOT NULL, observed_at timestamptz NOT NULL, window_seconds int NOT NULL,
        sanitized_payload jsonb NOT NULL, quality_flags jsonb NOT NULL, payload_hash text NOT NULL, UNIQUE(session_id,step))""")
    op.execute("""CREATE TABLE decision_intel.decision_requests (
        id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES decision_intel.investigation_sessions,
        step int NOT NULL, question_set_version text NOT NULL, state_hash text NOT NULL,
        available_actions jsonb NOT NULL, sent_at timestamptz NOT NULL DEFAULT now(), UNIQUE(session_id,step))""")
    op.execute("""CREATE TABLE decision_intel.decision_answers (
        request_id uuid PRIMARY KEY REFERENCES decision_intel.decision_requests,
        raw_answer_redacted jsonb NOT NULL, normalized_answers jsonb NOT NULL, distributions jsonb NOT NULL,
        validation_status text NOT NULL, provider_version text NOT NULL, latency_ms double precision,
        policy_decision jsonb NOT NULL, baseline_decision jsonb NOT NULL, ranking jsonb NOT NULL)""")
    op.execute("""CREATE TABLE decision_intel.tool_calls (
        id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES decision_intel.investigation_sessions,
        step int NOT NULL, tool_id text NOT NULL, validated_args jsonb NOT NULL, policy_verdict text NOT NULL,
        started_at timestamptz, ended_at timestamptz, status text NOT NULL, output_ref text, failure_reason text)""")
    op.execute("""CREATE TABLE decision_intel.evidence_items (
        id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES decision_intel.investigation_sessions,
        tool_call_id uuid REFERENCES decision_intel.tool_calls, source text NOT NULL,
        observed_at timestamptz NOT NULL, freshness jsonb NOT NULL, artifact_uri text NOT NULL, payload_hash text NOT NULL)""")
    op.execute("""CREATE TABLE decision_intel.session_conclusions (
        session_id uuid PRIMARY KEY REFERENCES decision_intel.investigation_sessions,
        suspected_components jsonb NOT NULL, evidence_refs jsonb NOT NULL, conclusion_type text NOT NULL,
        certainty_policy text NOT NULL, reason text NOT NULL)""")
    op.execute("""CREATE TABLE decision_intel.session_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, session_id uuid NOT NULL REFERENCES decision_intel.investigation_sessions,
        observed_at timestamptz NOT NULL DEFAULT now(), state text NOT NULL, reason text)""")
    op.execute("""CREATE TABLE decision_evaluation.evaluation_runs (
        id uuid PRIMARY KEY, dataset_ref text NOT NULL, split text NOT NULL, baseline_version text NOT NULL,
        model_version text NOT NULL, metrics jsonb NOT NULL, status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("""CREATE TABLE decision_evaluation.evaluation_items (
        run_id uuid NOT NULL REFERENCES decision_evaluation.evaluation_runs, session_ref uuid NOT NULL,
        ground_truth_ref text NOT NULL, expected_observed jsonb NOT NULL, scored_outcome jsonb NOT NULL,
        exclusions jsonb NOT NULL, PRIMARY KEY(run_id,session_ref))""")
    op.execute("GRANT USAGE ON SCHEMA decision_intel TO pulsepay_decision,pulsepay_evaluator")
    op.execute("GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA decision_intel TO pulsepay_decision")
    op.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA decision_intel TO pulsepay_decision")
    op.execute(
        "GRANT UPDATE(state,ended_at,last_error) ON decision_intel.investigation_sessions TO pulsepay_decision"
    )
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA decision_intel TO pulsepay_evaluator")
    op.execute("GRANT USAGE ON SCHEMA decision_evaluation TO pulsepay_evaluator")
    op.execute(
        "GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA decision_evaluation TO pulsepay_evaluator"
    )


def downgrade():
    raise RuntimeError("forward-only; do not erase investigation evidence")
