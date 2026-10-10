import httpx
from chaos import state

PROXIES = {
    "api_postgres": {"listen": "0.0.0.0:15432", "upstream": "postgres:5432"},
    "clients_redis": {"listen": "0.0.0.0:16379", "upstream": "redis:6379"},
}


def runtime_call(method, path, body=None):
    # This listener belongs to a separate control network, absent from runner
    # and application containers. Only the authorization gateway can reach it.
    with httpx.Client(
        base_url="http://toxiproxy-control:8474", timeout=5, trust_env=False
    ) as client:
        response = client.request(method, path, json=body)
        response.raise_for_status()
        return response.json() if response.content else None


def runtime_snapshot(name):
    if name not in PROXIES:
        raise ValueError("Unknown supported dependency proxy")
    current = runtime_call("GET", "/proxies/" + name)
    expected = PROXIES[name]
    listeners = {expected["listen"], "[::]:" + expected["listen"].rsplit(":", 1)[1]}
    if (
        current.get("listen") not in listeners
        or current.get("upstream") != expected["upstream"]
        or not current.get("enabled")
    ):
        raise ValueError("Proxy configuration does not match the healthy lab route")
    return current


def runtime_inject(lease):
    name = "api_postgres" if lease["scenario"] == "005-db-network-delay" else "clients_redis"
    if "proxy_before" not in lease:
        raise ValueError("Proxy restoration snapshot missing")
    if name == "api_postgres":
        runtime_call(
            "POST",
            "/proxies/" + name + "/toxics",
            {
                "name": lease["run_id"],
                "type": "latency",
                "stream": "downstream",
                "toxicity": 1.0,
                "attributes": {
                    "latency": lease["configuration"]["delay_ms"],
                    "jitter": 0,
                },
            },
        )
    else:
        runtime_call("POST", "/proxies/" + name, {"enabled": False})
    return {"confirmed": True}


def runtime_restore(lease):
    before = lease.get("proxy_before")
    if not before:
        return {"not_applicable": True}
    name = before["name"]
    current = runtime_call("GET", "/proxies/" + name)
    if any(current.get(k) != before[k] for k in ("listen", "upstream")):
        raise RuntimeError("Proxy route changed; manual restoration required")
    for toxic in current.get("toxics", []):
        if toxic["name"] == lease["run_id"]:
            runtime_call("DELETE", "/proxies/" + name + "/toxics/" + toxic["name"])
    runtime_call("POST", "/proxies/" + name, {"enabled": before["enabled"]})
    after = runtime_call("GET", "/proxies/" + name)
    if after.get("enabled") != before["enabled"] or after.get("toxics", []) != before.get(
        "toxics", []
    ):
        raise RuntimeError("Proxy restoration does not match the original state")
    return {"restored": True, "proxy": name, "state": after}


def snapshot(name):
    from chaos.docker_client import Docker

    if name not in PROXIES:
        raise ValueError("Unknown dependency proxy")
    return Docker().call("GET", "/lab/proxy/" + name)


def inject(lease):
    from chaos.docker_client import Docker

    result = Docker().call("POST", "/lab/proxy/inject", json={})
    if result.get("confirmed"):
        name = "api_postgres" if lease["scenario"] == "005-db-network-delay" else "clients_redis"
        state.safe_event("toxic_applied", proxy=name, experiment_owned_name=lease["run_id"])
    return result


def restore(lease):
    from chaos.docker_client import Docker

    if not lease.get("proxy_before"):
        return {"not_applicable": True}
    return Docker().call("POST", "/lab/proxy/restore", json={})
