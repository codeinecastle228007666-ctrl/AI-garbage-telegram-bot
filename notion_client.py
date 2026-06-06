import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"


class NotionError(Exception):
    """Ошибка при работе с Notion API."""


class NotionClient:
    """Асинхронный клиент для Notion API."""

    BASE_URL = "https://api.notion.com/v1"

    def __init__(self, token: str):
        self._token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }
        self._client: httpx.AsyncClient | None = None

    async def _request(
        self, method: str, path: str, json_data: dict | None = None
    ) -> dict:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        url = f"{self.BASE_URL}{path}"
        try:
            r = await self._client.request(method, url, headers=self._headers, json=json_data)
            if r.status_code >= 400:
                raise NotionError(f"Notion API error {r.status_code}: {r.text}")
            return r.json()
        except httpx.RequestError as e:
            raise NotionError(f"HTTP error: {e}") from e

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ─── База данных (создание, запрос) ───

    async def create_database(self, parent_page_id: str, title: str, properties: dict) -> dict:
        return await self._request("POST", "/databases", json_data={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        })

    async def query_database(self, database_id: str, filter_: dict | None = None, sorts: list | None = None, **kwargs) -> list[dict]:
        body = {}
        if filter_:
            body["filter"] = filter_
        if sorts:
            body["sorts"] = sorts
        body.update(kwargs)
        data = await self._request("POST", f"/databases/{database_id}/query", json_data=body)
        return data.get("results", [])

    # ─── Страницы (создание, обновление) ───

    async def create_page(self, database_id: str, properties: dict) -> dict:
        return await self._request("POST", "/pages", json_data={
            "parent": {"type": "database_id", "database_id": database_id},
            "properties": properties,
        })

    async def update_page(self, page_id: str, properties: dict) -> dict:
        return await self._request("PATCH", f"/pages/{page_id}", json_data={"properties": properties})

    # ─── Хелперы для извлечения данных из свойств Notion ───

    @staticmethod
    def prop_title(props: dict, key: str) -> str:
        parts = props.get(key, {}).get("title", [])
        return "".join(t.get("plain_text", "") for t in parts)

    @staticmethod
    def prop_rich_text(props: dict, key: str) -> str:
        parts = props.get(key, {}).get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in parts)

    @staticmethod
    def prop_select(props: dict, key: str) -> str | None:
        s = props.get(key, {}).get("select")
        return s["name"] if s else None

    @staticmethod
    def prop_multi_select(props: dict, key: str) -> list[str]:
        return [s["name"] for s in props.get(key, {}).get("multi_select", [])]

    @staticmethod
    def prop_number(props: dict, key: str) -> int | float | None:
        return props.get(key, {}).get("number")

    @staticmethod
    def prop_checkbox(props: dict, key: str) -> bool:
        return props.get(key, {}).get("checkbox", False)

    @staticmethod
    def prop_date(props: dict, key: str) -> str | None:
        d = props.get(key, {}).get("date")
        return d["start"] if d else None

    @staticmethod
    def prop_url(props: dict, key: str) -> str | None:
        return props.get(key, {}).get("url")

    @staticmethod
    def prop_relation(props: dict, key: str) -> list[str]:
        return [r["id"] for r in props.get(key, {}).get("relation", [])]

    @staticmethod
    def page_id(page: dict) -> str:
        return page["id"]

    @staticmethod
    def make_title(text: str) -> dict:
        return {"title": [{"type": "text", "text": {"content": text}}]}

    @staticmethod
    def make_rich_text(text: str) -> dict:
        return {"rich_text": [{"type": "text", "text": {"content": text}}]}

    @staticmethod
    def make_select(name: str) -> dict:
        return {"select": {"name": name}}

    @staticmethod
    def make_number(value: int | float) -> dict:
        return {"number": value}

    @staticmethod
    def make_checkbox(value: bool) -> dict:
        return {"checkbox": value}

    @staticmethod
    def make_date(dt: datetime | None = None) -> dict:
        return {"date": {"start": (dt or datetime.now()).isoformat()}}

    @staticmethod
    def make_relation(page_ids: list[str]) -> dict:
        return {"relation": [{"id": pid} for pid in page_ids]}

    async def get_page(self, page_id: str) -> dict:
        return await self._request("GET", f"/pages/{page_id}")

    @staticmethod
    def make_url(url: str) -> dict:
        return {"url": url}
