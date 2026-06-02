from __future__ import annotations

import json
import time
import random
from collections import defaultdict
from datetime import datetime
from typing import Any

from aiogram import Bot
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import Settings
from app.db import Database
from app.sepay_client import SePayClient
from app.utils import html_escape, money_vnd


# ─── Rate limiting ──────────────────────────────────────────

class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._auth_fails: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(self, key: str) -> bool:
        now = time.time()
        hits = self._hits[key]
        # Prune old entries
        self._hits[key] = [t for t in hits if now - t < self.window]
        if len(self._hits[key]) >= self.max_requests:
            return True
        self._hits[key].append(now)
        return False

    def record_auth_fail(self, key: str) -> bool:
        """Record auth failure. Returns True if should block."""
        now = time.time()
        fails = self._auth_fails[key]
        self._auth_fails[key] = [t for t in fails if now - t < self.window]
        self._auth_fails[key].append(now)
        return len(self._auth_fails[key]) >= 5


rate_limiter = RateLimiter()


# ─── Helpers ────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def make_api_order_code(user_id: int) -> int:
    return int(time.time() * 1000) + random.randint(100, 999)


# ─── API docs HTML ──────────────────────────────────────────

def _api_docs_html(base_url: str) -> str:
    return f"""
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Shop Bot API Documentation</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #0f0f23; color: #e0e0e0; line-height: 1.6; }}
    .container {{ max-width: 900px; margin: 0 auto; padding: 24px; }}
    h1 {{ color: #00d4ff; font-size: 28px; margin-bottom: 8px; }}
    h2 {{ color: #00d4ff; font-size: 20px; margin: 32px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #333; }}
    h3 {{ color: #ffd700; font-size: 16px; margin: 16px 0 8px; }}
    .subtitle {{ color: #888; margin-bottom: 24px; }}
    .endpoint {{ background: #1a1a2e; border: 1px solid #333; border-radius: 12px; padding: 16px; margin: 12px 0; }}
    .method {{ display: inline-block; padding: 2px 10px; border-radius: 6px; font-weight: 700; font-size: 13px; margin-right: 8px; }}
    .get {{ background: #1b5e20; color: #a5d6a7; }}
    .post {{ background: #e65100; color: #ffcc80; }}
    .url {{ font-family: 'Fira Code', monospace; color: #80cbc4; }}
    pre {{ background: #16213e; padding: 14px; border-radius: 8px; overflow-x: auto; font-size: 13px; margin: 8px 0; border: 1px solid #2a2a4a; }}
    code {{ font-family: 'Fira Code', 'Consolas', monospace; color: #a5d6a7; font-size: 13px; }}
    .warn {{ background: #4a1a1a; border: 1px solid #c62828; color: #ef9a9a; padding: 12px; border-radius: 8px; margin: 12px 0; }}
    .info {{ background: #1a3a4a; border: 1px solid #0277bd; color: #81d4fa; padding: 12px; border-radius: 8px; margin: 12px 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
    th, td {{ padding: 8px 12px; border: 1px solid #333; text-align: left; font-size: 14px; }}
    th {{ background: #1a1a2e; color: #00d4ff; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>\U0001f4d6 Shop Bot API Documentation</h1>
    <p class="subtitle">T\u00e0i li\u1ec7u h\u01b0\u1edbng d\u1eabn s\u1eed d\u1ee5ng API c\u1ee7a h\u1ec7 th\u1ed1ng Shop Bot.</p>

    <div class="info">\u2139\ufe0f Base URL: <code>{html_escape(base_url)}</code></div>

    <h2>\U0001f510 Authentication (X\u00e1c th\u1ef1c)</h2>
    <p>M\u1ecdi request \u0111\u1ec1u y\u00eau c\u1ea7u API Key trong header. L\u1ea5y key b\u1eb1ng l\u1ec7nh <code>/apikey</code> trong Telegram Bot.</p>
    <pre><code>X-API-Key: YOUR_API_KEY</code></pre>

    <h2>\U0001f7e2 1. L\u1ea5y th\u00f4ng tin t\u00e0i kho\u1ea3n</h2>
    <div class="endpoint">
      <span class="method get">GET</span> <span class="url">/api/balance</span>
      <pre><code>curl -H "X-API-Key: YOUR_API_KEY" {html_escape(base_url)}/api/balance</code></pre>
      <h3>Response (200 OK):</h3>
      <pre><code>{{
  "success": true,
  "user_id": 7874082485,
  "username": "tridev157",
  "balance_vnd": 500000
}}</code></pre>
    </div>

    <h2>\U0001f6d2 2. Danh s\u00e1ch s\u1ea3n ph\u1ea9m</h2>
    <div class="endpoint">
      <span class="method get">GET</span> <span class="url">/api/products</span>
      <pre><code>curl -H "X-API-Key: YOUR_API_KEY" {html_escape(base_url)}/api/products</code></pre>
      <h3>Response (200 OK):</h3>
      <pre><code>{{
  "success": true,
  "products": [
    {{
      "id": "gmail_2024",
      "name": "Gmail Account",
      "price_vnd": 50000,
      "stock": 100,
      "description": "T\u00e0i kho\u1ea3n Gmail m\u1edbi"
    }}
  ]
}}</code></pre>
    </div>

    <h2>\U0001f4b0 3. Mua s\u1ea3n ph\u1ea9m</h2>
    <div class="endpoint">
      <span class="method post">POST</span> <span class="url">/api/buy</span>
      <h3>Body Request:</h3>
      <pre><code>{{
  "product_id": "gmail_2024",
  "quantity": 1
}}</code></pre>
      <pre><code>curl -X POST \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"product_id": "gmail_2024", "quantity": 1}}' \\
  {html_escape(base_url)}/api/buy</code></pre>
      <h3>Response Success (200 OK):</h3>
      <pre><code>{{
  "success": true,
  "order": {{
    "order_code": 1717382912345,
    "product": "Gmail Account",
    "quantity": 1,
    "total_price": 50000
  }},
  "items": ["user1@gmail.com|pass123"],
  "new_balance": 450000
}}</code></pre>
    </div>

    <h2>\U0001f4dc 4. L\u1ecbch s\u1eed \u0111\u01a1n h\u00e0ng</h2>
    <div class="endpoint">
      <span class="method get">GET</span> <span class="url">/api/orders</span>
      <pre><code>curl -H "X-API-Key: YOUR_API_KEY" {html_escape(base_url)}/api/orders</code></pre>
      <h3>Response (200 OK):</h3>
      <pre><code>{{
  "success": true,
  "orders": [
    {{
      "id": 1717382912345,
      "product": "Gmail Account",
      "items": ["user1@gmail.com|pass123"],
      "price": 50000,
      "quantity": 1,
      "created_at": "2026-06-02T18:00:00"
    }}
  ]
}}</code></pre>
    </div>

    <h2>\U0001f3e6 5. T\u1ea1o y\u00eau c\u1ea7u n\u1ea1p ti\u1ec1n</h2>
    <div class="endpoint">
      <span class="method post">POST</span> <span class="url">/api/deposit</span>
      <h3>Body Request:</h3>
      <pre><code>{{"amount": 100000}}</code></pre>
      <pre><code>curl -X POST \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"amount": 100000}}' \\
  {html_escape(base_url)}/api/deposit</code></pre>
      <h3>Response (200 OK):</h3>
      <pre><code>{{
  "success": true,
  "deposit": {{
    "payment_code": "DH1717382912345",
    "amount_vnd": 100000,
    "bank": {{
      "bank_name": "MBBank",
      "account_number": "315072008",
      "account_name": "DOAN BA TRI",
      "transfer_content": "DH1717382912345"
    }},
    "qr_url": "https://qr.sepay.vn/img?...",
    "expires_in_minutes": 10
  }},
  "note": "Chuy\u1ec3n kho\u1ea3n \u0111\u00fang s\u1ed1 ti\u1ec1n v\u00e0 n\u1ed9i dung. Bot s\u1ebd t\u1ef1 \u0111\u1ed9ng c\u1ed9ng v\u00e0o v\u00ed."
}}</code></pre>
    </div>

    <h2>\U0001f6a8 Gi\u1edbi h\u1ea1n</h2>
    <div class="warn">
      \u26a0\ufe0f Rate Limit: T\u1ed1i \u0111a <b>100 requests / 60s</b> m\u1ed7i IP.<br>
      \u26a0\ufe0f Sai API Key 5 l\u1ea7n / 60s s\u1ebd b\u1ecb block t\u1ea1m th\u1eddi.<br>
      \u26a0\ufe0f S\u1ed1 l\u01b0\u1ee3ng mua t\u1ed1i \u0111a m\u1ed7i request: <b>100</b>.
    </div>
  </div>
</body>
</html>
"""


