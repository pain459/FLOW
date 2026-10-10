"""Read-only, bounded PostgreSQL operational evidence without SQL text labels."""

import asyncio
import math
import time
from prometheus_client import Gauge
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from shared.config import Settings
from shared.runtime import run_component

FIELDS = (
    "connections",
    "max_connections",
    "connection_usage_percent",
    "active_connections",
    "idle_connections",
    "lock_waits",
    "oldest_lock_wait_seconds",
    "long_running_queries",
    "deadlocks",
    "commits",
    "rollbacks",
    "statement_calls",
    "statement_execution_seconds",
    "statement_max_duration_seconds",
    "slow_statement_fingerprints",
    "blocks_read",
    "blocks_hit",
)
VALUES = {
    name: Gauge("pulsepay_database_" + name, "Observed PostgreSQL " + name) for name in FIELDS
}
LAST_SUCCESS = Gauge(
    "pulsepay_database_observed_timestamp_seconds", "Last complete read-only sample"
)

SQL = """SELECT
 (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()) AS connections,
 current_setting('max_connections')::int AS max_connections,
 (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='active') AS active_connections,
 (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle') AS idle_connections,
 (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock') AS lock_waits,
 (SELECT coalesce(max(extract(epoch FROM now()-query_start)),0) FROM pg_stat_activity
  WHERE datname=current_database() AND wait_event_type='Lock') AS oldest_lock_wait_seconds,
 (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='active'
  AND pid<>pg_backend_pid() AND query_start<now()-interval '250 milliseconds') AS long_running_queries,
 deadlocks, xact_commit AS commits, xact_rollback AS rollbacks, blks_read AS blocks_read, blks_hit AS blocks_hit,
 (SELECT coalesce(sum(calls),0) FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())) AS statement_calls,
 (SELECT coalesce(sum(total_exec_time)/1000,0) FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())) AS statement_execution_seconds,
 (SELECT coalesce(max(max_exec_time)/1000,0) FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())) AS statement_max_duration_seconds,
 (SELECT count(*) FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND max_exec_time>=250) AS slow_statement_fingerprints
 FROM pg_stat_database WHERE datname=current_database()"""


def decode_snapshot(row: dict) -> dict:
    result = {name: float(row[name]) if row.get(name) is not None else None for name in FIELDS}
    connections, ceiling = result["connections"], result["max_connections"]
    result["connection_usage_percent"] = (
        connections / ceiling * 100 if connections is not None and ceiling else None
    )
    return result


class DatabaseObserver:
    health = "UNKNOWN"

    def __init__(self, config: Settings):
        self.engine = create_async_engine(
            config.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=3,
            connect_args={
                "timeout": 3,
                "command_timeout": 3,
                "server_settings": {"statement_timeout": "3000"},
            },
        )

    async def tick(self) -> int:
        try:
            async with self.engine.connect() as connection, connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                row = (await connection.execute(text(SQL))).mappings().one()
            values = decode_snapshot(dict(row))
            for name, value in values.items():
                VALUES[name].set(value if value is not None else math.nan)
            LAST_SUCCESS.set(time.time())
            self.health = "HEALTHY"
        except Exception:
            for metric in VALUES.values():
                metric.set(math.nan)
            self.health = "UNKNOWN"
        return 0


async def main() -> None:
    config = Settings()
    observer = DatabaseObserver(config)
    try:
        await run_component(observer, config, interval=5)
    finally:
        await observer.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
