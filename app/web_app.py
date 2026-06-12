from __future__ import annotations

import json

from aiogram import Bot
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import Settings
from app.db import Database
from app.sepay_client import SePayClient
from app.utils import html_escape, money_vnd
from app.api_routes import create_api_router


def build_delivery_message(order: dict) -> str:
    lines = [
        "✅ <b>Thanh toán thành công!</b>",
        f"Mã đơn: <code>{order['order_code']}</code>",
        f"Tổng: <b>{money_vnd(int(order['total']))}</b>",
        "",
        "📦 <b>Nội dung giao hàng:</b>",
    ]
    for item in order["items"]:
        lines.append(f"\n<b>{html_escape(item['name'])}</b> x{item['qty']}")
        delivery = item.get("delivery_text") or "Shop sẽ liên hệ để giao hàng."
        lines.append(f"<code>{html_escape(delivery)}</code>")
    return "\n".join(lines)


def _html_page(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html lang="vi">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>{title}</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; color: #111; }}
        .wrap {{ max-width: 520px; margin: 24px auto; background: white; padding: 20px; border-radius: 16px; box-shadow: 0 8px 24px rgba(0,0,0,.08); }}
        .qr {{ width: 100%; max-width: 360px; display: block; margin: 16px auto; border-radius: 12px; }}
        code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 6px; }}
        .amount {{ font-size: 26px; font-weight: 700; }}
        .note {{ color: #555; font-size: 14px; }}
        .row {{ margin: 10px 0; }}
      </style>
    </head>
    <body><div class="wrap">{body}</div></body>
    </html>
    """


def create_web_app(bot: Bot, db: Database, sepay: SePayClient, settings: Settings) -> FastAPI:
    app = FastAPI(title="Telegram Shop Bot SePay")

    # Mount API router
    api_router = create_api_router(bot, db, sepay, settings)
    app.include_router(api_router)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _html_page(
            "Telegram Shop Bot SePay",
            """
            <h2>Telegram Shop Bot SePay đang chạy</h2>
            <p>Webhook SePay: <code>/webhook/sepay</code></p>
            <p>Trang QR đơn hàng: <code>/payment/{order_code}</code></p>
            <p>📖 <a href="/api/docs">API Documentation</a></p>
            """,
        )

    @app.get("/payment/{order_code}", response_class=HTMLResponse)
    async def payment_page(order_code: int):
        order = await db.get_order_by_code(order_code)
        if not order:
            return _html_page("Không tìm thấy đơn", "<h2>Không tìm thấy đơn hàng</h2>")

        if order["status"] == "paid":
            return _html_page(
                "Đã thanh toán",
                f"""
                <h2>✅ Đơn đã thanh toán</h2>
                <p>Mã đơn: <code>{order_code}</code></p>
                <p>Quay lại Telegram để nhận hàng/nội dung đơn.</p>
                """,
            )

        qr_url = order.get("qr_code") or sepay.build_qr_url(
            amount=int(order["total"]),
            payment_code=str(order.get("payment_link_id") or SePayClient.make_payment_code(order_code)),
        )
        payment_code = html_escape(str(order.get("payment_link_id") or SePayClient.make_payment_code(order_code)))

        return _html_page(
            "Thanh toán đơn hàng",
            f"""
            <h2>🏦 Thanh toán đơn hàng</h2>
            <div class="row">Mã đơn: <code>{order_code}</code></div>
            <div class="row amount">{money_vnd(int(order['total']))}</div>
            <img class="qr" src="{qr_url}" alt="QR thanh toán" />
            <div class="row">Ngân hàng: <b>{html_escape(settings.sepay_bank_code)}</b></div>
            <div class="row">Số tài khoản: <code>{html_escape(settings.sepay_account_no)}</code></div>
            <div class="row">Chủ tài khoản: <b>{html_escape(settings.sepay_account_name)}</b></div>
            <div class="row">Nội dung chuyển khoản: <code>{payment_code}</code></div>
            <p class="note">Chuyển đúng số tiền và đúng nội dung. Khi SePay webhook báo tiền vào, bot sẽ tự nhả đơn trong Telegram.</p>
            """,
        )

    @app.post("/webhook/sepay")
    async def sepay_webhook(request: Request):
        print("=" * 60)
        print("SePay webhook received!")

        ok, reason = await sepay.verify_webhook_request(request)
        if not ok:
            print(f"  [AUTH FAIL] {reason}")
            return JSONResponse({"success": False, "message": reason}, status_code=401)
        print("  [AUTH] OK")

        try:
            content_type = request.headers.get("content-type", "").lower()
            if "application/json" in content_type:
                payload = await request.json()
            elif "form" in content_type:
                form = await request.form()
                payload = dict(form)
            else:
                raw_body = await request.body()
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as exc:
            print(f"  [PAYLOAD FAIL] {exc}")
            return JSONResponse({"success": False, "message": "Invalid payload"}, status_code=400)

        print(f"  [PAYLOAD] {payload}")

        tx = sepay.parse_transaction(payload)
        print(
            f"  [PARSED] transfer_type={tx.transfer_type!r}, amount={tx.amount}, "
            f"payment_code={tx.payment_code!r}, content={tx.content!r}, "
            f"transaction_id={tx.transaction_id!r}, reference_code={tx.reference_code!r}"
        )

        # Chỉ xử lý tiền vào. BankHub IPN mới dùng credit/debit, payload cũ có thể dùng in/out.
        # FIX: thêm "incoming" cho một số ngân hàng gửi kiểu khác.
        if tx.transfer_type not in {"credit", "in", "", "incoming"}:
            print(f"  [SKIP] Ignored non-credit transaction: transfer_type={tx.transfer_type!r}")
            return {"success": True, "message": "Ignored non-credit transaction"}

        payment_codes = sepay.extract_payment_code_candidates(tx)
        if not payment_codes:
            print(f"  [SKIP] No payment code found")
            print(f"    Content: {tx.content!r}")
            print(f"    Payment code field: {tx.payment_code!r}")
            return {"success": True, "message": "No payment code found"}

        # Try each candidate code against DB (exact match first)
        order = None
        payment_code = None
        for candidate in payment_codes:
            order = await db.get_order_by_payment_code(candidate)
            if order:
                payment_code = candidate
                print(f"  [PAYMENT CODE] Exact match: {candidate}")
                break

        # Fallback: prefix/fuzzy search for codes with bank-appended digits
        if not order:
            for candidate in payment_codes:
                order = await db.get_order_by_payment_code_prefix(candidate)
                if order:
                    payment_code = candidate
                    print(f"  [PAYMENT CODE] Prefix match: {candidate} → payment_link_id={order.get('payment_link_id')}")
                    break

        if not order or not payment_code:
            print(f"  [FAIL] Order not found for any payment_code candidate: {payment_codes}")
            return JSONResponse(
                {"success": False, "message": f"Không tìm thấy đơn với payment_code {payment_codes}"},
                status_code=400,
            )
        print(
            f"  [ORDER FOUND] order_code={order['order_code']}, status={order['status']}, "
            f"total={order['total']}, payment_link_id={order.get('payment_link_id')}"
        )

        # CRITICAL FIX: Improve reference uniqueness by adding timestamp
        import time
        reference = tx.transaction_id or tx.reference_code or f"sepay-{payment_code}-{tx.amount}-{int(time.time())}"
        print(f"  [MARK PAID] order_code={order['order_code']}, amount={tx.amount}, reference={reference}")
        changed, message, paid_order = await db.mark_order_paid(
            order_code=int(order["order_code"]),
            amount=tx.amount,
            reference=reference,
        )

        if not changed:
            # Trùng giao dịch thì trả success để SePay không retry vô ích.
            status = 200 if "đã" in message.lower() or "trùng" in message.lower() else 400
            print(
                f"  [MARK PAID FAIL] message={message}, "
                f"order_total={order['total']}, webhook_amount={tx.amount}"
            )
            return JSONResponse({"success": status == 200, "message": message}, status_code=status)

        assert paid_order is not None
        print(f"  [PAID OK] order_code={paid_order['order_code']}")

        assigned, assign_message, assigned_order = await db.assign_accounts_to_order(int(paid_order["order_code"]))
        print(f"  [ASSIGN] assigned={assigned}, message={assign_message}")
        if assigned and assigned_order is not None:
            paid_order = assigned_order
        await db.clear_cart(int(paid_order["user_id"]))

        # Gắn user_id khách hàng vào hồ sơ khi thanh toán thành công
        try:
            user_id = int(paid_order["user_id"])
            await db.get_or_create_profile(
                user_id=user_id,
                username=paid_order.get("username"),
            )
        except Exception as exc:
            print(f"  [PROFILE] Failed to create profile for user {paid_order['user_id']}: {exc}")

        # CRITICAL FIX: Wrap Telegram sends in try/except so a Telegram API error
        # doesn't cause 500 → SePay retry → double processing.

        # Delete QR code + waiting messages (cleanup)
        try:
            qr_info = await db.get_qr_message_ids(int(paid_order["order_code"]))
            chat_id = int(paid_order["user_id"])
            if qr_info.get("qr_message_id"):
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=qr_info["qr_message_id"])
                except Exception:
                    pass
            if qr_info.get("wait_message_id"):
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=qr_info["wait_message_id"])
                except Exception:
                    pass
            print(f"  [CLEANUP] QR messages deleted for order {paid_order['order_code']}")
        except Exception as exc:
            print(f"  [CLEANUP] Failed to delete QR messages: {exc}")

        try:
            await bot.send_message(
                chat_id=int(paid_order["user_id"]),
                text=build_delivery_message(paid_order),
            )
            print(f"  [TELEGRAM] Delivery message sent to user {paid_order['user_id']}")
        except Exception as exc:
            print(f"  [TELEGRAM ERROR] Failed to send delivery to user {paid_order['user_id']}: {exc}")
            # CRITICAL: Continue processing, do not raise exception

        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "💰 <b>Có đơn đã thanh toán qua SePay</b>\n"
                        f"Mã đơn: <code>{paid_order['order_code']}</code>\n"
                        f"Nội dung CK: <code>{html_escape(payment_code)}</code>\n"
                        f"Số tiền: <b>{money_vnd(tx.amount)}</b>\n"
                        f"Transaction ID: <code>{html_escape(reference)}</code>\n"
                        f"Giao tài khoản: <b>{html_escape(assign_message)}</b>"
                    ),
                )
            except Exception as exc:
                print(f"  [TELEGRAM ERROR] Failed to notify admin {admin_id}: {exc}")
                # CRITICAL: Continue to next admin, do not raise exception

        print(f"  [DONE] Order {paid_order['order_code']} fully processed!")
        print("=" * 60)
        return {"success": True}

    return app
