import json
from uuid import UUID

import asyncpg


class Store:
    def __init__(self, pool):
        self.pool = pool

    @classmethod
    async def open(cls, url):
        if not url.startswith("postgresql://pulsepay_decision:") or "@postgres:5432/" not in url:
            raise ValueError("decision store target/role not allowlisted")

        async def init(c):
            await c.set_type_codec(
                "jsonb", schema="pg_catalog", encoder=json.dumps, decoder=json.loads, format="text"
            )

        return cls(
            await asyncpg.create_pool(
                url, min_size=1, max_size=2, command_timeout=5, timeout=3, init=init
            )
        )

    async def get(self, identifier):
        async with self.pool.acquire(timeout=3) as c:
            row = await c.fetchrow(
                "SELECT * FROM decision_intel.investigation_sessions WHERE id=$1",
                UUID(str(identifier)),
            )
            if not row:
                return None
            result = dict(row)
            conclusion = await c.fetchrow(
                "SELECT * FROM decision_intel.session_conclusions WHERE session_id=$1", row["id"]
            )
            result["conclusion"] = dict(conclusion) if conclusion else None
            return result

    async def list(self, limit=25, offset=0):
        async with self.pool.acquire(timeout=3) as c:
            return [
                dict(row)
                for row in await c.fetch(
                    "SELECT id,state,mode,dataset_ref,created_at,ended_at,last_error,recovery_status FROM decision_intel.investigation_sessions ORDER BY created_at DESC,id DESC LIMIT $1 OFFSET $2",
                    limit,
                    offset,
                )
            ]

    async def timeline(self, identifier):
        async with self.pool.acquire(timeout=3) as c:
            uid = UUID(str(identifier))
            decisions = await c.fetch(
                "SELECT r.step,r.sent_at,r.question_set_version,r.state_hash,a.*,o.sanitized_payload AS observation FROM decision_intel.decision_requests r LEFT JOIN decision_intel.decision_answers a ON a.request_id=r.id JOIN decision_intel.observation_snapshots o ON o.session_id=r.session_id AND o.step=r.step WHERE r.session_id=$1 ORDER BY r.step",
                uid,
            )
            events = await c.fetch(
                "SELECT observed_at,state,reason FROM decision_intel.session_events WHERE session_id=$1 ORDER BY id LIMIT 64",
                uid,
            )
            return {
                "decisions": [dict(row) for row in decisions],
                "events": [dict(row) for row in events],
                "tool_calls": [
                    dict(row)
                    for row in await c.fetch(
                        "SELECT * FROM decision_intel.tool_calls WHERE session_id=$1 ORDER BY step LIMIT 8",
                        uid,
                    )
                ],
            }

    async def transition(self, uid, state, reason=None, *, force=False):
        if state not in {
            "COLLECTING",
            "DECIDING",
            "EVALUATING",
            "INCONCLUSIVE",
            "ESCALATED",
            "TIMED_OUT",
            "CANCELLED",
            "ERROR",
        }:
            raise ValueError("unregistered session transition")
        if force and state != "ERROR":
            raise ValueError("only evidence failure can override a terminal state")
        async with self.pool.acquire(timeout=3) as c, c.transaction():
            changed = await c.fetchval(
                "UPDATE decision_intel.investigation_sessions SET state=$2,last_error=$3,ended_at=CASE WHEN $2=ANY($4::text[]) THEN now() ELSE NULL END WHERE id=$1 AND (ended_at IS NULL OR $5) RETURNING id",
                uid,
                state,
                reason,
                ["CONCLUDED", "ESCALATED", "INCONCLUSIVE", "TIMED_OUT", "CANCELLED", "ERROR"],
                force,
            )
            if changed is None:
                return False
            await c.execute(
                "INSERT INTO decision_intel.session_events(session_id,state,reason) VALUES($1,$2,$3)",
                uid,
                state,
                reason,
            )
            return True
