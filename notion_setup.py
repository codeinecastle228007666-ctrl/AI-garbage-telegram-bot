"""
Скрипт для создания служебных баз данных Notion,
необходимых для работы бота (пользователи, подписки, расписания, логи).

Запуск:
    python notion_setup.py

После выполнения скопируй полученные ID баз в .env файл.
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from notion_client import NotionClient

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("notion_setup")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID", "")

if not NOTION_TOKEN or not PARENT_PAGE_ID:
    print("Укажите NOTION_TOKEN и NOTION_PARENT_PAGE_ID в .env файле.")
    sys.exit(1)


async def setup():
    client = NotionClient(NOTION_TOKEN)
    results = {}

    # --- 1. Пользователи ---
    logger.info("Создаю БД «Пользователи»...")
    users_db = await client.create_database(PARENT_PAGE_ID, "Пользователи", {
        "Name": {"title": {}},
        "Telegram ID": {"number": {}},
        "Username": {"rich_text": {}},
        "First Name": {"rich_text": {}},
        "Last Name": {"rich_text": {}},
        "Is Active": {"checkbox": {}},
        "Created At": {"date": {}},
        "Updated At": {"date": {}},
    })
    users_db_id = users_db["id"]
    results["NOTION_USERS_DB_ID"] = users_db_id
    logger.info("  ID: %s", users_db_id)

    # --- 2. Подписки (без relation, используем Telegram ID) ---
    logger.info("Создаю БД «Подписки»...")
    subs_db = await client.create_database(PARENT_PAGE_ID, "Подписки", {
        "Name": {"title": {}},
        "Telegram ID": {"number": {}},
        "Notification Type": {"select": {
            "options": [
                {"name": "daily_digest", "color": "blue"},
                {"name": "weekly_report", "color": "green"},
                {"name": "system_alert", "color": "red"},
                {"name": "promo", "color": "yellow"},
                {"name": "custom", "color": "gray"},
            ]
        }},
        "Is Enabled": {"checkbox": {}},
        "Created At": {"date": {}},
    })
    subs_db_id = subs_db["id"]
    results["NOTION_SUBSCRIPTIONS_DB_ID"] = subs_db_id
    logger.info("  ID: %s", subs_db_id)

    # --- 3. Расписания (без relation, используем Telegram ID) ---
    logger.info("Создаю БД «Расписания»...")
    sched_db = await client.create_database(PARENT_PAGE_ID, "Расписания", {
        "Name": {"title": {}},
        "Telegram ID": {"number": {}},
        "Notification Type": {"select": {
            "options": [
                {"name": "daily_digest", "color": "blue"},
                {"name": "weekly_report", "color": "green"},
                {"name": "system_alert", "color": "red"},
                {"name": "promo", "color": "yellow"},
                {"name": "custom", "color": "gray"},
            ]
        }},
        "Interval Minutes": {"number": {}},
        "Time From": {"rich_text": {}},
        "Time To": {"rich_text": {}},
        "Is Active": {"checkbox": {}},
        "Created At": {"date": {}},
    })
    sched_db_id = sched_db["id"]
    results["NOTION_SCHEDULES_DB_ID"] = sched_db_id
    logger.info("  ID: %s", sched_db_id)

    # --- 4. Логи уведомлений ---
    logger.info("Создаю БД «Логи уведомлений»...")
    logs_db = await client.create_database(PARENT_PAGE_ID, "Логи уведомлений", {
        "Name": {"title": {}},
        "Telegram ID": {"number": {}},
        "Notification Type": {"select": {
            "options": [
                {"name": "daily_digest", "color": "blue"},
                {"name": "weekly_report", "color": "green"},
                {"name": "system_alert", "color": "red"},
                {"name": "promo", "color": "yellow"},
                {"name": "custom", "color": "gray"},
            ]
        }},
        "Title": {"rich_text": {}},
        "Message": {"rich_text": {}},
        "Status": {"select": {
            "options": [
                {"name": "sent", "color": "green"},
                {"name": "error", "color": "red"},
            ]
        }},
        "Sent At": {"date": {}},
    })
    logs_db_id = logs_db["id"]
    results["NOTION_LOGS_DB_ID"] = logs_db_id
    logger.info("  ID: %s", logs_db_id)

    # --- 5. Отслеживаемые каналы ---
    logger.info("Создаю БД «Отслеживаемые каналы»...")
    watch_db = await client.create_database(PARENT_PAGE_ID, "Отслеживаемые каналы", {
        "Name": {"title": {}},
        "Username": {"rich_text": {}},
        "Added By": {"number": {}},
        "Is Active": {"checkbox": {}},
        "Created At": {"date": {}},
    })
    watch_db_id = watch_db["id"]
    results["NOTION_WATCHED_DB_ID"] = watch_db_id
    logger.info("  ID: %s", watch_db_id)

    await client.close()

    print("\n" + "=" * 60)
    print("ВСЕ БАЗЫ ДАННЫХ СОЗДАНЫ!")
    print("=" * 60)
    print("\nСкопируй эти строки в .env:\n")
    for key, value in results.items():
        print(f"{key}={value}")
    print()


if __name__ == "__main__":
    asyncio.run(setup())
