import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from shared.config import Settings


def run_sync(connection):
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run():
    engine = create_async_engine(Settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_sync)
    await engine.dispose()


asyncio.run(run())
