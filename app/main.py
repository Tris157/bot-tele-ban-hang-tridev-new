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
from app.utils import money_vnd
from app.web_app import create_web_app


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


async def run_web_server(app, host: str, port: int) -> None:
    config = uvicorn.Config(app=app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def expire_orders_loop(db: Database, bot: Bot) -> None:
    """Background task: expire pending orders every 60s and notify users."""
    while True:
        await asyncio.sleep(60)
        try:
            expired = await db.expire_due_orders()
            for order in expired:
                try:
                    await bot.send_message(
                        chat_id=int(order["user_id"]),
                        text=(
                            f"⏰ <b>Đơn hàng đã hết hạn</b>\n"
                            f"Mã đơn: <code>{order['order_code']}</code>\n"
                            f"Tổng: <b>{money_vnd(int(order['total']))}</b>\n\n"
                            "Đơn chưa được thanh toán trong thời gian quy định.\n"
                            "Vui lòng tạo đơn mới nếu bạn vẫn muốn mua."
                        ),
                    )
                except Exception:
                    pass
            if expired:
                print(f"[EXPIRE] Đã hết hạn {len(expired)} đơn pending.")
        except Exception as e:
            print(f"[EXPIRE] Error: {e}")


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
    print(f"Auto-expire: đơn pending sẽ tự hết hạn sau {settings.order_expire_minutes} phút")

    await asyncio.gather(
        dp.start_polling(bot),
        run_web_server(web_app, settings.web_host, settings.web_port),
        expire_orders_loop(db, bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
