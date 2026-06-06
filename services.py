import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from models import NOTIFICATION_CHOICES, NotificationType
from notion_client import NotionClient


def _clean_html(raw: str) -> str:
    """Удалить HTML-теги из строки."""
    return re.sub(r'<[^>]+>', '', raw).strip()

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, client: NotionClient, users_db_id: str):
        self.client = client
        self.db_id = users_db_id

    async def register_user(self, telegram_id: int, username=None, first_name=None, last_name=None):
        existing = await self.find_by_telegram_id(telegram_id)
        now = datetime.now()
        if existing:
            props = {"Updated At": self.client.make_date(now), "Is Active": self.client.make_checkbox(True)}
            if username:
                props["Username"] = self.client.make_rich_text(username)
            if first_name:
                props["First Name"] = self.client.make_rich_text(first_name)
            if last_name:
                props["Last Name"] = self.client.make_rich_text(last_name)
            await self.client.update_page(self.client.page_id(existing), props)
            return
        name = username or first_name or str(telegram_id)
        await self.client.create_page(self.db_id, {
            "Name": self.client.make_title(name),
            "Telegram ID": self.client.make_number(telegram_id),
            "Username": self.client.make_rich_text(username or ""),
            "First Name": self.client.make_rich_text(first_name or ""),
            "Last Name": self.client.make_rich_text(last_name or ""),
            "Is Active": self.client.make_checkbox(True),
            "Created At": self.client.make_date(now),
            "Updated At": self.client.make_date(now),
        })

    async def find_by_telegram_id(self, telegram_id: int):
        r = await self.client.query_database(self.db_id, filter_={"property": "Telegram ID", "number": {"equals": telegram_id}})
        return r[0] if r else None

    async def get_all_active_users(self):
        r = await self.client.query_database(self.db_id, filter_={"property": "Is Active", "checkbox": {"equals": True}})
        users = []
        for page in r:
            tid = self.client.prop_number(page["properties"], "Telegram ID")
            if tid:
                users.append(int(tid))
        return users


class SubscriptionService:
    def __init__(self, client: NotionClient, subs_db_id: str):
        self.client = client
        self.db_id = subs_db_id

    async def get_enabled_types(self, telegram_id: int):
        r = await self.client.query_database(self.db_id, filter_={"and": [
            {"property": "Telegram ID", "number": {"equals": telegram_id}},
            {"property": "Is Enabled", "checkbox": {"equals": True}},
        ]})
        types = set()
        for page in r:
            name = self.client.prop_select(page["properties"], "Notification Type")
            if name:
                try:
                    types.add(NotificationType(name))
                except ValueError:
                    pass
        return types

    async def toggle_subscription(self, telegram_id: int, notification_type: NotificationType):
        r = await self.client.query_database(self.db_id, filter_={"and": [
            {"property": "Telegram ID", "number": {"equals": telegram_id}},
            {"property": "Notification Type", "select": {"equals": notification_type.value}},
        ]})
        label = NOTIFICATION_CHOICES[notification_type]
        if r:
            page = r[0]
            current = self.client.prop_checkbox(page["properties"], "Is Enabled")
            new_state = not current
            await self.client.update_page(self.client.page_id(page), {"Is Enabled": self.client.make_checkbox(new_state)})
        else:
            new_state = True
            await self.client.create_page(self.db_id, {
                "Name": self.client.make_title(f"{telegram_id} - {notification_type.value}"),
                "Telegram ID": self.client.make_number(telegram_id),
                "Notification Type": self.client.make_select(notification_type.value),
                "Is Enabled": self.client.make_checkbox(True),
                "Created At": self.client.make_date(),
            })
        return new_state, f"{'Включена' if new_state else 'Выключена'} подписка на «{label}»"

    async def unsubscribe_all(self, telegram_id: int):
        r = await self.client.query_database(self.db_id, filter_={"and": [
            {"property": "Telegram ID", "number": {"equals": telegram_id}},
            {"property": "Is Enabled", "checkbox": {"equals": True}},
        ]})
        for page in r:
            await self.client.update_page(self.client.page_id(page), {"Is Enabled": self.client.make_checkbox(False)})
        return True


