import os
import uuid
from dataclasses import dataclass
import asyncio
import pytest_asyncio
import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from apps.pulsepay.infrastructure.db import Database
from shared.config import Settings


@dataclass(repr=False)
class Lab:
    db: Database
    admin: AsyncEngine
    client: httpx.AsyncClient
    worker_url: str
    verifier_url: str


@pytest_asyncio.fixture
async def lab():
    # Only generated disposable databases; never truncate/reseed baseline lab.
    name = "pulsepay_test_" + uuid.uuid4().hex
    admin_url = make_url(os.environ["TEST_ADMIN_URL"])
    root = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with root.connect() as connection:
        await connection.execute(text(f"CREATE DATABASE {name} OWNER pulsepay_migrator"))
    migration_url = make_url(os.environ["MIGRATOR_DATABASE_URL"]).set(database=name)
    env = dict(os.environ, DATABASE_URL=migration_url.render_as_string(hide_password=False))
    process = await asyncio.create_subprocess_exec(
        "alembic",
        "upgrade",
        "head",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout + stderr).decode()
    db = Database(
        Settings(
            database_url=make_url(os.environ["DATABASE_URL"])
            .set(database=name)
            .render_as_string(hide_password=False)
        )
    )
    admin = create_async_engine(admin_url.set(database=name))
    import apps.pulsepay.main as main

    original = main.db
    original_cache = main.cache
    from apps.pulsepay.infrastructure.redis import Cache

    cache = Cache(Settings(database_url=env["DATABASE_URL"]), namespace=name)
    main.db = db
    main.cache = cache
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        try:
            yield Lab(
                db,
                admin,
                client,
                make_url(os.environ["WORKER_DATABASE_URL"])
                .set(database=name)
                .render_as_string(hide_password=False),
                make_url(os.environ["VERIFIER_DATABASE_URL"])
                .set(database=name)
                .render_as_string(hide_password=False),
            )
        finally:
            main.db = original
            main.cache = original_cache
            await cache.close()
            await db.close()
            await admin.dispose()
            async with root.connect() as connection:
                await connection.execute(text(f"DROP DATABASE {name} WITH (FORCE)"))
            await root.dispose()
