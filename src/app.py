import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings
from src.handlers import build_router
from src.hero_sms import HeroSmsClient
from src.service import BotService
from src.storage import JsonStorage


async def _main() -> None:
    if not settings.tg_token:
        raise RuntimeError("tg_token is not configured")

    storage = JsonStorage(
        access_code_store_path=settings.access_code_store_path,
        user_session_store_path=settings.user_session_store_path,
        user_locale_store_path=settings.user_locale_store_path,
    )
    hero_sms = HeroSmsClient(
        api_key=settings.hero_sms_api_key,
        base_url=settings.hero_sms_base_url,
    )
    service = BotService(
        settings=settings,
        storage=storage,
        hero_sms=hero_sms,
    )
    bot = Bot(
        token=settings.tg_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(service))

    try:
        await service.resume_pending_requests(bot)
        await dispatcher.start_polling(bot, handle_signals=False)
    finally:
        await bot.session.close()
        await service.shutdown()


def run() -> None:
    asyncio.run(_main())