# ─── Router factory ─────────────────────────────────────────

def create_api_router(bot: Bot, db: Database, sepay: SePayClient, settings: Settings) -> APIRouter:
    api = APIRouter(prefix="/api", tags=["API"])

    async def _auth(request: Request) -> dict[str, Any] | JSONResponse:
        """Authenticate by X-API-Key header. Returns user dict or error response."""
        client_ip = get_client_ip(request)

        # Rate limit check
        if rate_limiter.is_rate_limited(client_ip):
            return JSONResponse(
                {"success": False, "error": "Rate limit exceeded. Max 100 requests/60s."},
                status_code=429,
            )

        api_key = (request.headers.get("x-api-key") or "").strip()
        if not api_key:
            return JSONResponse(
                {"success": False, "error": "Missing X-API-Key header."},
                status_code=401,
            )

        user = await db.get_user_by_api_key(api_key)
        if not user:
            if rate_limiter.record_auth_fail(client_ip):
                return JSONResponse(
                    {"success": False, "error": "Too many auth failures. Blocked temporarily."},
                    status_code=429,
                )
            return JSONResponse(
                {"success": False, "error": "Invalid API key."},
                status_code=401,
            )
        return user

    # ── Docs page ────────────────────────────────────────────

    @api.get("/docs", response_class=HTMLResponse)
    async def api_docs():
        return _api_docs_html(settings.public_base_url)

    # ── Balance ──────────────────────────────────────────────

    @api.get("/balance")
    async def api_balance(request: Request):
        user = await _auth(request)
        if isinstance(user, JSONResponse):
            return user

        balance = await db.get_wallet_balance(int(user["user_id"]))
        return {
            "success": True,
            "user_id": int(user["user_id"]),
            "username": user.get("username") or "",
            "balance_vnd": balance,
        }

    # ── Products ─────────────────────────────────────────────

    @api.get("/products")
    async def api_products(request: Request):
        user = await _auth(request)
        if isinstance(user, JSONResponse):
            return user

        products = await db.list_products()
        return {
            "success": True,
            "products": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "price_vnd": int(p["price"]),
                    "stock": int(p["stock"]),
                    "description": p.get("description", ""),
                }
                for p in products
            ],
        }

    # ── Buy ──────────────────────────────────────────────────

    @api.post("/buy")
    async def api_buy(request: Request):
        user = await _auth(request)
        if isinstance(user, JSONResponse):
            return user

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"success": False, "error": "Invalid JSON body."},
                status_code=400,
            )

        product_id = body.get("product_id")
        quantity = body.get("quantity", 1)

        if not product_id:
            return JSONResponse(
                {"success": False, "error": "Missing product_id."},
                status_code=400,
            )

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return JSONResponse(
                {"success": False, "error": "Invalid quantity."},
                status_code=400,
            )

        if quantity < 1 or quantity > 100:
            return JSONResponse(
                {"success": False, "error": "Quantity must be between 1 and 100."},
                status_code=400,
            )

        # Check product
        product = await db.get_product(str(product_id))
        if not product:
            return JSONResponse(
                {"success": False, "error": f"Product '{product_id}' not found."},
                status_code=404,
            )

        stock = int(product["stock"])
        if quantity > stock:
            return JSONResponse(
                {"success": False, "error": f"Not enough stock. Available: {stock}"},
                status_code=400,
            )

        # Check account inventory
        account_counts = await db.get_product_account_counts(str(product_id))
        if account_counts["total"] > 0 and quantity > account_counts["available"]:
            return JSONResponse(
                {"success": False, "error": f"Not enough accounts in stock. Available: {account_counts['available']}"},
                status_code=400,
            )

        total = int(product["price"]) * quantity
        user_id = int(user["user_id"])
        balance = await db.get_wallet_balance(user_id)

        if balance < total:
            return JSONResponse(
                {"success": False, "error": f"Insufficient balance. Need {total:,}đ, have {balance:,}đ"},
                status_code=400,
            )

        # Debit wallet
        success, new_balance = await db.debit_wallet(user_id, total)
        if not success:
            return JSONResponse(
                {"success": False, "error": f"Insufficient balance. Need {total:,}đ, have {new_balance:,}đ"},
                status_code=400,
            )

        # Create order
        order_code = make_api_order_code(user_id)
        item = {
            "id": product["id"],
            "name": product["name"],
            "price": int(product["price"]),
            "qty": quantity,
            "delivery_text": product.get("delivery_text", ""),
        }
        await db.create_order(
            order_code=order_code,
            user_id=user_id,
            username=user.get("username"),
            items=[item],
            total=total,
        )

        # Mark paid
        reference = f"api-{user_id}-{order_code}"
        changed, msg, paid_order = await db.mark_order_paid(
            order_code=order_code,
            amount=total,
            reference=reference,
        )

        items_delivered: list[str] = []

        if changed and paid_order:
            assigned, assign_msg, assigned_order = await db.assign_accounts_to_order(order_code)
            if assigned and assigned_order:
                paid_order = assigned_order
                items_delivered = [a["account_text"] for a in assigned_order.get("accounts", [])]
            await db.clear_cart(user_id)

            # Notify via Telegram
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"\u2705 <b>\u0110\u01a1n h\u00e0ng qua API th\u00e0nh c\u00f4ng!</b>\n"
                        f"M\u00e3 \u0111\u01a1n: <code>{order_code}</code>\n"
                        f"S\u1ea3n ph\u1ea9m: <b>{html_escape(product['name'])}</b> x{quantity}\n"
                        f"T\u1ed5ng: <b>{money_vnd(total)}</b>\n"
                        f"S\u1ed1 d\u01b0 c\u00f2n: <b>{money_vnd(new_balance)}</b>"
                    ),
                )
            except Exception:
                pass

            for admin_id in settings.admin_ids:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=(
                            f"\U0001f4b0 <b>\u0110\u01a1n h\u00e0ng qua API</b>\n"
                            f"M\u00e3 \u0111\u01a1n: <code>{order_code}</code>\n"
                            f"Kh\u00e1ch: <code>{html_escape(user.get('username') or str(user_id))}</code>\n"
                            f"S\u1ea3n ph\u1ea9m: {html_escape(product['name'])} x{quantity}\n"
                            f"S\u1ed1 ti\u1ec1n: <b>{money_vnd(total)}</b>"
                        ),
                    )
                except Exception:
                    pass
        else:
            # Refund on failure
            await db.deposit_wallet(user_id, total)
            return JSONResponse(
                {"success": False, "error": f"Order processing failed: {msg}"},
                status_code=500,
            )

        if not items_delivered:
            items_delivered = [item.get("delivery_text", "") or ""]

        return {
            "success": True,
            "order": {
                "order_code": order_code,
                "product": product["name"],
                "quantity": quantity,
                "total_price": total,
            },
            "items": items_delivered,
            "new_balance": new_balance,
        }

    # ── Orders history ───────────────────────────────────────

    @api.get("/orders")
    async def api_orders(request: Request):
        user = await _auth(request)
        if isinstance(user, JSONResponse):
            return user

        orders = await db.list_user_orders_for_api(int(user["user_id"]), limit=50)
        return {
            "success": True,
            "orders": orders,
        }

    # ── Deposit ──────────────────────────────────────────────

    @api.post("/deposit")
    async def api_deposit(request: Request):
        user = await _auth(request)
        if isinstance(user, JSONResponse):
            return user

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"success": False, "error": "Invalid JSON body."},
                status_code=400,
            )

        amount = body.get("amount", 0)
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return JSONResponse(
                {"success": False, "error": "Invalid amount."},
                status_code=400,
            )

        if amount < 10000:
            return JSONResponse(
                {"success": False, "error": "Minimum deposit is 10,000đ."},
                status_code=400,
            )

        if amount > 50000000:
            return JSONResponse(
                {"success": False, "error": "Maximum deposit is 50,000,000đ."},
                status_code=400,
            )

        user_id = int(user["user_id"])

        # Create an order for the deposit to generate payment code
        order_code = make_api_order_code(user_id)
        deposit_item = {
            "id": "wallet_deposit",
            "name": "Nạp ví",
            "price": amount,
            "qty": 1,
            "delivery_text": f"Nạp {amount:,}đ vào ví",
        }
        await db.create_order(
            order_code=order_code,
            user_id=user_id,
            username=user.get("username"),
            items=[deposit_item],
            total=amount,
        )

        try:
            payment_info = sepay.build_payment_info(order_code=order_code, amount=amount)
        except Exception as exc:
            return JSONResponse(
                {"success": False, "error": f"Failed to generate payment: {str(exc)}"},
                status_code=500,
            )

        await db.attach_payment_link(
            order_code=order_code,
            payment_link_id=payment_info.payment_code,
            checkout_url=payment_info.payment_page_url,
            qr_code=payment_info.qr_url,
        )

        return {
            "success": True,
            "deposit": {
                "payment_code": payment_info.payment_code,
                "amount_vnd": amount,
                "bank": {
                    "bank_name": settings.sepay_bank_code,
                    "account_number": settings.sepay_account_no,
                    "account_name": settings.sepay_account_name,
                    "transfer_content": payment_info.payment_code,
                },
                "qr_url": payment_info.qr_url,
                "expires_in_minutes": 10,
            },
            "note": "Chuyển khoản đúng số tiền và nội dung. Bot sẽ tự động cộng vào ví.",
        }

    return api