class ScheduleService:
    def __init__(self, client: NotionClient, sched_db_id: str):
        self.client = client
        self.db_id = sched_db_id

    async def get_user_schedules(self, telegram_id: int):
        r = await self.client.query_database(self.db_id, filter_={"and": [
            {"property": "Telegram ID", "number": {"equals": telegram_id}},
            {"property": "Is Active", "checkbox": {"equals": True}},
        ]})
        out = []
        for page in r:
            props = page["properties"]
            ntype_name = self.client.prop_select(props, "Notification Type")
            try:
                ntype = NotificationType(ntype_name) if ntype_name else None
            except ValueError:
                continue
            out.append({
                "id": self.client.page_id(page),
                "notification_type": ntype,
                "interval_minutes": self.client.prop_number(props, "Interval Minutes") or 60,
                "time_from": self.client.prop_rich_text(props, "Time From") or "09:00",
                "time_to": self.client.prop_rich_text(props, "Time To") or "21:00",
            })
        return out

    async def set_schedule(self, telegram_id: int, notification_type: NotificationType,
                           interval_minutes=60, time_from="09:00", time_to="21:00"):
        if interval_minutes < 1 or interval_minutes > 1440:
            return "Интервал должен быть от 1 до 1440 минут."
        if not self._validate_time(time_from):
            return "Неверный формат времени. Используйте ЧЧ:ММ."
        if not self._validate_time(time_to):
            return "Неверный формат времени. Используйте ЧЧ:ММ."
        r = await self.client.query_database(self.db_id, filter_={"and": [
            {"property": "Telegram ID", "number": {"equals": telegram_id}},
            {"property": "Notification Type", "select": {"equals": notification_type.value}},
        ]})
        if r:
            await self.client.update_page(self.client.page_id(r[0]), {
                "Interval Minutes": self.client.make_number(interval_minutes),
                "Time From": self.client.make_rich_text(time_from),
                "Time To": self.client.make_rich_text(time_to),
                "Is Active": self.client.make_checkbox(True),
            })
        else:
            await self.client.create_page(self.db_id, {
                "Name": self.client.make_title(f"{telegram_id} - {notification_type.value}"),
                "Telegram ID": self.client.make_number(telegram_id),
                "Notification Type": self.client.make_select(notification_type.value),
                "Interval Minutes": self.client.make_number(interval_minutes),
                "Time From": self.client.make_rich_text(time_from),
                "Time To": self.client.make_rich_text(time_to),
                "Is Active": self.client.make_checkbox(True),
                "Created At": self.client.make_date(),
            })
        label = NOTIFICATION_CHOICES[notification_type]
        return f"Расписание для «{label}»: каждые {interval_minutes} мин., {time_from}-{time_to}"

    def _validate_time(self, s):
        try:
            h, m = map(int, s.split(":"))
            return 0 <= h <= 23 and 0 <= m <= 59
        except ValueError:
            return False


