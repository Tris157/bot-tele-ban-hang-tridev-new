from __future__ import annotations

import random
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
    confirm_order_keyboard,
    main_menu_keyboard,
    payment_keyboard,
    product_keyboard,
    shop_keyboard,
    start_keyboard,
)
from app.sepay_client import SePayClient, SePayError
from app.utils import html_escape, money_vnd


router = Router()
pending_products: dict[int, str] = {}
pending_orders: dict[int, dict[str, Any]] = {}
pending_admin_add_accounts: dict[int, str] = {}


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


def render_product_text(product: dict[str, Any]) -> str:
    return (
        f"📧 <b>{html_escape(product['name'])}</b>\n"
        f"💵 Giá: <b>{money_vnd(int(product['price']))}</b>\n"
        f"➕ Tồn kho: <b>{product['stock']} tài khoản</b>\n"
        f"📊 Đã bán: <b>{random.randint(12, 98)} tài khoản</b>\n\n"
        "💬 <b>Mô tả:</b>\n"
        f"{html_escape(product.get('description'))}"
    )


def render_order_confirm(product: dict[str, Any], qty: int) -> str:
    total = int(product["price"]) * qty
    return (
        "🧾 <b>Xác nhận đơn hàng</b>\n"
        f"Sản phẩm: <b>{html_escape(product['name'])}</b>\n"
        f"Số lượng: <b>{qty}</b>\n"
        f"Thành tiền: <b>{money_vnd(int(product['price']))}</b>\n"
        f"💵 Tổng thanh toán: <b>{money_vnd(total)}</b>\n"
        "👛 Số dư ví hiện tại: <b>0k</b>\n\n"
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


async def send_product(message: Message, product: dict[str, Any]) -> None:
    text = render_product_text(product)
    markup = product_keyboard(product["id"])
    image_url = (product.get("image_url") or "").strip()
    if image_url:
        try:
            await message.answer_photo(photo=image_url, caption=text, reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=markup)


def register_handlers(dp: Dispatcher, db: Database, sepay: SePayClient, settings: Settings) -> None:
    @router.message(Command("start"))
    async def start(message: Message):
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
            "💬 <b>Hỗ trợ</b>\n"
            "Bạn nhắn trực tiếp yêu cầu cần hỗ trợ tại đây. Admin sẽ kiểm tra đơn và phản hồi.",
            reply_markup=main_menu_keyboard(),
        )

    @router.message(F.text == "👛 Ví")
    async def wallet_text(message: Message):
        await message.answer("👛 <b>Ví của bạn</b>\nSố dư hiện tại: <b>0k</b>")

    @router.message(F.text == "🔗 API")
    async def api_text(message: Message):
        await message.answer("🔗 <b>API</b>\nTính năng liên kết API sẽ được shop cấu hình sau.")

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
        await send_product(callback.message, product)
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
        await message.answer(render_order_confirm(product, qty), reply_markup=confirm_order_keyboard())

    @router.callback_query(F.data == "pay:wallet")
    async def pay_wallet(callback: CallbackQuery):
        await callback.answer("Ví chưa đủ số dư. Vui lòng chọn Thanh toán ngay.", show_alert=True)

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

    @router.callback_query(F.data.in_({"profile", "wallet", "support", "api", "language"}))
    async def menu_placeholder(callback: CallbackQuery):
        labels = {
            "profile": "👤 Hồ sơ",
            "wallet": "👛 Ví của bạn\nSố dư hiện tại: <b>0k</b>",
            "support": "💬 Hỗ trợ\nBạn nhắn trực tiếp yêu cầu cần hỗ trợ tại đây.",
            "api": "🔗 API\nTính năng liên kết API sẽ được shop cấu hình sau.",
            "language": "🌐 Ngôn ngữ\nHiện bot đang dùng tiếng Việt.",
        }
        await callback.message.answer(labels[callback.data])
        await callback.answer()

    @router.callback_query(F.data == "myorders")
    async def my_orders_callback(callback: CallbackQuery):
        await send_my_orders(callback.message, callback.from_user.id)
        await callback.answer()

    @router.callback_query(F.data.startswith("order:"))
    async def check_order(callback: CallbackQuery):
        order_code = int(callback.data.split(":", 1)[1])
        order = await db.get_order_by_code(order_code)
        if not order or int(order["user_id"]) != callback.from_user.id:
            await callback.answer("Không tìm thấy đơn.", show_alert=True)
            return
        await callback.answer(f"Trạng thái đơn: {order['status']}", show_alert=True)

    @router.message(Command("myorders"))
    async def my_orders(message: Message):
        await send_my_orders(message, message.from_user.id)

    async def send_my_orders(message: Message, user_id: int):
        orders = await db.list_user_orders(user_id, limit=10)
        if not orders:
            await message.answer("Bạn chưa có đơn hàng nào.")
            return
        lines = ["🧿 <b>Lịch sử mua gần đây</b>", ""]
        for order in orders:
            lines.append(
                f"• <code>{order['order_code']}</code> | {money_vnd(int(order['total']))} | <b>{order['status']}</b>"
            )
        await message.answer("\n".join(lines))

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
