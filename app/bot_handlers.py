from __future__ import annotations

import time
from typing import Any

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import Settings
from app.db import Database
from app.keyboards import (
    admin_keyboard,
    admin_customers_keyboard,
    admin_manage_products_keyboard,
    admin_notify_product_keyboard,
    admin_orders_keyboard,
    admin_product_picker_keyboard,
    admin_wallet_customers_keyboard,
    confirm_order_keyboard,
    main_menu_keyboard,
    my_orders_keyboard,
    order_detail_keyboard,
    payment_keyboard,
    product_keyboard,
    profile_keyboard,
    shop_keyboard,
    start_keyboard,
    support_keyboard,
    wallet_keyboard,
    SUPPORT_USERNAME,
)
from app.sepay_client import SePayClient, SePayError
from app.utils import html_escape, money_vnd


router = Router()
pending_products: dict[int, str] = {}
pending_orders: dict[int, dict[str, Any]] = {}
pending_admin_add_accounts: dict[int, str] = {}
pending_admin_deposit: dict[int, int] = {}  # admin_user_id -> target_customer_id


def make_order_code() -> int:
    return int(time.time() * 1000) + random.randint(100, 999)


def cart_total(cart_items: list[dict[str, Any]]) -> int:
    return sum(int(item["price"]) * int(item["qty"]) for item in cart_items)


def render_start_text() -> str:
    return (
        "📌 <b>Đã bật menu nhanh dưới ô chat.</b>\n\n"
        "📌 <b>Hướng dẫn nhanh:</b>\n"
        "1. Nhấn nút “🛒 Mua hàng”.\n"
        "2. Chọn sản phẩm bạn muốn mua.\n"
        "3. Nhập số lượng cần mua.\n"
        "4. Chọn thanh toán và quét mã QR.\n"
        "5. Sau khi thanh toán xong, bot sẽ tự động xử lý đơn hàng.\n\n"
        "📌 <b>Vui lòng chọn menu:</b>"
    )


def render_shop_text(username: str | None) -> str:
    name = f"@{username}" if username else "cửa hàng"
    return f"Chào bạn đã đến với cửa hàng của {html_escape(name)}, hôm nay bạn muốn mua gì ^^"


def render_product_text(product: dict[str, Any], sold_count: int = 0) -> str:
    return (
        f"📧 <b>{html_escape(product['name'])}</b>\n"
        f"💵 Giá: <b>{money_vnd(int(product['price']))}</b>\n"
        f"➕ Tồn kho: <b>{product['stock']} tài khoản</b>\n"
        f"📊 Đã bán: <b>{sold_count} tài khoản</b>\n\n"
        "💬 <b>Mô tả:</b>\n"
        f"{html_escape(product.get('description'))}"
    )


def render_order_confirm(product: dict[str, Any], qty: int, *, wallet_balance: int = 0) -> str:
    total = int(product["price"]) * qty
    return (
        "🧾 <b>Xác nhận đơn hàng</b>\n"
        f"Sản phẩm: <b>{html_escape(product['name'])}</b>\n"
        f"Số lượng: <b>{qty}</b>\n"
        f"Thành tiền: <b>{money_vnd(int(product['price']))}</b>\n"
        f"💵 Tổng thanh toán: <b>{money_vnd(total)}</b>\n"
        f"👛 Số dư ví hiện tại: <b>{money_vnd(wallet_balance)}</b>\n\n"
        "Vui lòng chọn phương thức thanh toán:"
    )


def render_cart(cart_items: list[dict[str, Any]]) -> str:
    if not cart_items:
        return "🛒 <b>Giỏ hàng đang trống.</b>"

    lines = ["🛒 <b>Giỏ hàng của bạn</b>", ""]
    for item in cart_items:
        subtotal = int(item["price"]) * int(item["qty"])
        lines.append(f"• {html_escape(item['name'])} x{item['qty']}: <b>{money_vnd(subtotal)}</b>")
    lines.append("")
    lines.append(f"Tổng: <b>{money_vnd(cart_total(cart_items))}</b>")
    return "\n".join(lines)


def is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids


def render_admin_home(settings: Settings) -> str:
    admin_ids = ", ".join(str(admin_id) for admin_id in sorted(settings.admin_ids))
    return (
        "🛠 <b>Trang quản trị</b>\n\n"
        f"Admin ID: <code>{html_escape(admin_ids)}</code>\n"
        "Chọn chức năng bên dưới để quản lý shop."
    )


def render_order_detail(order: dict[str, Any]) -> str:
    username = order.get("username") or order.get("user_id")
    lines = [
        "🧾 <b>Chi tiết đơn hàng</b>",
        f"Mã đơn: <code>{order['order_code']}</code>",
        f"Khách: <code>{html_escape(str(username))}</code>",
        f"User ID: <code>{order['user_id']}</code>",
        f"Trạng thái: <b>{html_escape(str(order['status']))}</b>",
        f"Tổng tiền: <b>{money_vnd(int(order['total']))}</b>",
        f"Nội dung CK: <code>{html_escape(str(order.get('payment_link_id') or ''))}</code>",
        f"Tạo lúc: <code>{html_escape(str(order.get('created_at') or ''))}</code>",
    ]
    if order.get("paid_at"):
        lines.append(f"Thanh toán lúc: <code>{html_escape(str(order['paid_at']))}</code>")
    lines.append("")
    lines.append("📦 <b>Sản phẩm:</b>")
    for item in order.get("items", []):
        subtotal = int(item["price"]) * int(item["qty"])
        lines.append(
            f"• {html_escape(item['name'])} x{item['qty']} - <b>{money_vnd(subtotal)}</b>"
        )
    if order.get("accounts"):
        lines.append("")
        lines.append("🔐 <b>Tài khoản đã giao:</b>")
        for account in order["accounts"]:
            lines.append(f"<code>{html_escape(account['account_text'])}</code>")
    return "\n".join(lines)


async def send_shop(message: Message, db: Database) -> None:
    products = await db.list_products()
    if not products:
        await message.answer("Shop chưa có sản phẩm nào.", reply_markup=main_menu_keyboard())
        return
    await message.answer(
        render_shop_text(message.from_user.username if message.from_user else None),
        reply_markup=shop_keyboard(products),
    )


async def send_product(message: Message, product: dict[str, Any], db: Database | None = None) -> None:
    sold_count = 0
    if db:
        try:
            counts = await db.get_product_account_counts(product["id"])
            sold_count = counts.get("sold", 0)
        except Exception:
            pass
    text = render_product_text(product, sold_count=sold_count)
    markup = product_keyboard(product["id"], stock=int(product.get("stock", 0)))
    image_url = (product.get("image_url") or "").strip()
    if image_url:
        try:
            await message.answer_photo(photo=image_url, caption=text, reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=markup)


