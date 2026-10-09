import asyncio
import json
from apps.pulsepay.application.account_service import seed
from apps.pulsepay.infrastructure.db import Database
from shared.config import Settings


async def main():
    config = Settings()
    db = Database(config)
    try:
        print(json.dumps(await seed(db, config)))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
