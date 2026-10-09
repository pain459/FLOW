from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from shared.config import Settings
from shared import metrics
from sqlalchemy import event
import time

SCHEMA_REVISION = "0002"


class Database:
    def __init__(self, config: Settings):
        self.engine = create_async_engine(
            config.database_url,
            hide_parameters=True,
            pool_size=config.db_pool_size,
            max_overflow=0,
            pool_timeout=config.db_timeout_seconds,
            pool_pre_ping=True,
            connect_args={
                "timeout": config.db_timeout_seconds,
                "command_timeout": config.db_timeout_seconds,
                "server_settings": {"statement_timeout": "5000", "lock_timeout": "3000"},
            },
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        event.listen(
            self.engine.sync_engine, "checkout", lambda *args: metrics.pool_checked_out.inc()
        )
        event.listen(
            self.engine.sync_engine, "checkin", lambda *args: metrics.pool_checked_out.dec()
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        started = time.monotonic()
        async with self.engine.connect() as connection:
            metrics.pool_wait.observe(time.monotonic() - started)
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                yield session

    async def ready(self) -> bool:
        async with self.session() as session:
            return (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                == SCHEMA_REVISION
            )

    async def close(self) -> None:
        await self.engine.dispose()
