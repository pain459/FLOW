import random
from uuid import UUID


class AccountPool:
    def __init__(self, accounts: list[dict], seed: int, hot_count: int | None = None):
        rows = sorted(
            (a for a in accounts if a["status"] == "active" and int(a["balance_minor"]) > 0),
            key=lambda a: a["id"],
        )
        if len(rows) < 2 or len({a["currency"] for a in rows}) != 1:
            raise ValueError("At least two funded active accounts in one currency are required")
        for row in rows:
            UUID(row["id"])
        self.accounts = rows[:hot_count] if hot_count else rows
        if len(self.accounts) < 2:
            raise ValueError("Account subset is too small")
        self.random = random.Random(seed)
        self.currency = self.accounts[0]["currency"]
        self.ids = [a["id"] for a in self.accounts]

    def account(self) -> str:
        return self.random.choice(self.ids)

    def pair(self) -> tuple[str, str]:
        source, destination = self.random.sample(self.ids, 2)
        return source, destination
