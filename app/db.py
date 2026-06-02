from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.path = settings.database_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    price INTEGER NOT NULL CHECK(price >= 0),
                    stock INTEGER NOT NULL CHECK(stock >= 0),
                    description TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    delivery_text TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )

            columns = await db.execute_fetchall("PRAGMA table_info(products)")
            column_names = {row[1] for row in columns}
            if "image_url" not in column_names:
                await db.execute("ALTER TABLE products ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS carts (
                    user_id INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    qty INTEGER NOT NULL CHECK(qty > 0),
                    PRIMARY KEY (user_id, product_id),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_code INTEGER UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    items_json TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payment_link_id TEXT,
                    checkout_url TEXT,
                    qr_code TEXT,
                    qr_message_id INTEGER,
                    payment_reference TEXT,
                    created_at TEXT NOT NULL,
                    paid_at TEXT
                )
                """
            )
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN qr_message_id INTEGER")
            except Exception:
                pass


            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_code INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    price INTEGER NOT NULL CHECK(price >= 0),
                    qty INTEGER NOT NULL CHECK(qty > 0),
                    delivery_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(order_code, product_id),
                    FOREIGN KEY (order_code) REFERENCES orders(order_code)
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_transactions (
                    reference TEXT PRIMARY KEY,
                    order_code INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS product_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    account_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    order_code INTEGER,
                    created_at TEXT NOT NULL,
                    sold_at TEXT,
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    FOREIGN KEY (order_code) REFERENCES orders(order_code)
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS order_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_code INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    account_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (order_code) REFERENCES orders(order_code),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
                """
            )

            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_payment_link_id ON orders(payment_link_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order_code ON order_items(order_code)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_product_accounts_product_status ON product_accounts(product_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_product_accounts_order_code ON product_accounts(order_code)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_order_accounts_order_code ON order_accounts(order_code)")

            # User profiles table for wallet and profile info
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    wallet_balance INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
                """
            )

            # API keys table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    api_key TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(api_key)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id)")

            await self._backfill_order_items(db)

            await db.commit()

    async def _backfill_order_items(self, db: aiosqlite.Connection) -> None:
        rows = await db.execute_fetchall(
            """
            SELECT order_code, items_json, created_at
            FROM orders
            WHERE order_code NOT IN (SELECT DISTINCT order_code FROM order_items)
            """
        )
        for order_code, items_json, created_at in rows:
            try:
                items = json.loads(items_json)
            except json.JSONDecodeError:
                continue
            for item in items:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO order_items
                    (order_code, product_id, product_name, price, qty, delivery_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(order_code),
                        str(item.get("id", "")),
                        str(item.get("name", "")),
                        int(item.get("price", 0)),
                        int(item.get("qty", 1)),
                        str(item.get("delivery_text", "")),
                        str(created_at),
                    ),
                )

    async def seed_products_from_json(self, file_path: str = "data/products.json") -> None:
        path = Path(file_path)
        if not path.exists():
            return

        products: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        async with aiosqlite.connect(self.path) as db:
            for product in products:
                await db.execute(
                    """
                    INSERT INTO products (id, name, price, stock, description, image_url, delivery_text, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        price = excluded.price,
                        description = excluded.description,
                        image_url = excluded.image_url,
                        delivery_text = excluded.delivery_text,
                        active = 1
                    """,
                    (
                        product["id"],
                        product["name"],
                        int(product["price"]),
                        int(product.get("stock", 0)),
                        product.get("description", ""),
                        product.get("image_url", ""),
                        product.get("delivery_text", ""),
                    ),
                )
            await db.commit()

    async def list_products(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall("SELECT * FROM products WHERE active = 1 ORDER BY id ASC")
            return [dict(row) for row in rows]

    async def get_product(self, product_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM products WHERE id = ? AND active = 1",
                (product_id,),
            )
            return dict(rows[0]) if rows else None

    async def add_to_cart(self, user_id: int, product_id: str, qty_delta: int = 1) -> tuple[bool, str]:
        product = await self.get_product(product_id)
        if not product:
            return False, "Sản phẩm không tồn tại."

        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT qty FROM carts WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            )
            current_qty = int(rows[0]["qty"]) if rows else 0
            new_qty = current_qty + qty_delta

            if new_qty <= 0:
                await db.execute(
                    "DELETE FROM carts WHERE user_id = ? AND product_id = ?",
                    (user_id, product_id),
                )
                await db.commit()
                return True, "Đã cập nhật giỏ hàng."

            if new_qty > int(product["stock"]):
                return False, "Không đủ hàng trong kho."

            await db.execute(
                """
                INSERT INTO carts (user_id, product_id, qty)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, product_id) DO UPDATE SET qty = excluded.qty
                """,
                (user_id, product_id, new_qty),
            )
            await db.commit()
            return True, "Đã cập nhật giỏ hàng."

    async def get_cart(self, user_id: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT p.id, p.name, p.price, p.stock, p.description, p.delivery_text, c.qty
                FROM carts c
                JOIN products p ON p.id = c.product_id
                WHERE c.user_id = ? AND p.active = 1
                ORDER BY p.name ASC
                """,
                (user_id,),
            )
            return [dict(row) for row in rows]

    async def clear_cart(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM carts WHERE user_id = ?", (user_id,))
            await db.commit()

    async def create_order(
        self,
        *,
        order_code: int,
        user_id: int,
        username: str | None,
        items: list[dict[str, Any]],
        total: int,
    ) -> int:
        compact_items = [
            {
                "id": item["id"],
                "name": item["name"],
                "price": int(item["price"]),
                "qty": int(item["qty"]),
                "delivery_text": item.get("delivery_text", ""),
            }
            for item in items
        ]
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO orders
                (order_code, user_id, username, items_json, total, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    order_code,
                    user_id,
                    username,
                    json.dumps(compact_items, ensure_ascii=False),
                    total,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            created_at = datetime.now().isoformat(timespec="seconds")
            for item in compact_items:
                await db.execute(
                    """
                    INSERT INTO order_items
                    (order_code, product_id, product_name, price, qty, delivery_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_code,
                        item["id"],
                        item["name"],
                        int(item["price"]),
                        int(item["qty"]),
                        item.get("delivery_text", ""),
                        created_at,
                    ),
                )
            await db.commit()
            return int(cur.lastrowid)

    async def attach_payment_link(
        self,
        *,
        order_code: int,
        payment_link_id: str | None,
        checkout_url: str,
        qr_code: str | None,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE orders
                SET payment_link_id = ?, checkout_url = ?, qr_code = ?
                WHERE order_code = ?
                """,
                (payment_link_id, checkout_url, qr_code, order_code),
            )
            await db.commit()

    async def get_order_by_code(self, order_code: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM orders WHERE order_code = ?",
                (order_code,),
            )
            if not rows:
                return None
            order = dict(rows[0])
            order["items"] = await self._list_order_items(db, order_code)
            if not order["items"]:
                order["items"] = json.loads(order["items_json"])
            order["accounts"] = await self._list_order_accounts(db, order_code)
            return order


    async def get_order_by_payment_code(self, payment_code: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT * FROM orders
                WHERE payment_link_id = ?
                ORDER BY
                    CASE WHEN status = 'pending' THEN 0 ELSE 1 END,
                    id DESC
                LIMIT 1
                """,
                (payment_code,),
            )
            if not rows:
                return None
            order = dict(rows[0])
            order["items"] = await self._list_order_items(db, int(order["order_code"]))
            if not order["items"]:
                order["items"] = json.loads(order["items_json"])
            order["accounts"] = await self._list_order_accounts(db, int(order["order_code"]))
            return order

    async def _list_order_items(self, db: aiosqlite.Connection, order_code: int) -> list[dict[str, Any]]:
        rows = await db.execute_fetchall(
            """
            SELECT
                product_id AS id,
                product_name AS name,
                price,
                qty,
                delivery_text
            FROM order_items
            WHERE order_code = ?
            ORDER BY id ASC
            """,
            (order_code,),
        )
        return [dict(row) for row in rows]

    async def _list_order_accounts(self, db: aiosqlite.Connection, order_code: int) -> list[dict[str, Any]]:
        rows = await db.execute_fetchall(
            """
            SELECT product_id, account_text
            FROM order_accounts
            WHERE order_code = ?
            ORDER BY id ASC
            """,
            (order_code,),
        )
        return [dict(row) for row in rows]

    async def mark_order_paid(
        self,
        *,
        order_code: int,
        amount: int,
        reference: str,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Idempotent: webhook gọi trùng sẽ không nhả đơn lần 2."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")

            existing = await db.execute_fetchall(
                "SELECT reference FROM processed_transactions WHERE reference = ?",
                (reference,),
            )
            if existing:
                await db.commit()
                return False, "Giao dịch đã xử lý trước đó.", None

            rows = await db.execute_fetchall(
                "SELECT * FROM orders WHERE order_code = ?",
                (order_code,),
            )
            if not rows:
                await db.rollback()
                return False, "Không tìm thấy đơn hàng.", None

            order = dict(rows[0])
            if order["status"] == "paid":
                await db.execute(
                    """
                    INSERT OR IGNORE INTO processed_transactions(reference, order_code, amount, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (reference, order_code, amount, datetime.now().isoformat(timespec="seconds")),
                )
                await db.commit()
                return False, "Đơn đã paid từ trước.", None

            if order["status"] != "pending":
                await db.rollback()
                return False, f"Đơn không ở trạng thái pending: {order['status']}", None

            order_total = int(order["total"])
            paid_amount = int(amount)
            # Cho phép chênh lệch nhỏ do phí ngân hàng (tối đa 1% hoặc 1000đ, lấy giá trị lớn hơn)
            tolerance = max(int(order_total * 0.01), 1000)
            if abs(order_total - paid_amount) > tolerance:
                await db.rollback()
                return False, f"Số tiền không khớp: đơn={order_total}, nhận={paid_amount}.", None

            items = json.loads(order["items_json"])
            for item in items:
                product_rows = await db.execute_fetchall(
                    "SELECT stock FROM products WHERE id = ?",
                    (item["id"],),
                )
                if not product_rows or int(product_rows[0]["stock"]) < int(item["qty"]):
                    await db.rollback()
                    return False, f"Sản phẩm {item['name']} không đủ tồn kho.", None

            for item in items:
                await db.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (int(item["qty"]), item["id"]),
                )

            await db.execute(
                """
                UPDATE orders
                SET status = 'paid', paid_at = ?, payment_reference = ?
                WHERE order_code = ?
                """,
                (datetime.now().isoformat(timespec="seconds"), reference, order_code),
            )
            await db.execute(
                """
                INSERT INTO processed_transactions(reference, order_code, amount, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (reference, order_code, amount, datetime.now().isoformat(timespec="seconds")),
            )
            await db.commit()

            order["items"] = items
            order["status"] = "paid"
            order["payment_reference"] = reference
            return True, "Đã xác nhận thanh toán.", order

    async def list_user_orders(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT * FROM orders
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            return [dict(row) for row in rows]

    async def list_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM orders ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in rows]

    async def get_order_stats(self) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            total_orders = await db.execute_fetchall("SELECT COUNT(*) AS value FROM orders")
            pending_orders = await db.execute_fetchall(
                "SELECT COUNT(*) AS value FROM orders WHERE status = 'pending'"
            )
            paid_orders = await db.execute_fetchall(
                "SELECT COUNT(*) AS value FROM orders WHERE status = 'paid'"
            )
            revenue = await db.execute_fetchall(
                "SELECT COALESCE(SUM(total), 0) AS value FROM orders WHERE status = 'paid'"
            )
            products = await db.execute_fetchall(
                "SELECT COUNT(*) AS value FROM products WHERE active = 1"
            )
            return {
                "total_orders": int(total_orders[0]["value"]),
                "pending_orders": int(pending_orders[0]["value"]),
                "paid_orders": int(paid_orders[0]["value"]),
                "revenue": int(revenue[0]["value"]),
                "products": int(products[0]["value"]),
            }

    async def add_product_accounts(self, product_id: str, account_texts: list[str]) -> tuple[int, str]:
        product = await self.get_product(product_id)
        if not product:
            return 0, "Sản phẩm không tồn tại."

        cleaned = [text.strip() for text in account_texts if text.strip()]
        if not cleaned:
            return 0, "Không có tài khoản hợp lệ để thêm."

        now = datetime.now().isoformat(timespec="seconds")
        async with aiosqlite.connect(self.path) as db:
            for account_text in cleaned:
                await db.execute(
                    """
                    INSERT INTO product_accounts(product_id, account_text, status, created_at)
                    VALUES (?, ?, 'available', ?)
                    """,
                    (product_id, account_text, now),
                )
            await db.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (len(cleaned), product_id),
            )
            await db.commit()
        return len(cleaned), "Đã thêm tài khoản vào kho."

    async def get_product_account_counts(self, product_id: str) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END), 0) AS available,
                    COALESCE(SUM(CASE WHEN status = 'sold' THEN 1 ELSE 0 END), 0) AS sold
                FROM product_accounts
                WHERE product_id = ?
                """,
                (product_id,),
            )
            row = rows[0]
            return {
                "total": int(row["total"]),
                "available": int(row["available"]),
                "sold": int(row["sold"]),
            }

    async def get_account_inventory(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT
                    p.id,
                    p.name,
                    p.stock,
                    COALESCE(SUM(CASE WHEN a.status = 'available' THEN 1 ELSE 0 END), 0) AS available_accounts,
                    COALESCE(SUM(CASE WHEN a.status = 'sold' THEN 1 ELSE 0 END), 0) AS sold_accounts,
                    COUNT(a.id) AS total_accounts
                FROM products p
                LEFT JOIN product_accounts a ON a.product_id = p.id
                WHERE p.active = 1
                GROUP BY p.id, p.name, p.stock
                ORDER BY p.id ASC
                """
            )
            return [dict(row) for row in rows]

    async def assign_accounts_to_order(self, order_code: int) -> tuple[bool, str, dict[str, Any] | None]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            order_rows = await db.execute_fetchall(
                "SELECT * FROM orders WHERE order_code = ?",
                (order_code,),
            )
            if not order_rows:
                return False, "Không tìm thấy đơn hàng.", None

            order = dict(order_rows[0])
            if order["status"] != "paid":
                return False, "Đơn hàng chưa thanh toán.", None

            existing_accounts = await db.execute_fetchall(
                "SELECT id FROM order_accounts WHERE order_code = ? LIMIT 1",
                (order_code,),
            )
            if existing_accounts:
                order["items"] = await self._list_order_items(db, order_code)
                order["accounts"] = await self._list_order_accounts(db, order_code)
                return True, "Đơn đã có tài khoản.", order

            items = await self._list_order_items(db, order_code)
            if not items:
                items = json.loads(order["items_json"])

            now = datetime.now().isoformat(timespec="seconds")
            for item in items:
                counts = await db.execute_fetchall(
                    "SELECT COUNT(*) AS count FROM product_accounts WHERE product_id = ?",
                    (item["id"],),
                )
                if int(counts[0]["count"]) == 0:
                    continue

                account_rows = await db.execute_fetchall(
                    """
                    SELECT id, account_text
                    FROM product_accounts
                    WHERE product_id = ? AND status = 'available'
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (item["id"], int(item["qty"])),
                )
                if len(account_rows) < int(item["qty"]):
                    return False, f"Sản phẩm {item['name']} không đủ tài khoản trong kho.", None

                account_ids = [int(row["id"]) for row in account_rows]
                account_texts = [str(row["account_text"]) for row in account_rows]
                for account_text in account_texts:
                    await db.execute(
                        """
                        INSERT INTO order_accounts(order_code, product_id, account_text, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (order_code, item["id"], account_text, now),
                    )
                placeholders = ",".join("?" for _ in account_ids)
                await db.execute(
                    f"""
                    UPDATE product_accounts
                    SET status = 'sold', order_code = ?, sold_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    (order_code, now, *account_ids),
                )
                await db.execute(
                    """
                    UPDATE order_items
                    SET delivery_text = ?
                    WHERE order_code = ? AND product_id = ?
                    """,
                    ("\n".join(account_texts), order_code, item["id"]),
                )

            await db.commit()
            order["items"] = await self._list_order_items(db, order_code)
            order["accounts"] = await self._list_order_accounts(db, order_code)
            return True, "Đã gắn tài khoản vào đơn.", order

    async def get_all_products(self) -> list[dict[str, Any]]:
        """Get all products including hidden ones (for admin)."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall("SELECT * FROM products ORDER BY id ASC")
            return [dict(row) for row in rows]

    async def toggle_product_active(self, product_id: str) -> tuple[bool, str, dict[str, Any] | None]:
        """Toggle product visibility (active/hidden)."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            )
            if not rows:
                return False, "Sản phẩm không tồn tại.", None
            
            product = dict(rows[0])
            new_active = 1 - int(product["active"])
            
            await db.execute(
                "UPDATE products SET active = ? WHERE id = ?",
                (new_active, product_id),
            )
            await db.commit()
            
            product["active"] = new_active
            status = "Đã hiển thị" if new_active else "Đã ẩn"
            return True, status, product

    async def delete_product(self, product_id: str) -> tuple[bool, str]:
        """Permanently delete a product and its accounts."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            )
            if not rows:
                return False, "Sản phẩm không tồn tại."

            product_name = dict(rows[0])["name"]
            await db.execute("DELETE FROM product_accounts WHERE product_id = ?", (product_id,))
            await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
            await db.commit()
            return True, f"Đã xóa sản phẩm '{product_name}' và tất cả tài khoản liên quan."

    async def add_product(
        self,
        *,
        product_id: str,
        name: str,
        price: int,
        stock: int,
        description: str = "",
        image_url: str = "",
        delivery_text: str = "",
    ) -> tuple[bool, str]:
        """Add a new product."""
        async with aiosqlite.connect(self.path) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO products (id, name, price, stock, description, image_url, delivery_text, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (product_id, name, price, stock, description, image_url, delivery_text),
                )
                await db.commit()
                return True, f"Đã thêm sản phẩm: {name}"
            except Exception as e:
                return False, f"Lỗi: {str(e)}"

    async def get_all_customers(self) -> set[int]:
        """Get all user IDs who have made orders."""
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall(
                "SELECT DISTINCT user_id FROM orders WHERE user_id IS NOT NULL"
            )
            return {int(row[0]) for row in rows}

    async def get_customers_detailed(self) -> list[dict[str, Any]]:
        """Get all customers with order count and total spent."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT 
                    user_id,
                    username,
                    COUNT(*) as order_count,
                    COALESCE(SUM(total), 0) as total_spent
                FROM orders
                WHERE user_id IS NOT NULL
                GROUP BY user_id, username
                ORDER BY total_spent DESC
                """
            )
            return [dict(row) for row in rows]

    # ─── User profile & wallet ───────────────────────────────

    async def get_or_create_profile(
        self, user_id: int, username: str | None = None, first_name: str | None = None
    ) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                INSERT INTO user_profiles (user_id, username, first_name, wallet_balance, first_seen, last_seen)
                VALUES (?, ?, ?, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, user_profiles.username),
                    first_name = COALESCE(excluded.first_name, user_profiles.first_name),
                    last_seen = excluded.last_seen
                """,
                (user_id, username, first_name, now, now),
            )
            await db.commit()
            rows = await db.execute_fetchall(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            )
            return dict(rows[0])

    async def get_user_profile(self, user_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            )
            return dict(rows[0]) if rows else None

    async def get_wallet_balance(self, user_id: int) -> int:
        profile = await self.get_user_profile(user_id)
        return int(profile["wallet_balance"]) if profile else 0

    async def deposit_wallet(self, user_id: int, amount: int) -> int:
        """Add balance. Returns new balance."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                "UPDATE user_profiles SET wallet_balance = wallet_balance + ? WHERE user_id = ?",
                (amount, user_id),
            )
            await db.commit()
            rows = await db.execute_fetchall(
                "SELECT wallet_balance FROM user_profiles WHERE user_id = ?", (user_id,)
            )
            return int(rows[0]["wallet_balance"]) if rows else 0

    async def debit_wallet(self, user_id: int, amount: int) -> tuple[bool, int]:
        """Debit from wallet. Returns (success, new_balance)."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT wallet_balance FROM user_profiles WHERE user_id = ?", (user_id,)
            )
            if not rows:
                return False, 0
            balance = int(rows[0]["wallet_balance"])
            if balance < amount:
                return False, balance
            new_balance = balance - amount
            await db.execute(
                "UPDATE user_profiles SET wallet_balance = ? WHERE user_id = ?",
                (new_balance, user_id),
            )
            await db.commit()
            return True, new_balance

    async def get_user_order_detail(self, order_code: int, user_id: int) -> dict[str, Any] | None:
        """Get full order detail for the owning user, including delivered accounts."""
        order = await self.get_order_by_code(order_code)
        if not order or int(order["user_id"]) != user_id:
            return None
        return order

    async def get_user_stats(self, user_id: int) -> dict[str, Any]:
        """Get order stats for a user."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT
                    COUNT(*) as total_orders,
                    COALESCE(SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END), 0) as paid_orders,
                    COALESCE(SUM(CASE WHEN status = 'paid' THEN total ELSE 0 END), 0) as total_spent
                FROM orders
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = rows[0]
            return {
                "total_orders": int(row["total_orders"]),
                "paid_orders": int(row["paid_orders"]),
                "total_spent": int(row["total_spent"]),
            }

    # ─── API key management ─────────────────────────────────

    async def create_api_key(self, user_id: int) -> str:
        """Generate and store a new API key for a user. Deactivates old keys."""
        import secrets
        api_key = secrets.token_hex(32)  # 64 char hex key
        now = datetime.now().isoformat(timespec="seconds")
        async with aiosqlite.connect(self.path) as db:
            # Deactivate old keys
            await db.execute(
                "UPDATE api_keys SET is_active = 0 WHERE user_id = ?",
                (user_id,),
            )
            await db.execute(
                """
                INSERT INTO api_keys (user_id, api_key, created_at, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (user_id, api_key, now),
            )
            await db.commit()
        return api_key

    async def get_user_by_api_key(self, api_key: str) -> dict[str, Any] | None:
        """Look up user by API key. Returns profile + key info."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT k.user_id, k.api_key, k.created_at as key_created_at,
                       p.username, p.first_name, p.wallet_balance, p.first_seen
                FROM api_keys k
                LEFT JOIN user_profiles p ON p.user_id = k.user_id
                WHERE k.api_key = ? AND k.is_active = 1
                """,
                (api_key,),
            )
            if not rows:
                return None
            # Update last_used
            await db.execute(
                "UPDATE api_keys SET last_used = ? WHERE api_key = ?",
                (datetime.now().isoformat(timespec="seconds"), api_key),
            )
            await db.commit()
            return dict(rows[0])

    async def get_user_api_key(self, user_id: int) -> str | None:
        """Get active API key for a user."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT api_key FROM api_keys WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            return str(rows[0]["api_key"]) if rows else None

    async def list_user_orders_for_api(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Get user orders with items and delivered accounts for API response."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            order_rows = await db.execute_fetchall(
                """
                SELECT * FROM orders
                WHERE user_id = ? AND status = 'paid'
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            results = []
            for row in order_rows:
                order = dict(row)
                items = await self._list_order_items(db, int(order["order_code"]))
                accounts = await self._list_order_accounts(db, int(order["order_code"]))
                account_texts = [a["account_text"] for a in accounts]
                for item in items:
                    results.append({
                        "id": int(order["order_code"]),
                        "product": item["name"],
                        "items": account_texts if account_texts else [item.get("delivery_text", "")],
                        "price": int(item["price"]) * int(item["qty"]),
                        "quantity": int(item["qty"]),
                        "created_at": order.get("created_at", ""),
                    })
            return results
