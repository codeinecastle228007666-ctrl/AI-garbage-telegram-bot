import asyncio
import logging

from aiogram.types import BotCommand, BotCommandScopeDefault
from aiohttp import web

from ai_service import AIService
from bot import create_bot, create_dispatcher
from config import get_config
from handlers import get_router
from notion_client import NotionClient
from services import ContentService, NotificationService, ScheduleService, SubscriptionService, UserService, WatchedChannelService

logger = logging.getLogger(__name__)


async def scheduler_worker(notification_service, user_service, bot_id, interval_seconds=180):
    logger.info("Планировщик запущен (каждые %s сек.)", interval_seconds)
    while True:
        try:
            await notification_service.check_new_content(user_service, bot_id=bot_id)
        except Exception as e:
            logger.exception("Content check error: %s", e)
        await asyncio.sleep(interval_seconds)


async def scheduled_notif_worker(notification_service, bot_id, interval_seconds=3600):
    logger.info("Плановые уведомления (каждые %s сек.)", interval_seconds)
    while True:
        try:
            await notification_service.send_scheduled_notifications(bot_id=bot_id)
        except Exception as e:
            logger.exception("Scheduled notif error: %s", e)
        await asyncio.sleep(interval_seconds)


async def rss_watcher(watched_service, content_service, ai_service, admin_ids, bot, interval_seconds=300):
    if not watched_service:
        return
    logger.info("RSS-мониторинг запущен (каждые %s сек.)", interval_seconds)
    await asyncio.sleep(30)
    while True:
        try:
            channels = await watched_service.get_active()
            for ch in channels:
                posts = await watched_service.fetch_rss(ch["username"])
                for post in posts:
                    key = f"{ch['username']}:{post['date']}"
                    if key in watched_service._seen:
                        continue
                    watched_service._seen.add(key)
                    if ai_service and ai_service.enabled:
                        rel, data = await ai_service.is_relevant_post(post["title"], post["text"])
                        if not rel:
                            continue
                    existing = await content_service.search_items(post["title"][:30])
                    if existing:
                        continue
                    import secrets
                    pid = secrets.token_hex(6)
                    from handlers import _pending_items
                    ai_type = data.get("type", "") if ai_service and ai_service.enabled else ""
                    ai_tags = data.get("tags", []) if ai_service and ai_service.enabled else []
                    ai_name = data.get("name", post.get("title", ""))
                    _pending_items[pid] = {
                        "name": ai_name,
                        "type": ai_type,
                        "source": "Telegram-канал",
                        "url": post.get("url", ""),
                        "description": post["text"],
                        "tags": ai_tags,
                        "channel": ch["username"],
                    }
                    for admin_id in admin_ids:
                        from handlers import _stopped_users
                        if admin_id in _stopped_users:
                            continue
                        try:
                            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="\u2705 Подтвердить", callback_data=f"approve_{pid}"),
                                 InlineKeyboardButton(text="\u274c Отклонить", callback_data=f"reject_{pid}")]
                            ])
                            desc_snippet = (post["text"][:200] + "...") if len(post.get("text", "")) > 200 else post.get("text", "")
                            await bot.send_message(
                                admin_id,
                                f"\U0001f4e1 <b>Найдено AI:</b> {escape(ai_name)}\n"
                                f"\U0001f4cc {escape(ai_type)} \u2022 @{escape(ch['username'])}\n\n"
                                f"{escape(desc_snippet)}",
                                reply_markup=kb,
                            )
                        except Exception as e:
                            logger.warning("RSS notify admin %s: %s", admin_id, e)
                    await asyncio.sleep(2)
        except Exception as e:
            logger.exception("RSS watcher error: %s", e)
        await asyncio.sleep(interval_seconds)


def escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def set_commands(bot, admin_ids: list):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="search", description="Поиск в коллекции"),
        BotCommand(command="ai", description="Умный AI-поиск"),
        BotCommand(command="list", description="Последние записи"),
        BotCommand(command="add", description="Предложить запись"),
        BotCommand(command="parse", description="Распарсить ссылку"),
        BotCommand(command="notify", description="Управление подписками"),
        BotCommand(command="schedule", description="Настройка расписания"),
        BotCommand(command="stop", description="Отписаться от всего"),
    ]
    if admin_ids:
        commands.append(BotCommand(command="watch", description="(админ) Отслеживать канал"))
        commands.append(BotCommand(command="watched", description="(админ) Список каналов"))
        commands.append(BotCommand(command="scan", description="(админ) Сканировать каналы AI"))
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())


async def main():
    config = get_config()

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Запуск...")

    notion = NotionClient(config.NOTION_TOKEN)
    bot = create_bot(config)
    dp = create_dispatcher()
    await set_commands(bot, config.ADMIN_IDS)

    user_service = UserService(notion, config.NOTION_USERS_DB_ID)
    subscription_service = SubscriptionService(notion, config.NOTION_SUBSCRIPTIONS_DB_ID)
    schedule_service = ScheduleService(notion, config.NOTION_SCHEDULES_DB_ID)
    content_service = ContentService(notion, config.CONTENT_DATABASE_ID)
    notification_service = NotificationService(
        notion, config.NOTION_LOGS_DB_ID, bot,
        config.NOTION_SCHEDULES_DB_ID,
        content_db_id=config.CONTENT_DATABASE_ID or None,
    )
    await notification_service.load_notified_ids()

    ai_service = AIService(
        gemini_key=config.GEMINI_API_KEY or None,
        deepseek_key=config.DEEPSEEK_API_KEY or None,
        groq_key=config.GROQ_API_KEY or None,
        provider=config.AI_PROVIDER,
    )
    if not ai_service.enabled:
        ai_service = None

    watched_service = None
    if config.NOTION_WATCHED_DB_ID:
        watched_service = WatchedChannelService(notion, config.NOTION_WATCHED_DB_ID)

    router = get_router(
        user_service, subscription_service, schedule_service, content_service,
        config.ADMIN_IDS, ai_service=ai_service, watched_service=watched_service,
    )
    dp.include_router(router)

    asyncio.create_task(
        scheduler_worker(notification_service, user_service, bot.id, config.SCHEDULER_INTERVAL_SECONDS)
    )
    asyncio.create_task(
        scheduled_notif_worker(notification_service, bot.id, 3600)
    )
    asyncio.create_task(
        rss_watcher(watched_service, content_service, ai_service, config.ADMIN_IDS, bot, 300)
    )

    logger.info("Бот запущен.")

    async def health(request):
        return web.Response(text="OK")

    async def start_health():
        app = web.Application()
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8080)
        await site.start()
        while True:
            await asyncio.sleep(3600)

    asyncio.create_task(start_health())

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await notion.close()


if __name__ == "__main__":
    asyncio.run(main())
