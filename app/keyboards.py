from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.utils import money_vnd

SUPPORT_USERNAME = "tridev157"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Sản phẩm"), KeyboardButton(text="💬 Hỗ trợ")],
            [KeyboardButton(text="👛 Ví"), KeyboardButton(text="🔗 API")],
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


def product_keyboard(product_id: str, stock: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Mua sản phẩm này", callback_data=f"buy:{product_id}")
    # Quick-buy buttons for common quantities
    quick_qtys = [q for q in [1, 3, 5, 10] if q <= stock]
    for q in quick_qtys:
        kb.button(text=f"⚡ Mua {q}x", callback_data=f"quickbuy:{product_id}:{q}")
    kb.button(text="⬅️ Quay lại sản phẩm", callback_data="shop")
    kb.button(text="🏠 Menu chính", callback_data="mainmenu")
    # Layout: buy button full width, quick-buy in row, then back buttons in row
    if quick_qtys:
        kb.adjust(1, len(quick_qtys), 2)
    else:
        kb.adjust(1, 2)
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
    kb.button(text="🗑 Xóa sản phẩm", callback_data="admin:delete_product")
    kb.button(text="📢 Thông báo sản phẩm mới", callback_data="admin:notify_product")
    kb.button(text="📨 Thông báo riêng", callback_data="admin:notify_private")
    kb.button(text="💰 Nạp ví khách hàng", callback_data="admin:deposit_wallet")
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


def support_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💬 Nhắn tin cho Admin (@{SUPPORT_USERNAME})", url=f"https://t.me/{SUPPORT_USERNAME}")
    kb.button(text="🏠 Menu chính", callback_data="mainmenu")
    kb.adjust(1)
    return kb.as_markup()


def wallet_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Nạp tiền vào ví", callback_data="wallet:deposit")
    kb.button(text="📋 Lịch sử giao dịch", callback_data="wallet:history")
    kb.button(text="🏠 Menu chính", callback_data="mainmenu")
    kb.adjust(1)
    return kb.as_markup()


def profile_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧿 Lịch sử mua", callback_data="myorders")
    kb.button(text="👛 Ví", callback_data="wallet")
    kb.button(text="🏠 Menu chính", callback_data="mainmenu")
    kb.adjust(2, 1)
    return kb.as_markup()


def order_detail_keyboard(order_code: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧿 Lịch sử mua", callback_data="myorders")
    kb.button(text="🛍 Mua tiếp", callback_data="shop")
    kb.button(text="🏠 Menu chính", callback_data="mainmenu")
    kb.adjust(2, 1)
    return kb.as_markup()


def my_orders_keyboard(orders: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for order in orders:
        status_icon = "✅" if order["status"] == "paid" else "⏳"
        kb.button(
            text=f"{status_icon} #{order['order_code']} | {money_vnd(int(order['total']))} | {order['status']}",
            callback_data=f"orderdetail:{order['order_code']}",
        )
    kb.button(text="🛍 Mua tiếp", callback_data="shop")
    kb.button(text="🏠 Menu chính", callback_data="mainmenu")
    kb.adjust(1)
    return kb.as_markup()


def admin_wallet_customers_keyboard(customers: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for customer in customers:
        username = customer.get("username") or str(customer["user_id"])
        balance = customer.get("wallet_balance", 0)
        kb.button(
            text=f"👤 {username} | Ví: {money_vnd(balance)}",
            callback_data=f"admin:deposit_to:{customer['user_id']}",
        )
    kb.button(text="⬅️ Về admin", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()
