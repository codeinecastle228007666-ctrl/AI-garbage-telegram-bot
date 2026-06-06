import asyncio
import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

ITEM_TYPES = ["Программа", "Утилита", "ИИ-агент", "Промпт", "Скрипт", "Шаблон"]
SOURCES = ["Telegram-канал", "GitHub", "Reddit", "Hacker News", "YouTube", "Блог/статья", "Другое"]

PROVIDERS = {
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent",
    },
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
    },
}


class AIService:
    def __init__(self, gemini_key: str | None = None, deepseek_key: str | None = None, groq_key: str | None = None, provider: str = "auto"):
        self._keys = {"gemini": gemini_key, "deepseek": deepseek_key, "groq": groq_key}
        self._provider = provider
        self._last_call = 0.0
        self._min_interval = 2.0

        if provider != "auto":
            self._enabled = bool(self._keys.get(provider))
            if self._enabled:
                logger.info("AI-сервис включён (%s)", provider.capitalize())
            else:
                logger.warning("AI-сервис отключён — нет ключа для %s", provider)
        elif groq_key:
            self._enabled = True
            self._provider = "groq"
            logger.info("AI-сервис включён (Groq, авто)")
        elif deepseek_key:
            self._enabled = True
            self._provider = "deepseek"
            logger.info("AI-сервис включён (DeepSeek, авто)")
        elif gemini_key:
            self._enabled = True
            self._provider = "gemini"
            logger.info("AI-сервис включён (Gemini, авто)")
        else:
            self._enabled = False
            logger.warning("AI-сервис отключён — нет API-ключа")

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _rate_limit(self):
        now = time.time()
        since_last = now - self._last_call
        if since_last < self._min_interval:
            await asyncio.sleep(self._min_interval - since_last)
        self._last_call = time.time()

    async def _query(self, prompt: str) -> str | None:
        if not self._enabled:
            return None
        await self._rate_limit()
        if self._provider == "gemini":
            return await self._query_gemini(prompt)
        return await self._query_openai(prompt)

    async def _query_gemini(self, prompt: str) -> str | None:
        key = self._keys.get("gemini")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                resp = await c.post(
                    f"{PROVIDERS['gemini']['url']}?key={key}",
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                if resp.status_code != 200:
                    logger.warning("Gemini API error %s: %s", resp.status_code, resp.text[:200])
                    return None
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return None
                parts = candidates[0].get("content", {}).get("parts", [])
                return parts[0].get("text") if parts else None
        except Exception as e:
            logger.warning("Gemini request error: %s", e)
            return None

    async def _query_openai(self, prompt: str) -> str | None:
        cfg = PROVIDERS.get(self._provider)
        if not cfg:
            return None
        key = self._keys.get(self._provider)
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                resp = await c.post(
                    cfg["url"],
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": cfg["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 2000,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("%s API error %s: %s", self._provider.capitalize(), resp.status_code, resp.text[:200])
                    return None
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning("%s request error: %s", self._provider.capitalize(), e)
            return None

    def _parse_json(self, data: str | None) -> dict | list | None:
        if not data:
            return None
        cleaned = data.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(cleaned)
        except Exception:
            return None

    async def classify(self, title: str, description: str = "", url: str = "") -> dict:
        if not self._enabled:
            return {"type": None, "source": None, "tags": [], "description": description}
        prompt = (
            f"Ты — классификатор. Определи тип, источник и теги по заголовку/описанию.\n"
            f"Заголовок: {title}\n"
            f"Описание: {description[:1000]}\n"
            f"URL: {url}\n\n"
            f"Придумай короткое название (name, 2-5 слов) для этой программы/утилиты.\n"
            f"Тип (один из): {', '.join(ITEM_TYPES)} или null если не подходит.\n"
            f"Источник (один из): {', '.join(SOURCES)} или null.\n"
            f"Теги: 2-5 англ. ключевых слов (python, ai, telegram, docker, api, cli, windows, linux, mac, web, browser, dev, security, privacy, automation, editor, media, network, database).\n"
            f"ИГРЫ, НОВОСТИ ПРО ИГРЫ, МЕДИА, МЕССЕНДЖЕРЫ — НЕ программы/утилиты. Для них type=null.\n"
            f"Верни ТОЛЬКО JSON:\n"
            f'{{"name": "...", "type": "...", "source": "...", "tags": [...], "description": "..."}}'
        )
        try:
            data = await self._query(prompt)
            result = self._parse_json(data) or {}
            if result.get("type") not in ITEM_TYPES:
                result["type"] = None
            if result.get("source") not in SOURCES:
                result["source"] = None
            result.setdefault("tags", [])
            result.setdefault("description", description)
            result.setdefault("name", title)
            return result
        except Exception as e:
            logger.warning("AI classify error: %s", e)
            return {"type": None, "source": None, "tags": [], "description": description, "name": title}

    async def is_relevant_post(self, title: str, text: str) -> tuple[bool, dict]:
        if not self._enabled:
            return False, {}
        prompt = (
            f"Определи, является ли этот пост описанием ПОЛЕЗНОЙ программы, утилиты, библиотеки, инструмента, сервиса, промпта или скрипта.\n"
            f"Заголовок: {title}\n"
            f"Текст: {text[:2000]}\n\n"
            f"НЕ считается: игры, новости игр, трейлеры, фильмы, сериалы, музыка, мемы, мессенджеры/соцсети, общие новости, политика, крипта/биткоин.\n"
            f"Считается: IDE, редакторы, CLI-утилиты, библиотеки, фреймворки, базы данных, тулы для девов, AI-инструменты, промпты, скрипты, плагины, расширения браузера.\n"
            f"Если это реклама, новость, мем, общие рассуждения, игра, кино — relevant=false.\n"
            f"Если это анонс/обзор/релиз софта — relevant=true и заполни JSON.\n"
            f"Придумай КОРОТКОЕ название (name) для этой программы/утилиты, 2-5 слов.\n"
            f"Верни ТОЛЬКО JSON: {{\"relevant\": true/false, \"name\": \"...\", \"type\": \"...\", \"tags\": [...]}}"
        )
        try:
            data = await self._query(prompt)
            result = self._parse_json(data) or {}
            return bool(result.get("relevant")), result
        except Exception as e:
            logger.warning("AI relevance error: %s", e)
            return False, {}
