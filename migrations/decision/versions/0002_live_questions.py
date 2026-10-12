"""Human-triggered first-response sessions; no autonomous execution permission."""

from alembic import op

revision = "di0002"
down_revision = "di0001"


def upgrade():
    op.execute(
        "ALTER TABLE decision_intel.investigation_sessions DROP CONSTRAINT investigation_sessions_mode_check"
    )
    op.execute(
        "ALTER TABLE decision_intel.investigation_sessions ADD CONSTRAINT investigation_sessions_mode_check CHECK(mode IN ('shadow','live_question'))"
    )


def downgrade():
    raise RuntimeError("forward-only; retain investigation evidence")
