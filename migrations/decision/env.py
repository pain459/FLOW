import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine


def migrate(connection):
    context.configure(
        connection=connection, version_table="schema_version", version_table_schema="decision_intel"
    )
    with context.begin_transaction():
        context.run_migrations()


async def main():
    engine = create_async_engine(os.environ["DECISION_MIGRATION_URL"])
    async with engine.connect() as c:
        await c.run_sync(migrate)
    await engine.dispose()


asyncio.run(main())
