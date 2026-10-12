"""Durable opaque call-to-analysis references; financial tables untouched."""

from alembic import op

revision = "di0003"
down_revision = "di0002"


def upgrade():
    op.execute("""CREATE TABLE decision_intel.call_analyses (
        session_id uuid PRIMARY KEY REFERENCES decision_intel.investigation_sessions(id),
        call_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute(
        "CREATE INDEX call_analyses_recent ON decision_intel.call_analyses(call_id,created_at DESC,session_id)"
    )
    op.execute("GRANT SELECT,INSERT ON decision_intel.call_analyses TO pulsepay_decision")
    op.execute("GRANT SELECT ON decision_intel.call_analyses TO pulsepay_evaluator")


def downgrade():
    raise RuntimeError("forward-only; retain call analysis evidence")
