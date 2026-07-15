import asyncio

import app.models  # noqa: F401 — register models with Base.metadata
from app.db import Base, engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully")


if __name__ == "__main__":
    asyncio.run(main())
