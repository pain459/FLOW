from dataclasses import dataclass
from uuid import uuid4
import json


@dataclass(frozen=True)
class TransferIntent:
    key: str
    body: str

    @classmethod
    def new(cls, source: str, destination: str, amount: int, currency: str):
        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or not 1 <= amount <= 2**63 - 1
        ):
            raise ValueError("Amount is outside BIGINT bounds")
        return cls(
            "load-" + uuid4().hex,
            json.dumps(
                {
                    "source_account_id": source,
                    "destination_account_id": destination,
                    "amount_minor": amount,
                    "currency": currency,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def retry(self):
        return self
