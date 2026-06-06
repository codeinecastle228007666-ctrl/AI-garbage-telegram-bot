"""
Поиск всех баз данных Notion, доступных интеграции.

Запуск:
    python find_databases.py

Найди в списке «Моя коллекция программ и утилит» и скопируй её ID в .env → CONTENT_DATABASE_ID
"""

import asyncio
import os

from dotenv import load_dotenv
from httpx import AsyncClient

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
if not NOTION_TOKEN:
    print("❌ Укажите NOTION_TOKEN в .env")
    exit(1)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


async def main():
    async with AsyncClient(timeout=30) as client:
        # Поиск баз данных через search API
        payload = {
            "query": "",
            "filter": {"value": "database", "property": "object"},
        }
        r = await client.post(
            "https://api.notion.com/v1/search",
            headers=HEADERS,
            json=payload,
        )
        if r.status_code != 200:
            print(f"❌ Ошибка {r.status_code}: {r.text}")
            return

        data = r.json()
        results = data.get("results", [])
        if not results:
            print("❌ Не найдено ни одной базы данных.")
            print("   Убедитесь, что страница расшарена для интеграции.")
            return

        print(f"\n--- Найдено {len(results)} баз данных ---\n")
        for db in results:
            db_id = db["id"]
            title_parts = db.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts) if title_parts else "Без названия"
            url = db.get("url", "")
            print(f"[{title}]")
            print(f"  ID: {db_id}")
            print(f"  URL: {url}")
            print()

        print("=" * 60)
        print('Скопируй ID базы "Моя коллекция программ и утилит" в .env -> CONTENT_DATABASE_ID')


if __name__ == "__main__":
    asyncio.run(main())
