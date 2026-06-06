import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    TOKEN: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))

    # Notion
    NOTION_TOKEN: str = field(default_factory=lambda: os.getenv("NOTION_TOKEN", ""))
    NOTION_PARENT_PAGE_ID: str = field(default_factory=lambda: os.getenv("NOTION_PARENT_PAGE_ID", ""))

    # ID баз данных Notion
    CONTENT_DATABASE_ID: str = field(default_factory=lambda: os.getenv("CONTENT_DATABASE_ID", ""))
    NOTION_USERS_DB_ID: str = field(default_factory=lambda: os.getenv("NOTION_USERS_DB_ID", ""))
    NOTION_SUBSCRIPTIONS_DB_ID: str = field(default_factory=lambda: os.getenv("NOTION_SUBSCRIPTIONS_DB_ID", ""))
    NOTION_SCHEDULES_DB_ID: str = field(default_factory=lambda: os.getenv("NOTION_SCHEDULES_DB_ID", ""))
    NOTION_LOGS_DB_ID: str = field(default_factory=lambda: os.getenv("NOTION_LOGS_DB_ID", ""))
    NOTION_WATCHED_DB_ID: str = field(default_factory=lambda: os.getenv("NOTION_WATCHED_DB_ID", ""))

    BOT_PROXY: str = field(default_factory=lambda: os.getenv("BOT_PROXY", ""))
    ADMIN_IDS: list[int] = field(default_factory=lambda: _parse_int_list(os.getenv("ADMIN_IDS", "")))
    SCHEDULER_INTERVAL_SECONDS: int = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # AI
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    DEEPSEEK_API_KEY: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    GROQ_API_KEY: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "auto")

    def __post_init__(self):
        if not self.TOKEN:
            raise ValueError("BOT_TOKEN не задан! Проверьте .env файл.")
        if not self.NOTION_TOKEN:
            raise ValueError("NOTION_TOKEN не задан!")
        if not self.NOTION_USERS_DB_ID:
            raise ValueError("NOTION_USERS_DB_ID не задан! Запустите notion_setup.py")


def _parse_int_list(value: str) -> list[int]:
    if not value:
        return []
    return [int(x.strip()) for x in value.split(",") if x.strip().isdigit()]


BASE_DIR = Path(__file__).resolve().parent


def get_config() -> Config:
    return Config()
