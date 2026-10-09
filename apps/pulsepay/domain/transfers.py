import hashlib
import json
from apps.pulsepay.schemas.transfers import TransferRequest

MAX_MINOR = 2**63 - 1


def request_hash(request: TransferRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
