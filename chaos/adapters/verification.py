"""Call the existing independent SQL verifier with SELECT-only credentials."""

import asyncio
from shared.config import Settings
from verifier.main import reconcile


def collect():
    return asyncio.run(reconcile(Settings().database_url))
