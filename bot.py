import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import Config

logger = logging.getLogger(__name__)


def create_bot(config: Config) -> Bot:
    kwargs = {
        "token": config.TOKEN,
        "default": DefaultBotProperties(parse_mode=ParseMode.HTML),
    }
    if config.BOT_PROXY:
        kwargs["proxy"] = config.BOT_PROXY
        logger.info("Прокси установлен: %s", config.BOT_PROXY)

    bot = Bot(**kwargs)
    logger.info("Бот создан (id=%s)", config.TOKEN[:8])
    return bot


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    return dp
