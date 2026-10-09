"""Foundation migration marker."""

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.execute(
        "GRANT SELECT ON alembic_version TO pulsepay_app, pulsepay_worker, pulsepay_verifier"
    )


def downgrade():
    pass
