"""Server-owned localhost Grafana links; no user-provided destinations."""

import json
import os
from datetime import timedelta
from urllib.parse import urlencode

from decision_engine.models.calls import Call


def grafana_links(raw):
    call = Call.model_validate(raw)
    port = int(os.environ.get("GRAFANA_PORT", "3000"))
    if not 1 <= port <= 65535:
        raise ValueError("invalid Grafana port")
    base = f"http://127.0.0.1:{port}/explore?"
    window = {
        "from": (call.started_at - timedelta(seconds=30)).isoformat(),
        "to": (call.completed_at + timedelta(minutes=5)).isoformat(),
    }

    def link(uid, query):
        pane = {
            "A": {
                "datasource": uid,
                "queries": [{"refId": "A", "datasource": {"type": uid, "uid": uid}, **query}],
                "range": window,
            }
        }
        return base + urlencode(
            {"schemaVersion": 1, "panes": json.dumps(pane, separators=(",", ":"))}
        )

    return {
        "logs": link(
            "loki",
            {
                "expr": '{service=~"api|outbox-relay|event-worker"} | json | call_id="'
                + str(call.id)
                + '"',
                "queryType": "range",
            },
        ),
        "trace": link("tempo", {"query": call.trace_id, "queryType": "traceId"})
        if call.trace_id
        else None,
    }
