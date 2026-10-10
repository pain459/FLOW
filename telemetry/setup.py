"""One-off elevated statistics setup; runtime services never use this principal."""

import asyncio
import os
import asyncpg


async def main() -> None:
    connection = await asyncpg.connect(
        host="postgres",
        port=5432,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
        timeout=10,
    )
    try:
        await connection.execute("GRANT pg_monitor TO pulsepay_verifier")
        await connection.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        print("Read-only PostgreSQL statistics permissions and extension ready")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