class ContentService:
    """Сервис для работы с БД «Моя коллекция программ и утилит»."""

    def __init__(self, client: NotionClient, content_db_id: str):
        self.client = client
        self.db_id = content_db_id

    async def list_items(self, page_size=5, start_cursor=None):
        """Возвращает список записей с пагинацией."""
        sorts = [{"property": "Дата добавления", "direction": "descending"}]
        payload = {"sorts": sorts, "page_size": page_size}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        raw = await self.client._request("POST", f"/databases/{self.db_id}/query", json_data=payload)
        items = []
        for r in raw.get("results", []):
            items.append(self._parse_item(r))
        return items, raw.get("next_cursor"), raw.get("has_more")

    async def search_items(self, query: str):
        """Поиск по названию."""
        r = await self.client.query_database(self.db_id, filter_={
            "property": "Название", "title": {"contains": query},
        })
        return [self._parse_item(p) for p in r]

    async def get_item(self, page_id: str):
        """Получить одну запись по ID."""
        page = await self.client.get_page(page_id)
        return self._parse_item(page)

    async def add_item(self, name: str, item_type: str, source: str, url: str,
                       description: str, tags: list[str], notes: str = ""):
        """Добавить новую запись (статус = Новое)."""
        props = {
            "Название": self.client.make_title(name),
            "Тип": self.client.make_select(item_type) if item_type else None,
            "Источник": self.client.make_select(source) if source else None,
            "URL": self.client.make_url(url) if url else None,
            "Описание": self.client.make_rich_text(description) if description else None,
            "Теги": {"multi_select": [{"name": t} for t in tags]} if tags else None,
            "Статус": self.client.make_select("Новое"),
            "Дата добавления": self.client.make_date(),
        }
        if notes:
            props["Заметки"] = self.client.make_rich_text(notes)
        props = {k: v for k, v in props.items() if v is not None}
        page = await self.client.create_page(self.db_id, props)
        return self.client.page_id(page)

    async def get_pending(self):
        """Записи со статусом Новое (на модерации)."""
        r = await self.client.query_database(self.db_id, filter_={
            "property": "Статус", "select": {"equals": "Новое"},
        })
        return [self._parse_item(p) for p in r]

    async def approve_item(self, page_id: str, status: str = "Проверено"):
        """Утвердить запись (сменить статус)."""
        valid_statuses = ["Проверено", "В использовании", "Тестирую", "Архив", "Не подходит"]
        if status not in valid_statuses:
            raise ValueError(f"Статус должен быть: {', '.join(valid_statuses)}")
        await self.client.update_page(page_id, {"Статус": self.client.make_select(status)})

    def _parse_item(self, page: dict):
        p = page["properties"]
        return {
            "id": self.client.page_id(page),
            "name": self.client.prop_title(p, "Название"),
            "type": self.client.prop_select(p, "Тип"),
            "source": self.client.prop_select(p, "Источник"),
            "url": self.client.prop_url(p, "URL"),
            "description": self.client.prop_rich_text(p, "Описание"),
            "tags": self.client.prop_multi_select(p, "Теги"),
            "status": self.client.prop_select(p, "Статус"),
            "notes": self.client.prop_rich_text(p, "Заметки"),
            "date": self.client.prop_date(p, "Дата добавления"),
        }

    @staticmethod
    async def parse_url(url: str) -> dict:
        """Парсинг URL: заголовок, описание, домен. Поддержка og:, Twitter Card, Telegram."""
        parsed = urlparse(url)
        domain = parsed.netloc
        result = {"title": "", "description": "", "domain": domain}
        is_telegram = "t.me" in domain or "telegram" in domain
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                resp = await c.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                })
                if resp.status_code != 200:
                    return result
                html = resp.text

                if is_telegram:
                    result = await ContentService._parse_telegram(html, url)
                    if result.get("title"):
                        return result

                # 1. og:title > twitter:title > <title>
                m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
                if not m:
                    m = re.search(r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
                if not m:
                    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                if m:
                    result["title"] = re.sub(r'\s+', ' ', _clean_html(m.group(1))).strip()[:200]

                # 2. og:description > meta description > twitter:description
                m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
                if not m:
                    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
                if not m:
                    m = re.search(r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
                if not m:
                    m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', html, re.IGNORECASE)
                if m:
                    result["description"] = _clean_html(m.group(1))[:500]

                # 3. og:image
                m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
                if m:
                    result["image"] = m.group(1)

                # 4. JSON-LD
                for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL):
                    try:
                        import json
                        ld = json.loads(m.group(1))
                        if isinstance(ld, dict):
                            if not result["title"] and ld.get("name"):
                                result["title"] = ld["name"]
                            if not result["description"] and ld.get("description"):
                                result["description"] = ld["description"]
                    except json.JSONDecodeError:
                        pass

                # 5. Fallback: первый <h1>
                if not result["title"]:
                    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
                    if m:
                        result["title"] = _clean_html(m.group(1)).strip()[:200]

        except Exception as e:
            logger.warning("Parse error for %s: %s", url, e)
        return result

    @staticmethod
    async def _parse_telegram(html: str, url: str) -> dict:
        """Специализированный парсер для Telegram-постов."""
        result = {"title": "", "description": "", "domain": "t.me"}

        def _meta_content(html: str, attr: str, value: str) -> str | None:
            for q in ['"', "'"]:
                for aq in ['"', "'"]:
                    m = re.search(
                        rf'<meta[^>]+{attr}={q}{re.escape(value)}{q}[^>]+content={aq}([^{aq}]*){aq}',
                        html, re.IGNORECASE,
                    )
                    if m:
                        return _clean_html(m.group(1))
                    m = re.search(
                        rf'<meta[^>]+content={q}([^{q}]*){q}[^>]+{attr}={aq}{re.escape(value)}{aq}',
                        html, re.IGNORECASE,
                    )
                    if m:
                        return _clean_html(m.group(1))
            return None

        og_title = _meta_content(html, "property", "og:title")
        og_desc = _meta_content(html, "property", "og:description")

        if og_title:
            prefixes = ["Telegram: Contact @", "Telegram: Share", "Telegram:"]
            if not any(og_title.startswith(p) for p in prefixes):
                result["title"] = og_title[:200]

        if og_desc:
            result["description"] = og_desc[:500]

        m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
        if m:
            raw_text = m.group(1)
            raw_text = re.sub(r'<br\s*/?>', '\n', raw_text)
            raw_text = re.sub(r'<[^>]+>', '', raw_text)
            raw_text = re.sub(r'\n{3,}', '\n\n', raw_text).strip()
            if raw_text:
                if not result["title"]:
                    result["title"] = raw_text.split("\n")[0][:200]
                if not result["description"] or len(result["description"]) < len(raw_text):
                    result["description"] = raw_text[:1500]

        return result


class NotificationService:
    def __init__(self, client: NotionClient, logs_db_id: str, bot,
                 sched_db_id: str, content_db_id: str | None = None):
        self.client = client
        self.logs_db_id = logs_db_id
        self.sched_db_id = sched_db_id
        self.content_db_id = content_db_id
        self.bot = bot
        self._notified_ids: set[str] = set()
        self._last_schedule_send: dict[str, float] = {}

    async def load_notified_ids(self):
        """Загрузить ID уже уведомленных записей (чтобы не дублировать после перезапуска)."""
        if not self.content_db_id:
            return
        results = await self.client.query_database(self.content_db_id, filter_={
            "property": "Статус", "select": {"equals": "Проверено"},
        })
        for p in results:
            self._notified_ids.add(self.client.page_id(p))
        logger.info("Загружено %d уже уведомленных записей", len(self._notified_ids))

    async def send_notification(self, telegram_id: int, notification_type: NotificationType,
                                title=None, message=""):
        try:
            text = message
            if title:
                text = f"<b>{title}</b>\n\n{message}"
            await self.bot.send_message(chat_id=telegram_id, text=text, parse_mode="HTML")
            status = "sent"
        except Exception as e:
            status = "error"
            logger.error("Send error: %s", e)
            return False
        await self.client.create_page(self.logs_db_id, {
            "Name": self.client.make_title(f"{telegram_id} - {notification_type.value} - {datetime.now():%H:%M}"),
            "Telegram ID": self.client.make_number(telegram_id),
            "Notification Type": self.client.make_select(notification_type.value),
            "Title": self.client.make_rich_text(title or ""),
            "Message": self.client.make_rich_text(message),
            "Status": self.client.make_select(status),
            "Sent At": self.client.make_date(),
        })
        return status == "sent"

    async def send_scheduled_notifications(self, bot_id: int | None = None):
        now = datetime.now()
        current_total = now.hour * 60 + now.minute
        results = await self.client.query_database(self.sched_db_id, filter_={
            "property": "Is Active", "checkbox": {"equals": True},
        })
        sent = 0
        for sp in results:
            try:
                sp_id = self.client.page_id(sp)
                props = sp["properties"]
                ntype_name = self.client.prop_select(props, "Notification Type")
                if not ntype_name:
                    continue
                ntype = NotificationType(ntype_name)
                tid = self.client.prop_number(props, "Telegram ID")
                if not tid:
                    continue
                if bot_id and int(tid) == bot_id:
                    continue
                tf = self.client.prop_rich_text(props, "Time From") or "09:00"
                tt = self.client.prop_rich_text(props, "Time To") or "21:00"
                interval = self.client.prop_number(props, "Interval Minutes") or 60
                fh, fm = map(int, tf.split(":"))
                th, tm = map(int, tt.split(":"))
                if not (fh * 60 + fm <= current_total <= th * 60 + tm):
                    continue
                last = self._last_schedule_send.get(sp_id, 0)
                if last and (now.timestamp() - last) < interval * 60:
                    continue
                label = NOTIFICATION_CHOICES.get(ntype, ntype.value)
                ok = await self.send_notification(int(tid), ntype, label, f"Плановое уведомление «{label}».\n{now.strftime('%H:%M')}")
                if ok:
                    self._last_schedule_send[sp_id] = now.timestamp()
                    sent += 1
            except Exception as e:
                logger.exception("Schedule error: %s", e)
        return sent

    async def check_new_content(self, user_service: UserService, bot_id: int | None = None):
        if not self.content_db_id:
            return 0
        results = await self.client.query_database(self.content_db_id, sorts=[
            {"property": "Дата добавления", "direction": "descending"},
        ], page_size=20)
        if not results:
            return 0
        users = await user_service.get_all_active_users()
        if not users:
            return 0
        if bot_id:
            users = [u for u in users if u != bot_id]
            if not users:
                return 0
        total = 0
        for item in results:
            pid = self.client.page_id(item)
            if pid in self._notified_ids:
                continue
            p = item["properties"]
            status = self.client.prop_select(p, "Статус")
            if status != "Проверено":
                continue
            name = self.client.prop_title(p, "Название") or "Без названия"
            itype = self.client.prop_select(p, "Тип") or "-"
            url = self.client.prop_url(p, "URL") or ""
            desc = self.client.prop_rich_text(p, "Описание")
            tags = self.client.prop_multi_select(p, "Теги")
            msg = f"<b>{name}</b>\nТип: {itype}"
            if desc:
                msg += f"\n\n{desc[:300]}"
            if tags:
                msg += f"\n\nТеги: {', '.join(tags)}"
            if url:
                msg += f'\n\n<a href="{url}">Открыть</a>'
            for uid in users:
                ok = await self.send_notification(uid, NotificationType.CUSTOM, f"Новое в коллекции: {name}", msg)
                if ok:
                    total += 1
            self._notified_ids.add(pid)
            await asyncio.sleep(0.3)
        return total


class WatchedChannelService:
    """Мониторинг Telegram-каналов через RSS."""

    def __init__(self, client: NotionClient, db_id: str):
        self.client = client
        self.db_id = db_id
        self._seen: set[str] = set()

    async def add_channel(self, username: str, admin_id: int) -> str:
        username = username.removeprefix("https://t.me/").removeprefix("t.me/").strip().lstrip("@")
        if not username:
            return "Неверное имя канала."
        existing = await self.client.query_database(self.db_id, filter_={
            "property": "Username", "rich_text": {"equals": username},
        })
        if existing:
            return "Этот канал уже отслеживается."
        await self.client.create_page(self.db_id, {
            "Name": self.client.make_title(username),
            "Username": self.client.make_rich_text(username),
            "Added By": self.client.make_number(admin_id),
            "Is Active": self.client.make_checkbox(True),
            "Created At": self.client.make_date(),
        })
        return f"\u2705 Канал @{username} добавлен в отслеживание."

    async def remove_channel(self, username: str) -> str:
        username = username.removeprefix("https://t.me/").removeprefix("t.me/").strip().lstrip("@")
        existing = await self.client.query_database(self.db_id, filter_={
            "property": "Username", "rich_text": {"equals": username},
        })
        if not existing:
            return "Канал не найден."
        await self.client.update_page(self.client.page_id(existing[0]), {"Is Active": self.client.make_checkbox(False)})
        return f"\u2705 Канал @{username} отключён."

    async def get_active(self) -> list[dict]:
        r = await self.client.query_database(self.db_id, filter_={
            "property": "Is Active", "checkbox": {"equals": True},
        })
        return [{"id": self.client.page_id(p), "username": self.client.prop_rich_text(p["properties"], "Username") or ""} for p in r]

    async def fetch_rss(self, username: str, max_pages: int = 1) -> list[dict]:
        """Получить посты из Telegram-канала с пагинацией."""
        base_url = f"https://t.me/s/{username}"
        posts = []
        before = None
        for _ in range(max_pages):
            page_posts, next_before = await self._fetch_page(base_url, username, before)
            posts.extend(page_posts)
            if not next_before:
                break
            before = next_before
            await asyncio.sleep(0.3)
        return posts

    async def _fetch_page(self, base_url: str, username: str, before: str | None = None) -> tuple[list[dict], str | None]:
        url = base_url + (f"?before={before}" if before else "")
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                resp = await c.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })
                if resp.status_code != 200:
                    return [], None
                html = resp.text
                next_m = re.search(r'<a\s+href="/s/' + re.escape(username) + r'\?before=(\d+)"', html)
                next_before = next_m.group(1) if next_m else None
                posts = []
                blocks = re.split(r'<div class="tgme_widget_message_wrap', html)[1:]
                for block in blocks:
                    block = "<div class=\"tgme_widget_message_wrap" + block
                    post_id = _extract_post_id(block)
                    if not post_id:
                        continue
                    dt_m = re.search(r'<time\s+datetime="([^"]+)"', block)
                    if not dt_m:
                        continue
                    dt = dt_m.group(1)
                    text_m = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', block, re.DOTALL)
                    raw_text = _clean_html(text_m.group(1)) if text_m else ""
                    title = raw_text.split("\n")[0][:120] if raw_text else "-"
                    posts.append({"title": title, "text": raw_text[:2000], "date": dt, "url": f"https://t.me/{username}/{post_id}"})
                return posts, next_before
        except Exception as e:
            logger.warning("RSS page error for %s (before=%s): %s", username, before, e)
            return [], None


def _extract_post_id(block: str) -> str:
    m = re.search(r'data-post="([^"]+)"', block)
    return m.group(1).split("/")[-1] if m else ""
