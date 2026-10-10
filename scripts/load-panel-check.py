"""Readonly live dashboard gate; execute with the Compose tests container."""

import json
import math
import os
from pathlib import Path
import httpx


def main():
    dashboard = json.loads(
        Path("observability/grafana/dashboards/load-and-capacity.json").read_text()
    )
    checked = []
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.get(
            "http://grafana:3000/api/dashboards/uid/" + dashboard["uid"],
            auth=httpx.BasicAuth("admin", os.environ["GRAFANA_PASSWORD"]),
        )
        response.raise_for_status()
        assert response.json()["meta"]["provisioned"]
        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                response = client.get(
                    "http://prometheus:9090/api/v1/query", params={"query": target["expr"]}
                )
                response.raise_for_status()
                data = response.json()
                assert data["status"] == "success" and data["data"]["result"], panel["title"]
                assert all(
                    math.isfinite(float(row["value"][1])) for row in data["data"]["result"]
                ), panel["title"]
                checked.append(panel["title"])
    print(
        json.dumps(
            {
                "status": "PASS",
                "dashboard": dashboard["uid"],
                "checked_queries": len(checked),
                "panels": sorted(set(checked)),
            }
        )
    )


if __name__ == "__main__":
    main()
