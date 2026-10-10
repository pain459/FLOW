import subprocess
import sys
import time
import json
from datetime import datetime, timezone
import httpx
from load_generator.controller.schemas import Profile, validate_target
from load_generator.controller.reports import fingerprint


def independent_verification() -> dict:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "verifier.main", "--once"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        report = json.loads(result.stdout.strip().splitlines()[-1])
        if report.get("status") not in {"PASS", "FAIL", "UNKNOWN", "DEGRADED"}:
            raise ValueError("Invalid verification report")
        if (
            result.returncode
            != {"PASS": 0, "FAIL": 1, "UNKNOWN": 2, "DEGRADED": 3}[report["status"]]
        ):
            raise ValueError("Inconsistent verifier exit status")
        return report
    except (subprocess.TimeoutExpired, ValueError, IndexError, TypeError):
        return {
            "status": "UNKNOWN",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "reason": "VERIFIER_UNAVAILABLE_OR_INVALID",
            "checks": [],
        }


class Observer:
    def __init__(self, target: str):
        self.target = validate_target(target)
        self.client = httpx.Client(timeout=5, trust_env=False, follow_redirects=False)

    def get(self, path: str):
        response = self.client.get(self.target + path)
        response.raise_for_status()
        return response.json()

    def health(self):
        data = self.get("/health/dependencies")
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(data["observed_at"])
        ).total_seconds()
        if not 0 <= age < 30:
            raise ValueError("Stale dependency health")
        return data

    def discover(self, profile: Profile):
        rows, cursor = [], None
        for _ in range(10):
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = self.client.get(
                self.target + "/api/v1/dashboard/accounts", params=params
            )
            response.raise_for_status()
            page = response.json()
            rows.extend(page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        from load_generator.workloads.account_pool import AccountPool

        funded = [
            a
            for a in rows
            if a["status"] == "active"
            and int(a["balance_minor"]) >= profile.accounts.transfer_amount_minor_max
        ]
        if len(funded) < profile.accounts.minimum_funded_accounts:
            raise ValueError(
                "Insufficient funded accounts; run the explicit lab seed job before measuring"
            )
        pool = AccountPool(funded, profile.seed)
        dataset = {
            "account_ids": pool.ids,
            "currency": pool.currency,
            "funded_count": len(pool.ids),
            "total_funds_minor": self.get("/api/v1/dashboard")["totals"][
                "balance_minor"
            ],
            "initial_funding": [
                {
                    "id": account["id"],
                    "balance_minor": int(account["balance_minor"]),
                    "external_ref": account["external_ref"],
                }
                for account in sorted(funded, key=lambda account: account["id"])
            ],
        }
        return funded, dataset, fingerprint(dataset)

    def preflight(self, profile: Profile, metadata: dict, verification=None):
        for name in ("api", "postgres", "redis", "outbox-relay", "event-worker"):
            if not metadata.get("services", {}).get(name, {}).get("image_id"):
                raise ValueError("Missing Docker revision/ceiling evidence: " + name)
        self.get("/health/ready")
        health = self.health()
        if not health["core_transactions_ready"]:
            raise ValueError("Authoritative transactions are not ready")
        for name in ("postgres", "outbox-relay", "event-worker"):
            if health["dependencies"].get(name, {}).get("status") != "HEALTHY":
                raise ValueError("Required component is not healthy: " + name)
        if (
            profile.require_redis
            and health["dependencies"]["redis"]["status"] != "HEALTHY"
        ):
            raise ValueError("Profile requires healthy Redis")
        accounts, dataset, digest = self.discover(profile)
        report = verification or independent_verification()
        if report["status"] != "PASS":
            raise ValueError("Independent preflight integrity is " + report["status"])
        return {
            "health": health,
            "accounts": accounts,
            "dataset": dataset,
            "dataset_sha256": digest,
            "verification": report,
            "snapshot": self.get("/api/v1/dashboard"),
        }

    def cooldown(self, seconds: int):
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            try:
                last = self.get("/api/v1/dashboard")
                totals = last["totals"]
                if (
                    totals["outbox_pending"] == 0
                    and totals["projections"] == totals["transfers"]
                ):
                    return last
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            time.sleep(1)
        raise TimeoutError("Backlog did not settle within cooldown")

    def close(self):
        self.client.close()
