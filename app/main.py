from __future__ import annotations

import asyncio
import sys

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot_handlers import register_handlers
from app.config import get_settings
from app.db import Database
from app.sepay_client import SePayClient
from app.web_app import create_web_app


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


async def run_web_server(app, host: str, port: int) -> None:
    config = uvicorn.Config(app=app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    settings = get_settings()

    db = Database(settings)
    await db.init()
    await db.seed_products_from_json("data/products.json")

    sepay = SePayClient(settings)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    register_handlers(dp, db, sepay, settings)

    web_app = create_web_app(bot, db, sepay, settings)

    print("Bot Telegram đang chạy...")
    print(f"Web server: http://{settings.web_host}:{settings.web_port}")
    print(f"SePay webhook URL cần đăng ký: {settings.webhook_url}")

    await asyncio.gather(
        dp.start_polling(bot),
        run_web_server(web_app, settings.web_host, settings.web_port),
    )


if __name__ == "__main__":
    asyncio.run(main())
