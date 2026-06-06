import asyncio
import hashlib
import json
import logging
import secrets

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from models import NOTIFICATION_CHOICES, NotificationType
from services import ContentService, ScheduleService, SubscriptionService, UserService, WatchedChannelService

logger = logging.getLogger(__name__)

PAGE_SIZE = 5
ITEM_TYPES = ["Программа", "Утилита", "ИИ-агент", "Промпт", "Скрипт", "Шаблон"]
SOURCES = ["Telegram-канал", "GitHub", "Reddit", "Hacker News", "YouTube", "Блог/статья", "Другое"]

_cursor_store: dict[str, str] = {}
_user_data: dict[int, dict] = {}
_item_cache: dict[str, str] = {}  # short_id (8 chars) → full page_id
_pending_items: dict[str, dict] = {}  # key → pending item for approval
_stopped_users: set[int] = set()  # users who stopped RSS notifications


def escape(text: str) -> str:
    """Экранирование HTML-символов для отправки в Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_keyboard(*buttons: tuple[str, str]) -> InlineKeyboardMarkup:
    """Создать клавиатуру из кортежей (текст, callback_data)."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=b[0], callback_data=b[1])] for b in buttons])


def get_router(
    user_service: UserService,
    subscription_service: SubscriptionService,
    schedule_service: ScheduleService,
    content_service: ContentService,
    admin_ids: list[int],
    ai_service=None,
    watched_service: WatchedChannelService | None = None,
) -> Router:
    router = Router()

    def is_admin(user_id: int) -> bool:
        return user_id in admin_ids

    # ─── START ───

    @router.message(CommandStart())
    async def cmd_start(message: Message):
        user = message.from_user
        await user_service.register_user(user.id, user.username, user.first_name, user.last_name)
        _stopped_users.discard(user.id)
        kb = make_keyboard(
            ("\U0001f50d Поиск", "menu_search"),
            ("\U0001f4dd Список", "menu_list"),
            ("\U0001f4e4 Уведомления", "menu_notify"),
            ("\U0001f4c5 Расписание", "menu_schedule"),
        )
        if is_admin(user.id):
            kb.inline_keyboard.append([InlineKeyboardButton(text="\u2699 Админка", callback_data="menu_admin")])
        await message.answer(
            f"\U0001f44b Привет, {escape(user.first_name or 'пользователь')}!\n\n"
            "Я — бот для коллекции программ и утилит. Мои возможности:\n\n"
            "\U0001f50d /search &lt;текст&gt; — поиск по коллекции\n"
            "\U0001f4dd /list — список последних записей\n"
            "\U0001f4e4 /add — предложить новую запись\n"
            "\U0001f310 /parse &lt;ссылка&gt; — распарсить страницу\n"
            "\U0001f514 /notify — управление подписками\n"
            "\U0001f4c5 /schedule — настройка расписания\n"
            "\U0001f6d1 /stop — отписаться от всего",
            reply_markup=kb,
        )

    # ─── HELP ───

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        text = (
            "\U0001f4da <b>Справка</b>\n\n"
            "\U0001f44b /start — главное меню\n"
            "\U0001f50d /search &lt;текст&gt; — поиск по названию\n"
            "\U0001f4dd /list — последние записи\n"
            "\U0001f4e4 /add — предложить новую программу/утилиту\n"
            "\U0001f310 /parse &lt;ссылка&gt; — распарсить и предложить\n"
            "\U0001f514 /notify — управление подписками\n"
            "\U0001f4c5 /schedule — расписание уведомлений\n"
            "  Формат: /schedule &lt;тип&gt; &lt;инт&gt; &lt;с&gt; &lt;до&gt;\n"
            "  Пример: /schedule daily_digest 60 09:00 21:00\n"
            "\U0001f6d1 /stop — отписаться от всего\n\n"
            "<b>Типы уведомлений:</b>\n"
        )
        for k, v in NOTIFICATION_CHOICES.items():
            text += f"  \u2022 <code>{k.value}</code> — {v}\n"
        await message.answer(text)

    # ─── MENU CALLBACKS ───

    @router.callback_query(F.data == "menu_search")
    async def cb_menu_search(cb: CallbackQuery):
        await cb.message.answer("Введи /search &lt;текст&gt; для поиска по коллекции.")

    @router.callback_query(F.data == "menu_list")
    async def cb_menu_list(cb: CallbackQuery):
        await cmd_list(cb.message)

    @router.callback_query(F.data == "menu_notify")
    async def cb_menu_notify(cb: CallbackQuery):
        await cmd_notify(cb.message)

    @router.callback_query(F.data == "menu_schedule")
    async def cb_menu_schedule(cb: CallbackQuery):
        await cmd_schedule(cb.message)

    @router.callback_query(F.data == "menu_admin")
    async def cb_menu_admin(cb: CallbackQuery):
        if not is_admin(cb.from_user.id):
            await cb.answer("Нет доступа", show_alert=True)
            return
        kb = make_keyboard(
            ("\U0001f4e5 На модерации", "admin_pending"),
            ("\U0001f4cc Главное меню", "back_start"),
        )
        await cb.message.answer("\u2699 <b>Админ-панель</b>", reply_markup=kb)

    @router.callback_query(F.data == "back_start")
    async def cb_back_start(cb: CallbackQuery):
        await cmd_start(cb.message)

    # ─── SEARCH ───

    @router.message(Command("search"))
    async def cmd_search(message: Message):
        query = message.text.removeprefix("/search").strip()
        if not query:
            await message.answer("Использование: /search &lt;текст&gt;")
            return
        items = await content_service.search_items(query)
        if not items:
            await message.answer(f"Ничего не найдено по запросу «{escape(query)}».")
            return
        await _send_items_list(message, items, f"Результаты поиска по «{escape(query)}»:")

    @router.message(Command("ai"))
    async def cmd_ai_search(message: Message):
        query = message.text.removeprefix("/ai").strip()
        if not query:
            await message.answer("Использование: /ai &lt;что нужно&gt;\nПример: /ai программу для очистки системы")
            return
        if not ai_service or not ai_service.enabled:
            await message.answer("AI не настроен. Добавь GEMINI_API_KEY в .env")
            return
        if not watched_service:
            await message.answer("Мониторинг каналов не настроен. Добавь /watch @канал")
            return
        status = await message.answer("\U0001f504 Сканирую каналы по запросу...")
        channels = await watched_service.get_active()
        if not channels:
            await status.edit_text("Нет отслеживаемых каналов. /watch @канал — добавить.")
            return

        # Собираем все посты из истории каналов (не только новые)
        all_posts = []
        for ch in channels:
            posts = await watched_service.fetch_rss(ch["username"], max_pages=15)
            for p in posts:
                all_posts.append({**p, "channel": ch["username"]})

        if not all_posts:
            await status.edit_text("Нет постов в каналах.")
            return

        await status.edit_text(f"\U0001f504 AI анализирует {len(all_posts)} постов...")

        # Батевая проверка: отправляем по 15 постов за запрос
        found = 0
        batch_size = 15
        for i in range(0, len(all_posts), batch_size):
            batch = all_posts[i:i + batch_size]
            prompt_lines = [
                f"Запрос пользователя: {query}",
                "",
                "Ниже список постов из Telegram-каналов. Найди среди них те, что описывают ПОЛЕЗНЫЕ программы, утилиты, библиотеки, инструменты, сервисы, промпты или скрипты.",
                "",
                "НЕ считаются: игры (видеоигры, анонсы игр, трейлеры), новости про игры, фильмы, сериалы, музыка, мемы, мессенджеры, соцсети, общие новости, политика, крипта.",
                "Считаются: софт, девтулы, AI-инструменты, промпты, CLI, библиотеки, фреймворки, плагины, расширения.",
                "",
                "Для каждого подходящего поста верни: номер, короткое название (name, 2-5 слов), тип (Программа/Утилита/ИИ-агент/Промпт/Скрипт/Шаблон), теги, причину.",
                "Верни ТОЛЬКО JSON-массив: [{\"idx\": 0, \"match\": true, \"name\": \"...\", \"type\": \"...\", \"tags\": [...], \"reason\": \"...\"}, ...]",
                "Для неподходящих не включай в результат.",
                "---",
            ]
            for j, post in enumerate(batch):
                prompt_lines.append(f"\n[{j}] Канал: @{post['channel']}")
                prompt_lines.append(f"    Заголовок: {post['title']}")
                prompt_lines.append(f"    Текст: {post['text'][:1000]}")

            data = await ai_service._query("\n".join(prompt_lines))
            if not data:
                continue
            try:
                cleaned = data.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                results = json.loads(cleaned)
                if not isinstance(results, list):
                    results = [results]
            except Exception:
                continue

            for r in results:
                if not r.get("match"):
                    continue
                post = batch[r["idx"]]
                existing = await content_service.search_items(post["title"][:40])
                if existing:
                    continue

                pid = secrets.token_hex(6)
                ai_name = r.get("name", post.get("title", ""))
                _pending_items[pid] = {
                    "name": ai_name,
                    "type": r.get("type", ""),
                    "source": "Telegram-канал",
                    "url": post.get("url", ""),
                    "description": post["text"],
                    "tags": r.get("tags", []),
                    "channel": post["channel"],
                }
                kb = make_keyboard(
                    ("\u2705 Подтвердить", f"approve_{pid}"),
                    ("\u274c Отклонить", f"reject_{pid}"),
                )
                desc_snippet = (post["text"][:200] + "...") if len(post.get("text", "")) > 200 else post.get("text", "")
                await message.answer(
                    f"\U0001f916 <b>По запросу найдено:</b>\n"
                    f"{escape(ai_name)}\n"
                    f"\U0001f4cc {escape(r.get('type', '?'))}  \u2022 @{escape(post['channel'])}\n\n"
                    f"{escape(desc_snippet)}",
                    reply_markup=kb,
                )
                found += 1
                await asyncio.sleep(1)

        await status.edit_text(f"\U00002705 Поиск завершён. Найдено подходящих: {found}")

    # ─── LIST ───

    @router.message(Command("list"))
    async def cmd_list(message: Message, page_items=None, page_msg=None, cursor=None):
        items, next_cursor, has_more = await content_service.list_items(PAGE_SIZE, cursor)
        if not items:
            text = "Коллекция пуста."
            if page_msg:
                await page_msg.edit_text(text)
            else:
                await message.answer(text)
            return
        await _send_items_list(message, items, "\U0001f4dd <b>Последние записи</b>", next_cursor if has_more else None, page_msg)

    async def _send_items_list(dst, items: list, header: str, next_cursor=None, page_msg=None):
        text = header + "\n\n"
        for i, item in enumerate(items, 1):
            sid = hashlib.md5(item['id'].encode()).hexdigest()[:8]
            _item_cache[sid] = item['id']
            text += f"<b>{i}. {escape(item['name'] or 'Без названия')}</b>\n"
            if item["type"]:
                text += f"  \U0001f4cc {escape(item['type'])}"
                if item["source"]:
                    text += f"  \u2022 {escape(item['source'])}"
                text += "\n"
            if item["tags"]:
                text += f"  \U0001f3f7 {', '.join(escape(t) for t in item['tags'][:3])}\n"
            text += f"  \U0001f517 /item_{sid}\n\n"
        kb_list = []
        if next_cursor:
            key = secrets.token_hex(4)
            _cursor_store[key] = next_cursor
            kb_list.append([InlineKeyboardButton(text="\u25b6 Далее", callback_data=f"n_{key}")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_list) if kb_list else None
        if page_msg:
            await page_msg.edit_text(text, reply_markup=kb)
        else:
            await dst.answer(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("n_"))
    async def cb_list_page(cb: CallbackQuery):
        key = cb.data.removeprefix("n_")
        cursor = _cursor_store.pop(key, None)
        if not cursor:
            await cb.answer("Список устарел, начни заново: /list", show_alert=True)
            return
        await cmd_list(cb.message, page_msg=cb.message, cursor=cursor)

    # ─── ITEM DETAIL ───

    @router.message(lambda m: m.text and m.text.startswith("/item_"))
    async def cmd_item(message: Message):
        raw_id = message.text.removeprefix("/item_").strip()
        try:
            page_id = _item_cache.get(raw_id)
            if page_id:
                item = await content_service.get_item(page_id)
            elif len(raw_id) == 36 and raw_id.count("-") == 4:
                item = await content_service.get_item(raw_id)
            else:
                pages = await content_service.client.query_database(
                    content_service.db_id, page_size=100,
                )
                item = None
                for p in pages:
                    pid = content_service.client.page_id(p)
                    if pid.startswith(raw_id) or pid.replace("-", "").startswith(raw_id):
                        _item_cache[raw_id] = pid
                        item = content_service._parse_item(p)
                        break
                if not item:
                    await message.answer("Запись не найдена.")
                    return
        except Exception:
            await message.answer("Ошибка загрузки записи.")
            return
        await _send_item_detail(message, item)

    async def _send_item_detail(dst, item: dict):
        text = (
            f"\U0001f4e6 <b>{escape(item['name'] or 'Без названия')}</b>\n\n"
            f"\U0001f4cc Тип: <b>{escape(item['type'] or '?')}</b>\n"
            f"\U0001f4e2 Источник: {escape(item['source'] or '?')}\n"
        )
        if item["url"]:
            text += f"\U0001f517 <a href=\"{item['url']}\">Открыть ссылку</a>\n"
        if item["tags"]:
            text += f"\U0001f3f7 Теги: {', '.join(escape(t) for t in item['tags'])}\n"
        if item["status"]:
            emoji = {"Проверено": "\u2705", "Новое": "\U0001f195", "Не подходит": "\u274c", "В использовании": "\U0001f4a1", "Тестирую": "\u2699\ufe0f"}
            text += f"{emoji.get(item['status'], '\U0001f4ad')} Статус: {escape(item['status'])}\n"
        if item["description"]:
            text += f"\n{escape(item['description'])}"
        if item["notes"]:
            text += f"\n\n\U0001f4dd <i>{escape(item['notes'])}</i>"
        await dst.answer(text)

    # ─── ADD (inline flow) ───

    user_data: dict[int, dict] = {}

    @router.message(Command("add"))
    async def cmd_add(message: Message):
        uid = message.from_user.id
        user_data[uid] = {}
        kb = make_keyboard(*[(t, f"add_type_{t}") for t in ITEM_TYPES])
        await message.answer("Выбери тип новой записи:", reply_markup=kb)

    @router.callback_query(F.data.startswith("add_type_"))
    async def cb_add_type(cb: CallbackQuery):
        uid = cb.from_user.id
        user_data.setdefault(uid, {})["type"] = cb.data.removeprefix("add_type_")
        kb = make_keyboard(*[(s, f"add_src_{s}") for s in SOURCES])
        await cb.message.edit_text(f"Тип: <b>{escape(user_data[uid]['type'])}</b>\n\nТеперь выбери источник:", reply_markup=kb)

    @router.callback_query(F.data.startswith("add_src_"))
    async def cb_add_source(cb: CallbackQuery):
        uid = cb.from_user.id
        user_data.setdefault(uid, {})["source"] = cb.data.removeprefix("add_src_")
        await cb.message.edit_text(
            f"Тип: <b>{escape(user_data[uid]['type'])}</b>\n"
            f"Источник: <b>{escape(user_data[uid]['source'])}</b>\n\n"
            "Отправь мне название записи:"
        )
        user_data[uid]["step"] = "name"

    @router.message(lambda m: m.from_user.id in user_data and user_data[m.from_user.id].get("step") == "name")
    async def add_step_name(message: Message):
        uid = message.from_user.id
        user_data[uid]["name"] = message.text.strip()
        user_data[uid]["step"] = "url"
        await message.answer("Отправь ссылку (или отправь «-» если нет):")

    @router.message(lambda m: m.from_user.id in user_data and user_data[m.from_user.id].get("step") == "url")
    async def add_step_url(message: Message):
        uid = message.from_user.id
        url = message.text.strip()
        user_data[uid]["url"] = url if url != "-" else ""
        user_data[uid]["step"] = "desc"
        await message.answer("Отправь описание (или «-»):")

    @router.message(lambda m: m.from_user.id in user_data and user_data[m.from_user.id].get("step") == "desc")
    async def add_step_desc(message: Message):
        uid = message.from_user.id
        desc = message.text.strip()
        user_data[uid]["description"] = desc if desc != "-" else ""
        user_data[uid]["step"] = "tags"
        await message.answer("Отправь теги через запятую (или «-»):\nПример: python, ai, telegram")

    @router.message(lambda m: m.from_user.id in user_data and user_data[m.from_user.id].get("step") == "tags")
    async def add_step_tags(message: Message):
        uid = message.from_user.id
        raw = message.text.strip()
        tags = [t.strip() for t in raw.split(",") if t.strip()] if raw != "-" else []
        user_data[uid]["tags"] = tags
        d = user_data[uid]
        try:
            pid = await content_service.add_item(
                name=d["name"],
                item_type=d["type"],
                source=d["source"],
                url=d["url"],
                description=d["description"],
                tags=d["tags"],
            )
            await message.answer(
                f"\U00002705 Запись добавлена на модерацию!\n\n"
                f"<b>{escape(d['name'])}</b>\n"
                f"Тип: {escape(d['type'])}\n"
                f"Источник: {escape(d['source'])}",
            )
            if is_admin(uid):
                kb = make_keyboard(
                    ("\u2705 Подтвердить", f"approve_{pid}"),
                    ("\u274c Отклонить", f"reject_{pid}"),
                )
                await message.answer("Ты админ — подтвердить сразу?", reply_markup=kb)
        except Exception as e:
            await message.answer(f"\u274c Ошибка: {e}")
        user_data.pop(uid, None)

    # ─── PARSE ───

    @router.message(Command("parse"))
    async def cmd_parse(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("Только для админа. /add — чтобы предложить запись.")
            return
        url = message.text.removeprefix("/parse").strip()
        if not url or not url.startswith("http"):
            await message.answer("Отправь ссылку: /parse &lt;url&gt;")
            return
        status_msg = await message.answer("\U0001f504 Парсинг...")
        try:
            data = await ContentService.parse_url(url)
            uid = message.from_user.id

            # AI-классификация
            ai_type, ai_source, ai_tags = None, None, []
            if ai_service and ai_service.enabled:
                ai_result = await ai_service.classify(data.get("title", ""), data.get("description", ""), url)
                ai_type = ai_result.get("type")
                ai_source = ai_result.get("source")
                ai_tags = ai_result.get("tags", [])
                if not data.get("description") and ai_result.get("description"):
                    data["description"] = ai_result["description"]

            title = data.get("title") or "Без названия"
            desc = data.get("description", "")

            uid = message.from_user.id
            user_data[uid] = {
                "name": title,
                "url": url,
                "description": desc,
                "type": ai_type or "",
                "source": ai_source or "",
                "tags": ai_tags,
                "step": "type" if not ai_type else ("source" if not ai_source else "done"),
            }

            if ai_type and ai_source:
                await _finish_parse(uid, cb=None, msg=status_msg)
                return

            text_parts = [f"\U0001f310 <b>{escape(title)}</b>"]
            if ai_type:
                text_parts.append(f"\U0001f4cc Тип: <b>{escape(ai_type)}</b> (определён AI)")
            if ai_source:
                text_parts.append(f"\U0001f4e2 Источник: <b>{escape(ai_source)}</b> (определён AI)")
            if desc:
                text_parts.append(f"\n{escape(desc[:200])}")

            if not ai_type:
                text_parts.append("\n\nВыбери тип:")
                kb = make_keyboard(*[(t, f"parse_type_{t}") for t in ITEM_TYPES])
            else:
                text_parts.append("\n\nВыбери источник:")
                kb = make_keyboard(*[(s, f"parse_src_{s}") for s in SOURCES])

            await status_msg.edit_text("\n".join(text_parts), reply_markup=kb)
        except Exception as e:
            logger.exception("Parse error")
            await status_msg.edit_text(f"\u274c Ошибка парсинга: {e}")

    @router.callback_query(F.data.startswith("parse_type_"))
    async def cb_parse_type(cb: CallbackQuery):
        uid = cb.from_user.id
        user_data.setdefault(uid, {})["type"] = cb.data.removeprefix("parse_type_")
        step = user_data[uid].get("step", "")
        d = user_data[uid]
        if d.get("source"):
            await _finish_parse(uid, cb=cb)
            return
        kb = make_keyboard(*[(s, f"parse_src_{s}") for s in SOURCES])
        await cb.message.edit_text(
            f"Тип: <b>{escape(d['type'])}</b>\n\nИсточник:", reply_markup=kb,
        )

    @router.callback_query(F.data.startswith("parse_src_"))
    async def cb_parse_src(cb: CallbackQuery):
        uid = cb.from_user.id
        d = user_data.setdefault(uid, {})
        d["source"] = cb.data.removeprefix("parse_src_")
        if not d.get("type"):
            await cb.message.edit_text(f"Источник: <b>{escape(d['source'])}</b>\n\nТеперь выбери тип:")
            kb = make_keyboard(*[(t, f"parse_type_{t}") for t in ITEM_TYPES])
            await cb.message.edit_reply_markup(reply_markup=kb)
            return
        await _finish_parse(uid, cb=cb)

    async def _finish_parse(uid: int, cb: CallbackQuery | None = None, msg: Message | None = None):
        d = user_data.get(uid, {})
        if not d.get("name"):
            return
        tags = d.get("tags", [])
        if not tags:
            name_words = set(d.get("name", "").lower().split())
            tag_map = {"python": "python", "javascript": "javascript", "ai": "ai",
                        "machine learning": "machine-learning", "telegram": "telegram",
                        "docker": "docker", "api": "api", "cli": "cli", "web": "web",
                        "automation": "automation", "github": "automation", "bot": "telegram"}
            for word, tag in tag_map.items():
                if word in name_words:
                    tags.append(tag)
            d["tags"] = list(set(tags))
        pid = await content_service.add_item(
            name=d.get("name", "Без названия"),
            item_type=d.get("type", ""),
            source=d.get("source", ""),
            url=d.get("url", ""),
            description=d.get("description", ""),
            tags=tags,
        )
        tag_str = ", ".join(escape(t) for t in tags) if tags else "\u2014"
        msg_text = (
            f"\U00002705 Добавлено!\n\n"
            f"<b>{escape(d.get('name', ''))}</b>\n"
            f"\U0001f4cc Тип: {escape(d['type'])}\n"
            f"\U0001f4e2 Источник: {escape(d['source'])}\n"
            f"\U0001f3f7 Теги: {tag_str}"
        )
        if is_admin(uid):
            kb = make_keyboard(
                ("\u2705 Подтвердить", f"approve_{pid}"),
                ("\u274c Отклонить", f"reject_{pid}"),
            )
            if cb:
                await cb.message.edit_text(msg_text, reply_markup=kb)
            elif msg:
                await msg.edit_text(msg_text, reply_markup=kb)
        else:
            msg_text += "\n\nОтправлено на модерацию."
            if cb:
                await cb.message.edit_text(msg_text)
            elif msg:
                await msg.edit_text(msg_text)
        user_data.pop(uid, None)

    # ─── ADMIN: APPROVE / REJECT ───

    @router.callback_query(F.data.startswith("approve_"))
    async def cb_approve(cb: CallbackQuery):
        if not is_admin(cb.from_user.id):
            await cb.answer("Нет доступа", show_alert=True)
            return
        key = cb.data.removeprefix("approve_")
        if key in _pending_items:
            item = _pending_items.pop(key)
            pid = await content_service.add_item(
                name=item["name"], item_type=item["type"],
                source=item["source"], url=item["url"],
                description=item["description"], tags=item["tags"],
            )
            await content_service.approve_item(pid, "Проверено")
            await cb.answer("\u2705 Добавлено и подтверждено!")
            await cb.message.edit_text(cb.message.html_text + "\n\n\u2705 <b>Подтверждено</b>")
        else:
            await content_service.approve_item(key, "Проверено")
            await cb.answer("\u2705 Подтверждено!")
            await cb.message.edit_text(cb.message.html_text + "\n\n\u2705 <b>Подтверждено</b>")

    @router.callback_query(F.data.startswith("reject_"))
    async def cb_reject(cb: CallbackQuery):
        if not is_admin(cb.from_user.id):
            await cb.answer("Нет доступа", show_alert=True)
            return
        key = cb.data.removeprefix("reject_")
        if key in _pending_items:
            _pending_items.pop(key)
            await cb.answer("\u274c Отклонено")
            await cb.message.edit_text(cb.message.html_text + "\n\n\u274c <b>Отклонено</b>")
        else:
            await content_service.approve_item(key, "Не подходит")
            await cb.answer("\u274c Отклонено")
            await cb.message.edit_text(cb.message.html_text + "\n\n\u274c <b>Отклонено</b>")

    @router.callback_query(F.data == "admin_pending")
    async def cb_admin_pending(cb: CallbackQuery):
        if not is_admin(cb.from_user.id):
            await cb.answer("Нет доступа", show_alert=True)
            return
        items = await content_service.get_pending()
        if not items:
            await cb.message.edit_text("Нет записей на модерации.")
            return
        for item in items[:5]:
            text = (
                f"<b>{escape(item['name'] or 'Без названия')}</b>\n"
                f"\U0001f4cc {escape(item['type'] or '?')}  \u2022 {escape(item['source'] or '?')}"
            )
            if item["tags"]:
                text += f"\n\U0001f3f7 {', '.join(escape(t) for t in item['tags'])}"
            if item["url"]:
                text += f'\n\U0001f517 <a href="{item["url"]}">Открыть</a>'
            kb = make_keyboard(
                ("\u2705 Подтвердить", f"approve_{item['id']}"),
                ("\u274c Отклонить", f"reject_{item['id']}"),
            )
            await cb.message.answer(text, reply_markup=kb)
        await cb.message.delete()

    # ─── NOTIFY ───

    @router.message(Command("notify"))
    async def cmd_notify(message: Message):
        tid = message.from_user.id
        enabled = await subscription_service.get_enabled_types(tid)
        buttons = []
        for nt, label in NOTIFICATION_CHOICES.items():
            status = "\u2705" if nt in enabled else "\u2b1c"
            buttons.append([InlineKeyboardButton(text=f"{status} {label}", callback_data=f"toggle:{nt.value}")])
        await message.answer("\U0001f514 <b>Управление подписками</b>\n\nНажми, чтобы включить/выключить:",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

    @router.callback_query(F.data.startswith("toggle:"))
    async def callback_toggle(cb: CallbackQuery):
        ntype_value = cb.data.split(":", 1)[1]
        try:
            ntype = NotificationType(ntype_value)
        except ValueError:
            await cb.answer("Неизвестный тип", show_alert=True)
            return
        _, msg = await subscription_service.toggle_subscription(cb.from_user.id, ntype)
        await cb.answer(msg, show_alert=False)
        await cmd_notify(cb.message)

    # ─── SCHEDULE ───

    @router.message(Command("schedule"))
    async def cmd_schedule(message: Message):
        tid = message.from_user.id
        args = message.text.strip().split(maxsplit=4)
        if len(args) < 5:
            current = await schedule_service.get_user_schedules(tid)
            if not current:
                text = (
                    "\U0001f4c5 <b>Настройка расписания</b>\n\n"
                    "Формат:\n"
                    "<code>/schedule &lt;тип&gt; &lt;интервал_мин&gt; &lt;с&gt; &lt;до&gt;</code>\n\n"
                    "Пример:\n"
                    "<code>/schedule daily_digest 60 09:00 21:00</code>\n\n"
                    "Типы: " + ", ".join(f"<code>{t.value}</code>" for t in NotificationType)
                )
            else:
                text = "\U0001f4c5 <b>Ваши расписания</b>\n\n"
                for s in current:
                    label = NOTIFICATION_CHOICES.get(s["notification_type"], s["notification_type"].value)
                    text += f"  \u2022 {label}: каждые {s['interval_minutes']} мин., {s['time_from']}-{s['time_to']}\n"
                text += '\nФормат: <code>/schedule &lt;тип&gt; &lt;интервал&gt; &lt;с&gt; &lt;до&gt;</code>'
            await message.answer(text)
            return
        try:
            ntype = NotificationType(args[1])
            interval = int(args[2])
        except (ValueError, KeyError):
            await message.answer(f"Неверный формат. Типы: {', '.join(t.value for t in NotificationType)}")
            return
        msg = await schedule_service.set_schedule(tid, ntype, interval, args[3], args[4])
        await message.answer(msg)

    # ─── STOP ───

    @router.message(Command("stop"))
    async def cmd_stop(message: Message):
        uid = message.from_user.id
        await subscription_service.unsubscribe_all(uid)
        _stopped_users.add(uid)
        await message.answer("\U0001f6d1 Вы отписаны от всего, RSS-мониторинг отключён.\n/start — чтобы включить снова")

    # ─── WATCH / MONITOR ───

    @router.message(Command("watch"))
    async def cmd_watch(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("Только для админа.")
            return
        if not watched_service:
            await message.answer("Сервис мониторинга не настроен (нет БД watched).")
            return
        username = message.text.removeprefix("/watch").strip()
        if not username:
            await message.answer("Укажи имя канала: /watch &lt;username&gt;")
            return
        msg = await watched_service.add_channel(username, message.from_user.id)
        await message.answer(msg)

    @router.message(Command("unwatch"))
    async def cmd_unwatch(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("Только для админа.")
            return
        if not watched_service:
            await message.answer("Сервис мониторинга не настроен.")
            return
        username = message.text.removeprefix("/unwatch").strip()
        if not username:
            await message.answer("Укажи имя канала: /unwatch &lt;username&gt;")
            return
        msg = await watched_service.remove_channel(username)
        await message.answer(msg)

    @router.message(Command("watched"))
    async def cmd_watched(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("Только для админа.")
            return
        if not watched_service:
            await message.answer("Сервис мониторинга не настроен.")
            return
        channels = await watched_service.get_active()
        if not channels:
            await message.answer("Нет отслеживаемых каналов.\n/watch &lt;username&gt; — добавить.")
            return
        text = "\U0001f4fa <b>Отслеживаемые каналы:</b>\n\n"
        for ch in channels:
            text += f"  \u2022 @{escape(ch['username'])}\n"
        await message.answer(text)

    @router.message(Command("scan"))
    async def cmd_scan(message: Message):
        if not is_admin(message.from_user.id):
            await message.answer("Только для админа.")
            return
        if not watched_service:
            await message.answer("Сервис мониторинга не настроен.")
            return
        if not ai_service or not ai_service.enabled:
            await message.answer("AI не настроен. Добавь GEMINI_API_KEY в .env")
            return
        status = await message.answer("\U0001f504 Сканирование каналов...")
        channels = await watched_service.get_active()
        if not channels:
            await status.edit_text("Нет отслеживаемых каналов.")
            return
        found = 0
        for ch in channels:
            posts = await watched_service.fetch_rss(ch["username"], max_pages=5)
            for post in posts:
                key = f"{ch['username']}:{post['date']}"
                if key in watched_service._seen:
                    continue
                watched_service._seen.add(key)
                rel, data = await ai_service.is_relevant_post(post["title"], post["text"])
                if not rel:
                    continue
                existing = await content_service.search_items(post["title"][:30])
                if existing:
                    continue
                pid = secrets.token_hex(6)
                ai_name = data.get("name", post.get("title", ""))
                _pending_items[pid] = {
                    "name": ai_name,
                    "type": data.get("type", ""),
                    "source": "Telegram-канал",
                    "url": post.get("url", ""),
                    "description": post["text"],
                    "tags": data.get("tags", []),
                    "channel": ch["username"],
                }
                kb = make_keyboard(
                    ("\u2705 Подтвердить", f"approve_{pid}"),
                    ("\u274c Отклонить", f"reject_{pid}"),
                )
                desc_snippet = (post["text"][:200] + "...") if len(post.get("text", "")) > 200 else post.get("text", "")
                await message.answer(
                    f"\U0001f4e1 <b>Найдено AI:</b> {escape(ai_name)}\n"
                    f"\U0001f4cc {escape(data.get('type', '?'))}  \u2022 @{escape(ch['username'])}\n\n"
                    f"{escape(desc_snippet)}",
                    reply_markup=kb,
                )
                found += 1
                await asyncio.sleep(3)
        await status.edit_text(f"\U00002705 Сканирование завершено. Найдено: {found}")

    return router
