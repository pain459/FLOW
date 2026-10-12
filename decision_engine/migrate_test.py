import os

from alembic.config import Config
from alembic import command

os.environ["DECISION_MIGRATION_URL"] = (
    "postgresql+asyncpg://pulsepay_decision_migrator:"
    + os.environ["DECISION_MIGRATOR_PASSWORD"]
    + "@postgres:5432/pulsepay_decision_test"
)
command.upgrade(Config("alembic.decision.ini"), "head")
