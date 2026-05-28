from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils import money_vnd


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Mua hàng"), KeyboardButton(text="🧿 Lịch sử mua")],
            [KeyboardButton(text="👛 Ví"), KeyboardButton(text="💬 Hỗ trợ")],
            [KeyboardButton(text="🔗 API"), KeyboardButton(text="🏠 Menu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Chọn menu nhanh bên dưới",
    )


def start_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Mua hàng", callback_data="shop")
    kb.button(text="👤 Hồ sơ", callback_data="profile")
    kb.button(text="🧿 Lịch sử mua", callback_data="myorders")
    kb.button(text="👛 Ví", callback_data="wallet")
    kb.button(text="💬 Hỗ trợ", callback_data="support")
    kb.button(text="🔗 Liên kết API", callback_data="api")
    kb.button(text="🌐 Ngôn ngữ", callback_data="language")
    kb.adjust(1, 2, 1, 1, 1)
    return kb.as_markup()


def shop_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.button(
            text=f"{product['name']} | {money_vnd(int(product['price']))} | 📦 {product['stock']}",
            callback_data=f"view:{product['id']}",
        )
    kb.button(text="🔄 Cập nhật sản phẩm", callback_data="shop")
    kb.adjust(1)
    return kb.as_markup()


def product_keyboard(product_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Mua sản phẩm này", callback_data=f"buy:{product_id}")
    kb.button(text="⬅️ Quay lại sản phẩm", callback_data="shop")
    kb.adjust(1)
    return kb.as_markup()


def confirm_order_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Thanh toán qua ví", callback_data="pay:wallet")
    kb.button(text="🏦 Thanh toán ngay", callback_data="pay:bank")
    kb.adjust(1)
    return kb.as_markup()


def payment_keyboard(order_code: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 Kiểm tra đơn", callback_data=f"order:{order_code}")
    kb.button(text="🛍 Về sản phẩm", callback_data="shop")
    kb.adjust(1)
    return kb.as_markup()


def admin_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Đơn mới nhất", callback_data="admin:orders")
    kb.button(text="📊 Thống kê", callback_data="admin:stats")
    kb.button(text="🛍 Sản phẩm", callback_data="admin:products")
    kb.button(text="🔐 Kho tài khoản", callback_data="admin:accounts")
    kb.button(text="➕ Nạp tài khoản", callback_data="admin:add_accounts")
    kb.button(text="➕ Thêm sản phẩm", callback_data="admin:add_product")
    kb.button(text="🔄 Quản lý sản phẩm", callback_data="admin:manage_products")
    kb.button(text="📢 Thông báo sản phẩm mới", callback_data="admin:notify_product")
    kb.button(text="📨 Thông báo riêng", callback_data="admin:notify_private")
    kb.adjust(1)
    return kb.as_markup()


def admin_product_picker_keyboard(products: list[dict], *, prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.button(
            text=f"{product['name']} | kho {product['stock']}",
            callback_data=f"{prefix}:{product['id']}",
        )
    kb.button(text="⬅️ Về admin", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_orders_keyboard(orders: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for order in orders:
        kb.button(
            text=f"#{order['order_code']} | {order['status']} | {money_vnd(int(order['total']))}",
            callback_data=f"admin:order:{order['order_code']}",
        )
    kb.button(text="⬅️ Về admin", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_manage_products_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for product in products:
        status = "👁" if product.get("active") else "🚫"
        kb.button(
            text=f"{status} {product['name']} | kho {product['stock']}",
            callback_data=f"admin:toggle_product:{product['id']}",
        )
    kb.button(text="⬅️ Về admin", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_notify_product_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for product in products:
        kb.button(
            text=f"📢 {product['name']} | {money_vnd(int(product['price']))}",
            callback_data=f"admin:notify:{product['id']}",
        )
    kb.button(text="⬅️ Về admin", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def admin_customers_keyboard(customers: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for customer in customers:
        username = customer.get("username") or str(customer["user_id"])
        kb.button(
            text=f"👤 {username} | {customer['order_count']} đơn | {money_vnd(customer['total_spent'])}",
            callback_data=f"admin:notify_private:{customer['user_id']}",
        )
    kb.button(text="⬅️ Về admin", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()