async def notify_stock_waiters(bot: Any, db: Database, product_id: str) -> tuple[int, int]:
    product = await db.get_product(product_id)
    if not product or int(product.get("stock", 0)) <= 0:
        return 0, 0

    waiters = await db.pop_stock_waiters(product_id)
    if not waiters:
        return 0, 0

    kb = InlineKeyboardBuilder()
    kb.button(text="Xem san pham", callback_data=f"view:{product_id}")
    kb.button(text="Mua ngay", callback_data=f"buy:{product_id}")
    kb.adjust(1)

    text = (
        "San pham ban dang cho da co hang lai.\n\n"
        f"San pham: <b>{html_escape(product['name'])}</b>\n"
        f"Gia: <b>{money_vnd(int(product['price']))}</b>\n"
        f"Kho hien tai: <b>{int(product['stock'])}</b>\n\n"
        "Bam nut ben duoi de mua."
    )

    sent = 0
    failed = 0
    for waiter in waiters:
        try:
            await bot.send_message(int(waiter["user_id"]), text, reply_markup=kb.as_markup())
            sent += 1
        except Exception:
            failed += 1
    return sent, failed


def register_handlers(dp: Dispatcher, db: Database, sepay: SePayClient, settings: Settings) -> None:
    @router.message(Command("start"))
    async def start(message: Message):
        # Create/update user profile
        await db.get_or_create_profile(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        
        # Notify admin about new user
        user_name = message.from_user.first_name or ""
        user_username = f"@{message.from_user.username}" if message.from_user.username else ""
        user_info = f"{user_name} {user_username}".strip()
        
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_message(
                    admin_id,
                    f"👤 <b>Có người vào dùng bot</b>\n"
                    f"User: <code>{html_escape(user_info)}</code>\n"
                    f"User ID: <code>{message.from_user.id}</code>"
                )
            except Exception:
                pass
        
        await message.answer("📌 Đã bật menu nhanh dưới ô chat.", reply_markup=main_menu_keyboard())
        await message.answer(render_start_text(), reply_markup=start_keyboard())

    @router.message(Command("shop"))
    @router.message(F.text == "🛍 Sản phẩm")
    async def shop(message: Message):
        await send_shop(message, db)

    @router.message(F.text == "💬 Hỗ trợ")
    async def support_text(message: Message):
        await message.answer(
            f"💬 <b>Hỗ trợ</b>\n\n"
            f"Nếu bạn cần hỗ trợ về đơn hàng, sản phẩm hoặc bất kỳ vấn đề gì, "
            f"vui lòng liên hệ Admin qua Telegram:\n\n"
            f"👤 Admin: <b>@{SUPPORT_USERNAME}</b>\n\n"
            f"Hoặc nhấn nút bên dưới để nhắn tin trực tiếp:",
            reply_markup=support_keyboard(),
        )

    @router.message(F.text == "👛 Ví")
    async def wallet_text(message: Message):
        balance = await db.get_wallet_balance(message.from_user.id)
        await message.answer(
            f"👛 <b>Ví của bạn</b>\n\n"
            f"💰 Số dư hiện tại: <b>{money_vnd(balance)}</b>\n\n"
            f"Bạn có thể nạp tiền vào ví để thanh toán nhanh hơn.",
            reply_markup=wallet_keyboard(),
        )

    @router.message(F.text == "🔗 API")
    async def api_text(message: Message):
        await message.answer(
            "🔗 <b>Liên kết API</b>\n\n"
            f"Tính năng API giúp bạn tích hợp mua hàng tự động.\n"
            f"Liên hệ Admin @{SUPPORT_USERNAME} để được cấp API key.\n\n"
            f"📖 Các endpoint hỗ trợ:\n"
            f"• <code>GET /api/products</code> - Danh sách sản phẩm\n"
            f"• <code>POST /api/order</code> - Tạo đơn hàng\n"
            f"• <code>GET /api/order/{{code}}</code> - Kiểm tra đơn",
            reply_markup=support_keyboard(),
        )

    @router.message(Command("apikey"))
    async def apikey_command(message: Message):
        # Create/update user profile first
        await db.get_or_create_profile(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        
        # Check if user already has a key
        existing_key = await db.get_user_api_key(message.from_user.id)
        
        kb = InlineKeyboardBuilder()
        if existing_key:
            kb.button(text="🔄 Tạo key mới (hủy key cũ)", callback_data="apikey:regenerate")
            kb.button(text="🏠 Menu chính", callback_data="mainmenu")
            kb.adjust(1)
            await message.answer(
                f"🔑 <b>API Key của bạn</b>\n\n"
                f"Key hiện tại:\n<code>{existing_key}</code>\n\n"
                f"📖 Tài liệu API: <b>{settings.public_base_url}/api/docs</b>\n\n"
                f"⚠️ Giữ key bí mật, không chia sẻ!",
                reply_markup=kb.as_markup(),
            )
        else:
            new_key = await db.create_api_key(message.from_user.id)
            await message.answer(
                f"✅ <b>API Key đã được tạo!</b>\n\n"
                f"🔑 Key:\n<code>{new_key}</code>\n\n"
                f"📖 Tài liệu API (Docs):\n👉 <b>{settings.public_base_url}/api/docs</b>\n\n"
                f"⚠️ Giữ key bí mật, không chia sẻ!",
            )

    @router.callback_query(F.data == "apikey:regenerate")
    async def apikey_regenerate(callback: CallbackQuery):
        new_key = await db.create_api_key(callback.from_user.id)
        await callback.message.answer(
            f"✅ <b>API Key mới đã được tạo!</b>\n\n"
            f"🔑 Key:\n<code>{new_key}</code>\n\n"
            f"📖 Tài liệu API (Docs):\n👉 <b>{settings.public_base_url}/api/docs</b>\n\n"
            f"⚠️ Key cũ đã bị hủy. Giữ key mới bí mật!",
        )
        await callback.answer("Đã tạo key mới!")

    @router.message(Command("admin"))
    async def admin_home(message: Message):
        if not is_admin(message.from_user.id, settings):
            await message.answer("Bạn không có quyền dùng lệnh này.")
            return
        await message.answer(
            render_admin_home(settings)
            + "\n\nBấm nút bên dưới để quản lý đơn, sản phẩm và kho tài khoản.",
            reply_markup=admin_keyboard(),
        )

    @router.message(Command("add_accounts"))
    async def add_accounts(message: Message):
        if not is_admin(message.from_user.id, settings):
            await message.answer("Bạn không có quyền dùng lệnh này.")
            return

        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(
                "Cú pháp:\n"
                "<code>/add_accounts product_id tài_khoản_1\n"
                "tài_khoản_2\n"
                "tài_khoản_3</code>\n\n"
                "Ví dụ:\n"
                "<code>/add_accounts gmail_2010_2022 user1@gmail.com|pass1\n"
                "user2@gmail.com|pass2</code>"
            )
            return

        product_id = parts[1].strip()
        account_texts = parts[2].splitlines()
        added, result = await db.add_product_accounts(product_id, account_texts)
        notified, notify_failed = (0, 0)
        if added > 0:
            notified, notify_failed = await notify_stock_waiters(message.bot, db, product_id)
        await message.answer(
            f"🔐 <b>{html_escape(result)}</b>\n"
            f"Sản phẩm: <code>{html_escape(product_id)}</code>\n"
            f"Số tài khoản thêm: <b>{added}</b>",
            reply_markup=admin_keyboard(),
        )

    @router.callback_query(F.data == "admin:add_accounts")
    async def admin_add_accounts_pick_product(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        products = await db.list_products()
        if not products:
            await callback.message.answer("Chưa có sản phẩm nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        await callback.message.answer(
            "➕ <b>Nạp tài khoản</b>\nChọn sản phẩm cần nạp:",
            reply_markup=admin_product_picker_keyboard(products, prefix="admin:add_to"),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:add_to:"))
    async def admin_add_accounts_wait_text(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        product_id = callback.data.rsplit(":", 1)[1]
        product = await db.get_product(product_id)
        if not product:
            await callback.answer("Không tìm thấy sản phẩm.", show_alert=True)
            return
        pending_admin_add_accounts[callback.from_user.id] = product_id
        await callback.message.answer(
            "📥 <b>Dán danh sách tài khoản cần nạp</b>\n"
            f"Sản phẩm: <b>{html_escape(product['name'])}</b>\n\n"
            "Mỗi dòng là một tài khoản, ví dụ:\n"
            "<code>user1@gmail.com|pass1|recover1@gmail.com\n"
            "user2@gmail.com|pass2|recover2@gmail.com</code>\n\n"
            "Gửi /cancel để hủy."
        )
        await callback.answer()

    @router.message(Command("cancel"))
    async def cancel_pending(message: Message):
        pending_admin_add_accounts.pop(message.from_user.id, None)
        pending_products.pop(message.from_user.id, None)
        pending_orders.pop(message.from_user.id, None)
        pending_admin_deposit.pop(message.from_user.id, None)
        await message.answer("Đã hủy thao tác đang chờ.", reply_markup=main_menu_keyboard())

    @router.callback_query(F.data == "admin:home")
    async def admin_home_callback(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        await callback.message.answer(render_admin_home(settings), reply_markup=admin_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "admin:stats")
    async def admin_stats(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        stats = await db.get_order_stats()
        await callback.message.answer(
            "📊 <b>Thống kê shop</b>\n\n"
            f"Đơn hàng: <b>{stats['total_orders']}</b>\n"
            f"Đang chờ thanh toán: <b>{stats['pending_orders']}</b>\n"
            f"Đã thanh toán: <b>{stats['paid_orders']}</b>\n"
            f"Doanh thu đã thanh toán: <b>{money_vnd(stats['revenue'])}</b>\n"
            f"Sản phẩm đang bán: <b>{stats['products']}</b>",
            reply_markup=admin_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin:orders")
    async def admin_orders_callback(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        orders = await db.list_orders(limit=10)
        if not orders:
            await callback.message.answer("Chưa có đơn hàng nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        await callback.message.answer(
            "📦 <b>10 đơn mới nhất</b>\nChọn một đơn để xem chi tiết.",
            reply_markup=admin_orders_keyboard(orders),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:order:"))
    async def admin_order_detail(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        order_code = int(callback.data.rsplit(":", 1)[1])
        order = await db.get_order_by_code(order_code)
        if not order:
            await callback.answer("Không tìm thấy đơn.", show_alert=True)
            return
        await callback.message.answer(render_order_detail(order), reply_markup=admin_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "admin:products")
    async def admin_products(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        products = await db.list_products()
        if not products:
            await callback.message.answer("Chưa có sản phẩm nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        lines = ["🛍 <b>Sản phẩm đang bán</b>", ""]
        for product in products:
            lines.append(
                f"• <code>{html_escape(product['id'])}</code> | "
                f"{html_escape(product['name'])} | {money_vnd(int(product['price']))} | "
                f"Kho: <b>{product['stock']}</b>"
            )
        await callback.message.answer("\n".join(lines), reply_markup=admin_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "admin:accounts")
    async def admin_accounts(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        inventory = await db.get_account_inventory()
        if not inventory:
            await callback.message.answer("Chưa có sản phẩm nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        lines = [
            "🔐 <b>Kho tài khoản</b>",
            "",
            "Bấm <b>➕ Nạp tài khoản</b> để chọn sản phẩm rồi dán danh sách tài khoản.",
            "",
        ]
        for item in inventory:
            lines.append(
                f"• <code>{html_escape(item['id'])}</code> | "
                f"Kho bán: <b>{item['stock']}</b> | "
                f"TK trống: <b>{item['available_accounts']}</b> | "
                f"Đã bán: <b>{item['sold_accounts']}</b>"
            )
        await callback.message.answer("\n".join(lines), reply_markup=admin_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "admin:manage_products")
    async def admin_manage_products(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        products = await db.get_all_products()
        if not products:
            await callback.message.answer("Chưa có sản phẩm nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        await callback.message.answer(
            "🔄 <b>Quản lý sản phẩm</b>\n"
            "👁 = Đang hiển thị | 🚫 = Đã ẩn\n"
            "Nhấn sản phẩm để ẩn/hiển thị:",
            reply_markup=admin_manage_products_keyboard(products),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:toggle_product:"))
    async def admin_toggle_product(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        product_id = callback.data.rsplit(":", 1)[1]
        success, status, product = await db.toggle_product_active(product_id)
        if not success or not product:
            await callback.answer(f"Lỗi: {status}", show_alert=True)
            return
        
        product_status = "Hiển thị" if product["active"] else "Ẩn"
        await callback.answer(f"✅ {product['name']}: {product_status}", show_alert=True)
        
        # Refresh the management list
        products = await db.get_all_products()
        try:
            await callback.message.edit_text(
                "🔄 <b>Quản lý sản phẩm</b>\n"
                "👁 = Đang hiển thị | 🚫 = Đã ẩn\n"
                "Nhấn sản phẩm để ẩn/hiển thị:",
                reply_markup=admin_manage_products_keyboard(products),
            )
        except Exception:
            pass

    @router.callback_query(F.data == "admin:delete_product")
    async def admin_delete_product_start(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        products = await db.get_all_products()
        if not products:
            await callback.message.answer("Chưa có sản phẩm nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        kb = InlineKeyboardBuilder()
        for product in products:
            kb.button(
                text=f"🗑 {product['name']} | kho {product['stock']}",
                callback_data=f"admin:del:{product['id']}",
            )
        kb.button(text="⬅️ Về admin", callback_data="admin:home")
        kb.adjust(1)
        await callback.message.answer(
            "🗑 <b>Xóa sản phẩm</b>\n"
            "⚠️ Sản phẩm sẽ bị xóa vĩnh viễn kèm tài khoản trong kho.\n"
            "Chọn sản phẩm cần xóa:",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:del:"))
    async def admin_delete_product_confirm(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        product_id = callback.data.rsplit(":", 1)[1]
        product = await db.get_product(product_id)
        if not product:
            # Try get from all products (including hidden)
            all_products = await db.get_all_products()
            product = next((p for p in all_products if p["id"] == product_id), None)
        if not product:
            await callback.answer("Không tìm thấy sản phẩm.", show_alert=True)
            return

        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Xác nhận xóa", callback_data=f"admin:delconfirm:{product_id}")
        kb.button(text="❌ Hủy", callback_data="admin:home")
        kb.adjust(2)
        await callback.message.answer(
            f"⚠️ <b>Xác nhận xóa sản phẩm</b>\n\n"
            f"Sản phẩm: <b>{html_escape(product['name'])}</b>\n"
            f"Kho: <b>{product.get('stock', 0)}</b>\n\n"
            f"Thao tác này <b>không thể hoàn tác</b>!",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:delconfirm:"))
    async def admin_delete_product_execute(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        product_id = callback.data.rsplit(":", 1)[1]
        success, result = await db.delete_product(product_id)
        if success:
            await callback.message.answer(
                f"✅ <b>{html_escape(result)}</b>",
                reply_markup=admin_keyboard(),
            )
        else:
            await callback.message.answer(
                f"❌ {html_escape(result)}",
                reply_markup=admin_keyboard(),
            )
        await callback.answer()

    @router.callback_query(F.data == "admin:add_product")
    async def admin_add_product_start(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        pending_products[callback.from_user.id] = "ADD_PRODUCT"
        await callback.message.answer(
            "➕ <b>Thêm sản phẩm mới</b>\n\n"
            "Nhập thông tin sản phẩm theo format:\n"
            "<code>id_product|Tên sản phẩm|Giá|Số lượng|Mô tả|URL hình ảnh|Text giao hàng</code>\n\n"
            "Ví dụ:\n"
            "<code>gmail_2024|Gmail Account|50000|100|Tài khoản gmail mới|https://example.com/image.jpg|user@gmail.com|pass123</code>\n\n"
            "Các trường sau dấu phẩy lần 4 là tùy chọn (có thể bỏ trống). Gửi /cancel để hủy."
        )
        await callback.answer()

    @router.message(
        lambda message: bool(
            message.from_user
            and message.text
            and message.from_user.id in settings.admin_ids
            and pending_products.get(message.from_user.id) == "ADD_PRODUCT"
            and not (message.text or "").startswith("/")
        )
    )
    async def receive_add_product_info(message: Message):
        if not message.from_user or not is_admin(message.from_user.id, settings):
            return
        
        text = (message.text or "").strip()
        if text.startswith("/"):
            return
        
        try:
            parts = text.split("|")
            if len(parts) < 4:
                await message.answer(
                    "❌ Sai format. Cần ít nhất: id_product|Tên|Giá|Số lượng\n\n"
                    "Gửi lại hoặc /cancel để hủy."
                )
                return
            
            product_id = parts[0].strip()
            name = parts[1].strip()
            try:
                price = int(parts[2].strip())
                stock = int(parts[3].strip())
            except ValueError:
                await message.answer("❌ Giá và số lượng phải là số nguyên. Gửi lại hoặc /cancel để hủy.")
                return
            
            description = parts[4].strip() if len(parts) > 4 else ""
            image_url = parts[5].strip() if len(parts) > 5 else ""
            delivery_text = parts[6].strip() if len(parts) > 6 else ""
            
            # Check if product already exists
            existing = await db.get_product(product_id)
            if existing:
                await message.answer(
                    f"❌ Sản phẩm với ID '<code>{html_escape(product_id)}</code>' đã tồn tại.\n\n"
                    "Gửi lại với ID khác hoặc /cancel để hủy."
                )
                return
            
            success, result = await db.add_product(
                product_id=product_id,
                name=name,
                price=price,
                stock=stock,
                description=description,
                image_url=image_url,
                delivery_text=delivery_text,
            )
            
            if success:
                pending_products.pop(message.from_user.id, None)
                await message.answer(
                    f"✅ {result}\n\n"
                    f"ID: <code>{html_escape(product_id)}</code>\n"
                    f"Tên: <b>{html_escape(name)}</b>\n"
                    f"Giá: <b>{money_vnd(price)}</b>\n"
                    f"Kho: <b>{stock}</b>",
                    reply_markup=admin_keyboard(),
                )
            else:
                await message.answer(f"❌ {result}\n\nGửi lại hoặc /cancel để hủy.")
        except Exception as e:
            await message.answer(f"❌ Lỗi: {str(e)}\n\nGửi lại hoặc /cancel để hủy.")

    @router.callback_query(F.data == "admin:notify_product")
    async def admin_notify_product_start(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        products = await db.list_products()
        if not products:
            await callback.message.answer("Chưa có sản phẩm nào để thông báo.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        await callback.message.answer(
            "📢 <b>Thông báo sản phẩm mới</b>\nChọn sản phẩm cần thông báo:",
            reply_markup=admin_notify_product_keyboard(products),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:notify:"))
    async def admin_notify_pick_product(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        product_id = callback.data.rsplit(":", 1)[1]
        product = await db.get_product(product_id)
        if not product:
            await callback.answer("Không tìm thấy sản phẩm.", show_alert=True)
            return
        
        pending_products[callback.from_user.id] = f"NOTIFY:{product_id}"
        await callback.message.answer(
            f"📢 <b>Nhập nội dung thông báo cho sản phẩm:</b>\n\n"
            f"<b>{html_escape(product['name'])}</b>\n"
            f"Giá: <b>{money_vnd(int(product['price']))}</b>\n"
            f"Kho: <b>{product['stock']}</b>\n\n"
            "Gửi /cancel để hủy."
        )
        await callback.answer()

    @router.message(
        lambda message: bool(
            message.from_user
            and message.text
            and message.from_user.id in settings.admin_ids
            and isinstance(pending_products.get(message.from_user.id), str)
            and pending_products.get(message.from_user.id, "").startswith("NOTIFY:")
            and not (message.text or "").startswith("/")
        )
    )
    async def receive_notify_message(message: Message):
        if not message.from_user or not is_admin(message.from_user.id, settings):
            return
        
        pending_key = pending_products.get(message.from_user.id)
        if not isinstance(pending_key, str) or not pending_key.startswith("NOTIFY:"):
            return
        
        product_id = pending_key.split(":", 1)[1]
        product = await db.get_product(product_id)
        if not product:
            await message.answer("Sản phẩm không tồn tại.", reply_markup=main_menu_keyboard())
            pending_products.pop(message.from_user.id, None)
            return
        
        notify_message = (message.text or "").strip()
        
        # Get all customers
        customers = await db.get_all_customers()
        
        if not customers:
            await message.answer(
                "❌ Chưa có khách hàng nào để gửi thông báo.",
                reply_markup=admin_keyboard(),
            )
            pending_products.pop(message.from_user.id, None)
            return
        
        # Build notification message
        notify_text = (
            f"📢 <b>THÔNG BÁO SẢN PHẨM MỚI</b>\n\n"
            f"📦 <b>{html_escape(product['name'])}</b>\n"
            f"💵 Giá: <b>{money_vnd(int(product['price']))}</b>\n"
            f"📊 Kho: <b>{product['stock']}</b> sản phẩm\n\n"
            f"💬 <b>Thông báo từ Shop:</b>\n"
            f"{html_escape(notify_message)}\n\n"
            "🛒 Nhấn nút dưới để xem sản phẩm!"
        )
        
        kb = InlineKeyboardBuilder()
        kb.button(text="🛒 Xem sản phẩm", callback_data=f"view:{product_id}")
        
        # Send to all customers
        sent_count = 0
        failed_count = 0
        
        for customer_id in customers:
            try:
                await message.bot.send_message(
                    customer_id,
                    notify_text,
                    reply_markup=kb.as_markup(),
                )
                sent_count += 1
            except Exception:
                failed_count += 1
        
        pending_products.pop(message.from_user.id, None)
        
        await message.answer(
            f"✅ <b>Đã gửi thông báo</b>\n\n"
            f"Sản phẩm: <b>{html_escape(product['name'])}</b>\n"
            f"Gửi thành công: <b>{sent_count}</b> người\n"
            f"Gửi thất bại: <b>{failed_count}</b> người",
            reply_markup=admin_keyboard(),
        )

    @router.callback_query(F.data == "admin:notify_private")
    async def admin_notify_private_start(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        customers = await db.get_customers_detailed()
        if not customers:
            await callback.message.answer("Chưa có khách hàng nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        await callback.message.answer(
            "📨 <b>Thông báo riêng cho khách hàng</b>\nChọn khách hàng cần gửi thông báo:",
            reply_markup=admin_customers_keyboard(customers),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:notify_private:"))
    async def admin_notify_private_pick_customer(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        customer_id = int(callback.data.rsplit(":", 1)[1])
        pending_products[callback.from_user.id] = f"NOTIFY_PRIVATE:{customer_id}"
        await callback.message.answer(
            f"📨 <b>Nhập nội dung thông báo riêng</b>\n\n"
            f"Khách hàng ID: <code>{customer_id}</code>\n\n"
            "Gửi /cancel để hủy."
        )
        await callback.answer()

    @router.message(
        lambda message: bool(
            message.from_user
            and message.text
            and message.from_user.id in settings.admin_ids
            and isinstance(pending_products.get(message.from_user.id), str)
            and pending_products.get(message.from_user.id, "").startswith("NOTIFY_PRIVATE:")
            and not (message.text or "").startswith("/")
        )
    )
    async def receive_notify_private_message(message: Message):
        if not message.from_user or not is_admin(message.from_user.id, settings):
            return
        
        pending_key = pending_products.get(message.from_user.id)
        if not isinstance(pending_key, str) or not pending_key.startswith("NOTIFY_PRIVATE:"):
            return
        
        customer_id = int(pending_key.split(":", 1)[1])
        notify_message = (message.text or "").strip()
        
        # Build notification message
        notify_text = (
            f"📨 <b>THÔNG BÁO RIÊNG TỪ SHOP</b>\n\n"
            f"{html_escape(notify_message)}"
        )
        
        # Send to customer
        try:
            await message.bot.send_message(
                customer_id,
                notify_text,
            )
            pending_products.pop(message.from_user.id, None)
            await message.answer(
                f"✅ <b>Đã gửi thông báo</b>\n\n"
                f"Khách hàng ID: <code>{customer_id}</code>\n"
                f"Nội dung: {html_escape(notify_message[:50])}...",
                reply_markup=admin_keyboard(),
            )
        except Exception as e:
            await message.answer(
                f"❌ Gửi thất bại: {str(e)}\n\n"
                f"Hãy kiểm tra khách hàng ID hoặc thử lại sau.",
                reply_markup=admin_keyboard(),
            )
            pending_products.pop(message.from_user.id, None)

    @router.callback_query(F.data == "admin:deposit_wallet")
    async def admin_deposit_wallet_start(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        customers = await db.get_customers_detailed()
        if not customers:
            await callback.message.answer("Chưa có khách hàng nào.", reply_markup=admin_keyboard())
            await callback.answer()
            return
        # Enrich with wallet balance
        enriched = []
        for c in customers:
            profile = await db.get_user_profile(int(c["user_id"]))
            balance = int(profile["wallet_balance"]) if profile else 0
            enriched.append({**c, "wallet_balance": balance})
        await callback.message.answer(
            "💰 <b>Nạp ví khách hàng</b>\nChọn khách hàng cần nạp ví:",
            reply_markup=admin_wallet_customers_keyboard(enriched),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:deposit_to:"))
    async def admin_deposit_to_customer(callback: CallbackQuery):
        if not is_admin(callback.from_user.id, settings):
            await callback.answer("Bạn không có quyền.", show_alert=True)
            return
        customer_id = int(callback.data.rsplit(":", 1)[1])
        pending_admin_deposit[callback.from_user.id] = customer_id
        profile = await db.get_user_profile(customer_id)
        balance = int(profile["wallet_balance"]) if profile else 0
        await callback.message.answer(
            f"💰 <b>Nạp ví cho khách hàng</b>\n\n"
            f"Khách hàng ID: <code>{customer_id}</code>\n"
            f"Số dư hiện tại: <b>{money_vnd(balance)}</b>\n\n"
            "Nhập số tiền cần nạp (VNĐ):\n"
            "Gửi /cancel để hủy."
        )
        await callback.answer()

    @router.message(
        lambda message: bool(
            message.from_user
            and message.text
            and message.from_user.id in settings.admin_ids
            and message.from_user.id in pending_admin_deposit
            and not (message.text or "").startswith("/")
        )
    )
    async def receive_admin_deposit_amount(message: Message):
        if not message.from_user or not is_admin(message.from_user.id, settings):
            return
        customer_id = pending_admin_deposit.get(message.from_user.id)
        if not customer_id:
            return
        
        text = (message.text or "").strip().replace(".", "").replace(",", "")
        try:
            amount = int(text)
        except ValueError:
            await message.answer("❌ Số tiền không hợp lệ. Nhập số nguyên (VNĐ).\n\nGửi lại hoặc /cancel để hủy.")
            return
        
        if amount <= 0:
            await message.answer("❌ Số tiền phải lớn hơn 0.\n\nGửi lại hoặc /cancel để hủy.")
            return
        
        # Ensure profile exists
        await db.get_or_create_profile(user_id=customer_id)
        new_balance = await db.deposit_wallet(customer_id, amount)
        pending_admin_deposit.pop(message.from_user.id, None)
        
        await message.answer(
            f"✅ <b>Đã nạp ví thành công</b>\n\n"
            f"Khách hàng ID: <code>{customer_id}</code>\n"
            f"Số tiền nạp: <b>{money_vnd(amount)}</b>\n"
            f"Số dư mới: <b>{money_vnd(new_balance)}</b>",
            reply_markup=admin_keyboard(),
        )
        
        # Notify customer
        try:
            await message.bot.send_message(
                customer_id,
                f"💰 <b>Ví đã được nạp tiền</b>\n\n"
                f"Số tiền: <b>{money_vnd(amount)}</b>\n"
                f"Số dư mới: <b>{money_vnd(new_balance)}</b>\n\n"
                f"Cảm ơn bạn! Bạn có thể dùng ví để thanh toán nhanh.",
                reply_markup=main_menu_keyboard(),
            )
        except Exception:
            pass

    @router.callback_query(F.data == "shop")
    async def shop_callback(callback: CallbackQuery):
        products = await db.list_products()
        await callback.message.answer(
            render_shop_text(callback.from_user.username),
            reply_markup=shop_keyboard(products),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("view:"))
    async def view_product(callback: CallbackQuery):
        product_id = callback.data.split(":", 1)[1]
        product = await db.get_product(product_id)
        if not product:
            await callback.answer("Sản phẩm không tồn tại.", show_alert=True)
            return
        await send_product(callback.message, product, db)
        await callback.answer()

    @router.callback_query(F.data.startswith("waitstock:"))
    async def wait_stock(callback: CallbackQuery):
        product_id = callback.data.split(":", 1)[1]
        ok, message_text = await db.add_stock_waiter(
            product_id=product_id,
            user_id=callback.from_user.id,
            username=callback.from_user.username,
        )
        await callback.answer(message_text, show_alert=True)
        if ok:
            await callback.message.answer(
                "Da ghi nhan. Khi san pham co hang lai, bot se nhan tin cho ban.",
                reply_markup=main_menu_keyboard(),
            )

    @router.callback_query(F.data == "mainmenu")
    async def mainmenu_callback(callback: CallbackQuery):
        await callback.message.answer(render_start_text(), reply_markup=start_keyboard())
        await callback.answer()

    @router.callback_query(F.data.startswith("quickbuy:"))
    async def quickbuy_product(callback: CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Lỗi dữ liệu.", show_alert=True)
            return
        product_id = parts[1]
        qty = int(parts[2])
        product = await db.get_product(product_id)
        if not product:
            await callback.answer("Sản phẩm không tồn tại.", show_alert=True)
            return
        stock = int(product["stock"])
        if qty > stock:
            await callback.answer(f"Không đủ hàng. Tồn kho: {stock}", show_alert=True)
            return
        pending_orders[callback.from_user.id] = {"product": product, "qty": qty}
        wallet_balance = await db.get_wallet_balance(callback.from_user.id)
        await callback.message.answer(render_order_confirm(product, qty, wallet_balance=wallet_balance), reply_markup=confirm_order_keyboard())
        await callback.answer()

    @router.message(
        lambda message: bool(
            message.from_user
            and message.text
            and message.from_user.id in settings.admin_ids
            and message.from_user.id in pending_admin_add_accounts
        )
    )
    async def receive_admin_accounts(message: Message):
        if not message.from_user or not is_admin(message.from_user.id, settings):
            return
        product_id = pending_admin_add_accounts.get(message.from_user.id)
        if not product_id:
            return
        if (message.text or "").startswith("/"):
            return

        account_texts = (message.text or "").splitlines()
        added, result = await db.add_product_accounts(product_id, account_texts)
        notified, notify_failed = (0, 0)
        if added > 0:
            notified, notify_failed = await notify_stock_waiters(message.bot, db, product_id)
        pending_admin_add_accounts.pop(message.from_user.id, None)
        inventory = await db.get_product_account_counts(product_id)
        await message.answer(
            f"🔐 <b>{html_escape(result)}</b>\n"
            f"Sản phẩm: <code>{html_escape(product_id)}</code>\n"
            f"Đã thêm: <b>{added}</b>\n"
            f"Tài khoản trống: <b>{inventory['available']}</b>\n"
            f"Đã bán: <b>{inventory['sold']}</b>",
            reply_markup=admin_keyboard(),
        )


    @router.callback_query(F.data.startswith("buy:"))
    async def buy_product(callback: CallbackQuery):
        product_id = callback.data.split(":", 1)[1]
        product = await db.get_product(product_id)
        if not product:
            await callback.answer("Sản phẩm không tồn tại.", show_alert=True)
            return
        if int(product.get("stock", 0)) <= 0:
            await callback.answer("San pham dang het hang. Bam 'Nhac toi khi co hang' de duoc bao lai.", show_alert=True)
            await send_product(callback.message, product, db)
            return
        pending_products[callback.from_user.id] = product_id
        await callback.message.answer(
            f"📌 Vui lòng nhập số lượng muốn mua <b>(1-{product['stock']})</b>:"
        )
        await callback.answer()

    @router.message(F.text.regexp(r"^\d+$"))
    async def receive_quantity(message: Message):
        user_id = message.from_user.id
        product_id = pending_products.get(user_id)
        if not product_id:
            return

        product = await db.get_product(product_id)
        if not product:
            pending_products.pop(user_id, None)
            await message.answer("Sản phẩm không tồn tại hoặc đã bị ẩn.")
            return

        qty = int(message.text)
        stock = int(product["stock"])
        if qty < 1 or qty > stock:
            await message.answer(f"📌 Số lượng không hợp lệ. Vui lòng nhập từ 1 đến {stock}.")
            return

        pending_products.pop(user_id, None)
        pending_orders[user_id] = {"product": product, "qty": qty}
        wallet_balance = await db.get_wallet_balance(user_id)
        await message.answer(render_order_confirm(product, qty, wallet_balance=wallet_balance), reply_markup=confirm_order_keyboard())

    @router.callback_query(F.data == "pay:wallet")
    async def pay_wallet(callback: CallbackQuery):
        pending = pending_orders.get(callback.from_user.id)
        if not pending:
            await callback.answer("Không tìm thấy đơn đang chờ. Vui lòng chọn sản phẩm lại.", show_alert=True)
            return
        
        product = pending["product"]
        qty = int(pending["qty"])
        total = int(product["price"]) * qty
        
        balance = await db.get_wallet_balance(callback.from_user.id)
        if balance < total:
            await callback.answer(
                f"Ví không đủ số dư.\nCần: {money_vnd(total)}\nSố dư: {money_vnd(balance)}\n\nVui lòng nạp thêm hoặc chọn Thanh toán ngay.",
                show_alert=True,
            )
            return
        
        latest_product = await db.get_product(product["id"])
        if not latest_product or qty > int(latest_product["stock"]):
            await callback.answer("Sản phẩm không đủ tồn kho.", show_alert=True)
            return
        account_counts = await db.get_product_account_counts(latest_product["id"])
        if account_counts["total"] > 0 and qty > account_counts["available"]:
            await callback.answer("Sản phẩm không đủ tài khoản trong kho.", show_alert=True)
            return

        # Debit wallet
        success, new_balance = await db.debit_wallet(callback.from_user.id, total)
        if not success:
            await callback.answer(f"Ví không đủ số dư. Số dư hiện tại: {money_vnd(new_balance)}", show_alert=True)
            return
        
        order_code = make_order_code()
        item = {
            "id": latest_product["id"],
            "name": latest_product["name"],
            "price": int(latest_product["price"]),
            "qty": qty,
            "delivery_text": latest_product.get("delivery_text", ""),
        }
        await db.create_order(
            order_code=order_code,
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            items=[item],
            total=total,
        )
        
        # Auto-mark as paid since wallet was debited
        reference = f"wallet-{callback.from_user.id}-{order_code}"
        changed, message_text, paid_order = await db.mark_order_paid(
            order_code=order_code,
            amount=total,
            reference=reference,
        )
        
        pending_orders.pop(callback.from_user.id, None)
        
        if changed and paid_order:
            # Assign accounts
            assigned, assign_msg, assigned_order = await db.assign_accounts_to_order(order_code)
            if assigned and assigned_order:
                paid_order = assigned_order
            await db.clear_cart(callback.from_user.id)
            
            from app.web_app import build_delivery_message
            await callback.message.answer(build_delivery_message(paid_order))
            await callback.message.answer(
                f"👛 Số dư ví còn lại: <b>{money_vnd(new_balance)}</b>",
                reply_markup=main_menu_keyboard(),
            )
            
            # Notify admin
            for admin_id in settings.admin_ids:
                try:
                    await callback.message.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            "💰 <b>Có đơn thanh toán qua Ví</b>\n"
                            f"Mã đơn: <code>{order_code}</code>\n"
                            f"Khách: <code>{html_escape(callback.from_user.username or str(callback.from_user.id))}</code>\n"
                            f"Số tiền: <b>{money_vnd(total)}</b>\n"
                            f"Giao tài khoản: <b>{html_escape(assign_msg)}</b>"
                        ),
                    )
                except Exception:
                    pass
        else:
            # Shouldn't happen, but refund wallet just in case
            await db.deposit_wallet(callback.from_user.id, total)
            await callback.message.answer(
                "❌ Có lỗi khi xử lý đơn. Tiền đã được hoàn vào ví.",
                reply_markup=main_menu_keyboard(),
            )
        
        await callback.answer("Thanh toán qua ví thành công!")

    @router.callback_query(F.data == "pay:bank")
    async def pay_bank(callback: CallbackQuery):
        pending = pending_orders.get(callback.from_user.id)
        if not pending:
            await callback.answer("Không tìm thấy đơn đang chờ. Vui lòng chọn sản phẩm lại.", show_alert=True)
            return

        product = pending["product"]
        qty = int(pending["qty"])
        latest_product = await db.get_product(product["id"])
        if not latest_product or qty > int(latest_product["stock"]):
            await callback.answer("Sản phẩm không đủ tồn kho.", show_alert=True)
            return
        account_counts = await db.get_product_account_counts(latest_product["id"])
        if account_counts["total"] > 0 and qty > account_counts["available"]:
            await callback.answer("Sản phẩm không đủ tài khoản trong kho.", show_alert=True)
            return

        total = int(latest_product["price"]) * qty
        order_code = make_order_code()
        item = {
            "id": latest_product["id"],
            "name": latest_product["name"],
            "price": int(latest_product["price"]),
            "qty": qty,
            "delivery_text": latest_product.get("delivery_text", ""),
        }
        await db.create_order(
            order_code=order_code,
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            items=[item],
            total=total,
            expires_in_minutes=settings.order_expire_minutes,
        )

        try:
            payment_info = sepay.build_payment_info(order_code=order_code, amount=total)
        except SePayError as exc:
            await callback.message.answer(
                "❌ Không tạo được QR thanh toán. Kiểm tra SEPAY_BANK_CODE và SEPAY_ACCOUNT_NO trong .env.\n"
                f"Lỗi: <code>{html_escape(str(exc))}</code>"
            )
            await callback.answer()
            return

        await db.attach_payment_link(
            order_code=order_code,
            payment_link_id=payment_info.payment_code,
            checkout_url=payment_info.payment_page_url,
            qr_code=payment_info.qr_url,
        )
        pending_orders.pop(callback.from_user.id, None)

        caption = (
            f"🏦 Chuyển khoản tới <b>{html_escape(settings.sepay_bank_code)}</b> - "
            f"<code>{html_escape(settings.sepay_account_no)}</code> theo hướng dẫn dưới đây:\n\n"
            f"🔑 Mã đơn hàng (ghi chú chuyển khoản): <code>{payment_info.payment_code}</code>\n"
            "⏳ Vui lòng thanh toán trong 5 phút.\n\n"
            f"💰 Vui lòng chuyển khoản <b>{money_vnd(total)}</b>.\n"
            f"👤 Chủ tài khoản: <b>{html_escape(settings.sepay_account_name) or 'Chưa cấu hình'}</b>\n\n"
            "✅ Sau khi chuyển thành công, bot sẽ tự động xác nhận và gửi tài khoản."
        )
        await callback.message.answer_photo(
            photo=payment_info.qr_url,
            caption=caption,
            reply_markup=payment_keyboard(order_code),
        )
        await callback.message.answer("🕘 Sau khi chuyển khoản thành công, bot sẽ tự động xác nhận và gửi tài khoản.")
        await callback.answer("Đã tạo QR thanh toán.")

    @router.callback_query(F.data.in_({"language"}))
    async def menu_placeholder(callback: CallbackQuery):
        await callback.message.answer(
            "🌐 <b>Ngôn ngữ</b>\n\n"
            "Hiện bot đang hỗ trợ <b>Tiếng Việt</b>.\n"
            "Các ngôn ngữ khác sẽ được cập nhật sau."
        )
        await callback.answer()

    @router.callback_query(F.data == "profile")
    async def profile_callback(callback: CallbackQuery):
        profile = await db.get_or_create_profile(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        stats = await db.get_user_stats(callback.from_user.id)
        name = callback.from_user.first_name or ""
        username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"
        
        await callback.message.answer(
            f"👤 <b>Hồ sơ của bạn</b>\n\n"
            f"📛 Tên: <b>{html_escape(name)}</b>\n"
            f"🆔 Username: <b>{html_escape(username)}</b>\n"
            f"🔑 User ID: <code>{callback.from_user.id}</code>\n"
            f"👛 Số dư ví: <b>{money_vnd(int(profile['wallet_balance']))}</b>\n\n"
            f"📊 <b>Thống kê mua hàng</b>\n"
            f"• Tổng đơn: <b>{stats['total_orders']}</b>\n"
            f"• Đơn đã thanh toán: <b>{stats['paid_orders']}</b>\n"
            f"• Tổng chi tiêu: <b>{money_vnd(stats['total_spent'])}</b>\n\n"
            f"📅 Tham gia từ: <code>{html_escape(str(profile.get('first_seen', 'N/A')))}</code>",
            reply_markup=profile_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "wallet")
    async def wallet_callback(callback: CallbackQuery):
        balance = await db.get_wallet_balance(callback.from_user.id)
        await callback.message.answer(
            f"👛 <b>Ví của bạn</b>\n\n"
            f"💰 Số dư hiện tại: <b>{money_vnd(balance)}</b>\n\n"
            f"Bạn có thể nạp tiền vào ví để thanh toán nhanh hơn.",
            reply_markup=wallet_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "wallet:deposit")
    async def wallet_deposit_info(callback: CallbackQuery):
        await callback.message.answer(
            f"💰 <b>Nạp tiền vào ví</b>\n\n"
            f"Để nạp tiền vào ví, vui lòng liên hệ Admin:\n"
            f"👤 <b>@{SUPPORT_USERNAME}</b>\n\n"
            f"Gửi tin nhắn kèm số tiền muốn nạp, Admin sẽ xác nhận và cộng vào ví cho bạn.",
            reply_markup=support_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "wallet:history")
    async def wallet_history(callback: CallbackQuery):
        orders = await db.list_user_orders(callback.from_user.id, limit=10)
        paid_orders = [o for o in orders if o["status"] == "paid"]
        balance = await db.get_wallet_balance(callback.from_user.id)
        if not paid_orders:
            await callback.message.answer(
                f"📋 <b>Lịch sử giao dịch</b>\n\n"
                f"Chưa có giao dịch nào.\n"
                f"Số dư hiện tại: <b>{money_vnd(balance)}</b>",
                reply_markup=wallet_keyboard(),
            )
            await callback.answer()
            return
        lines = [
            f"📋 <b>Lịch sử giao dịch</b>",
            f"Số dư hiện tại: <b>{money_vnd(balance)}</b>",
            "",
        ]
        for order in paid_orders:
            lines.append(
                f"• <code>{order['order_code']}</code> | -{money_vnd(int(order['total']))} | {html_escape(str(order.get('paid_at', '')))}"
            )
        await callback.message.answer("\n".join(lines), reply_markup=wallet_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "support")
    async def support_callback(callback: CallbackQuery):
        await callback.message.answer(
            f"💬 <b>Hỗ trợ</b>\n\n"
            f"Nếu bạn cần hỗ trợ về đơn hàng, sản phẩm hoặc bất kỳ vấn đề gì, "
            f"vui lòng liên hệ Admin qua Telegram:\n\n"
            f"👤 Admin: <b>@{SUPPORT_USERNAME}</b>\n\n"
            f"Hoặc nhấn nút bên dưới để nhắn tin trực tiếp:",
            reply_markup=support_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "api")
    async def api_callback(callback: CallbackQuery):
        await callback.message.answer(
            "🔗 <b>Liên kết API</b>\n\n"
            f"Tính năng API giúp bạn tích hợp mua hàng tự động.\n"
            f"Liên hệ Admin @{SUPPORT_USERNAME} để được cấp API key.\n\n"
            f"📖 Các endpoint hỗ trợ:\n"
            f"• <code>GET /api/products</code> - Danh sách sản phẩm\n"
            f"• <code>POST /api/order</code> - Tạo đơn hàng\n"
            f"• <code>GET /api/order/{{code}}</code> - Kiểm tra đơn",
            reply_markup=support_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "myorders")
    async def my_orders_callback(callback: CallbackQuery):
        await send_my_orders(callback.message, callback.from_user.id)
        await callback.answer()

    @router.callback_query(F.data.startswith("orderdetail:"))
    async def order_detail_user(callback: CallbackQuery):
        order_code = int(callback.data.split(":", 1)[1])
        order = await db.get_user_order_detail(order_code, callback.from_user.id)
        if not order:
            await callback.answer("Không tìm thấy đơn hàng.", show_alert=True)
            return
        await callback.message.answer(
            render_order_detail(order),
            reply_markup=order_detail_keyboard(order_code),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("order:"))
    async def check_order(callback: CallbackQuery):
        order_code = int(callback.data.split(":", 1)[1])
        order = await db.get_user_order_detail(order_code, callback.from_user.id)
        if not order:
            await callback.answer("Không tìm thấy đơn.", show_alert=True)
            return
        await callback.message.answer(
            render_order_detail(order),
            reply_markup=order_detail_keyboard(order_code),
        )
        await callback.answer()

    @router.message(Command("myorders"))
    async def my_orders(message: Message):
        await send_my_orders(message, message.from_user.id)

    async def send_my_orders(message: Message, user_id: int):
        orders = await db.list_user_orders(user_id, limit=10)
        if not orders:
            await message.answer(
                "🧿 <b>Lịch sử mua hàng</b>\n\nBạn chưa có đơn hàng nào.",
                reply_markup=main_menu_keyboard(),
            )
            return
        await message.answer(
            "🧿 <b>Lịch sử mua gần đây</b>\nNhấn vào đơn để xem chi tiết:",
            reply_markup=my_orders_keyboard(orders),
        )

    @router.message(Command("cart"))
    async def cart_command(message: Message):
        cart_items = await db.get_cart(message.from_user.id)
        await message.answer(render_cart(cart_items))

    @router.message(Command("admin_orders"))
    async def admin_orders(message: Message):
        if message.from_user.id not in settings.admin_ids:
            await message.answer("Bạn không có quyền dùng lệnh này.")
            return
        orders = await db.list_orders(limit=20)
        if not orders:
            await message.answer("Chưa có đơn hàng nào.")
            return
        lines = ["🧾 <b>20 đơn gần nhất</b>", ""]
        for order in orders:
            username = order.get("username") or order.get("user_id")
            lines.append(
                f"• <code>{order['order_code']}</code> | {html_escape(str(username))} | "
                f"{money_vnd(int(order['total']))} | <b>{order['status']}</b>"
            )
        await message.answer("\n".join(lines))

    dp.include_router(router)
