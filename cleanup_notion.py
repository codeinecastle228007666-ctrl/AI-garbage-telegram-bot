import asyncio
import os
import sys

from dotenv import load_dotenv
from httpx import AsyncClient

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
if not NOTION_TOKEN:
    print("NOTION_TOKEN не задан")
    sys.exit(1)

TO_DELETE = [
    "3775e757-ff6b-81a8-9bd2-d88f52ff3631",
    "3775e757-ff6b-8122-b2a6-df06dbc753b7",
    "3775e757-ff6b-8149-9beb-cd6d05029658",
    "3775e757-ff6b-8187-ab19-f8ced7cdf141",
]

async def main():
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    async with AsyncClient(timeout=30) as c:
        for db_id in TO_DELETE:
            print(f"Архивирую {db_id}...", end=" ")
            r = await c.patch(
                f"https://api.notion.com/v1/blocks/{db_id}",
                headers=headers,
                json={"archived": True},
            )
            if r.status_code == 200:
                print("OK")
            else:
                print(f"Ошибка {r.status_code}: {r.text[:100]}")

if __name__ == "__main__":
    asyncio.run(main())
