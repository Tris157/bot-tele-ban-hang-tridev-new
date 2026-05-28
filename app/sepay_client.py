from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from fastapi import Request

from app.config import Settings


class SePayError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaymentInfo:
    payment_code: str
    qr_url: str
    payment_page_url: str


@dataclass(frozen=True)
class SePayTransaction:
    transaction_id: str
    payment_code: str | None
    content: str
    transfer_type: str
    amount: int
    reference_code: str | None
    raw: dict[str, Any]


class SePayClient:
    QR_BASE = "https://qr.sepay.vn/img"

    def __init__(self, settings: Settings):
        self.bank_code = settings.sepay_bank_code
        self.account_no = settings.sepay_account_no
        self.account_name = settings.sepay_account_name
        self.webhook_api_key = settings.sepay_webhook_api_key
        self.webhook_secret_key = settings.sepay_webhook_secret_key
        self.auth_mode = settings.sepay_auth_mode
        self.qr_template = settings.sepay_qr_template
        self.payment_page_base_url = settings.payment_page_base_url

    def ensure_configured_for_qr(self) -> None:
        missing: list[str] = []
        if not self.bank_code:
            missing.append("SEPAY_BANK_CODE")
        if not self.account_no:
            missing.append("SEPAY_ACCOUNT_NO")
        if missing:
            raise SePayError("Thiếu cấu hình SePay/VietQR: " + ", ".join(missing))

    @staticmethod
    def make_payment_code(order_code: int) -> str:
        # Keep the transfer note ASCII-only, but include the full order code so
        # SePay webhooks cannot collide with older pending orders.
        return f"DH{order_code}"

    def build_qr_url(self, *, amount: int, payment_code: str) -> str:
        self.ensure_configured_for_qr()
        params = {
            "acc": self.account_no,
            "bank": self.bank_code,
            "amount": int(amount),
            "des": payment_code,
        }
        if self.qr_template:
            params["template"] = self.qr_template
        return f"{self.QR_BASE}?{urlencode(params)}"

    def build_payment_info(self, *, order_code: int, amount: int) -> PaymentInfo:
        payment_code = self.make_payment_code(order_code)
        qr_url = self.build_qr_url(amount=amount, payment_code=payment_code)
        payment_page_url = f"{self.payment_page_base_url}/{order_code}"
        return PaymentInfo(
            payment_code=payment_code,
            qr_url=qr_url,
            payment_page_url=payment_page_url,
        )

    async def verify_webhook_request(self, request: Request) -> tuple[bool, str]:
        """Verify request đến từ SePay.

        SePay có nhiều kiểu cấu hình webhook. Project này hỗ trợ:
        - SEPAY_AUTH_MODE=api_key: header Authorization: Apikey <key>
        - SEPAY_AUTH_MODE=secret_key: header X-Secret-Key: <secret>
        - SEPAY_AUTH_MODE=none: bỏ qua verify, chỉ dùng để test local
        """
        mode = self.auth_mode or "api_key"
        if mode == "none":
            return True, "OK"

        if mode == "api_key":
            if not self.webhook_api_key:
                return False, "Server thiếu SEPAY_WEBHOOK_API_KEY"
            auth = request.headers.get("authorization", "").strip()
            expected = f"Apikey {self.webhook_api_key}"
            if auth != expected:
                return False, "Sai Authorization header"
            return True, "OK"

        if mode == "secret_key":
            if not self.webhook_secret_key:
                return False, "Server thiếu SEPAY_WEBHOOK_SECRET_KEY"
            secret = request.headers.get("x-secret-key", "").strip()
            if secret != self.webhook_secret_key:
                return False, "Sai X-Secret-Key header"
            return True, "OK"

        return False, f"SEPAY_AUTH_MODE không hợp lệ: {mode}"

    @staticmethod
    def parse_transaction(payload: dict[str, Any]) -> SePayTransaction:
        # New BankHub IPN fields: transaction_id, payment_code, content, transfer_type, amount...
        # Older/other SePay payloads sometimes use id, code, transferType, transferAmount.
        transaction_id = str(
            payload.get("transaction_id")
            or payload.get("id")
            or payload.get("transactionId")
            or payload.get("reference_code")
            or payload.get("referenceCode")
            or ""
        ).strip()
        reference_code = str(
            payload.get("reference_code")
            or payload.get("referenceCode")
            or payload.get("reference")
            or ""
        ).strip() or None
        payment_code = str(
            payload.get("payment_code")
            or payload.get("paymentCode")
            or payload.get("code")
            or ""
        ).strip() or None
        content = str(
            payload.get("content")
            or payload.get("transaction_content")
            or payload.get("transactionContent")
            or payload.get("description")
            or ""
        )
        transfer_type = str(payload.get("transfer_type") or payload.get("transferType") or "").lower()

        # --- FIX: ưu tiên amount_in / amountIn (tiền vào) trước amount chung ---
        # Nếu payload có cả amount và amount_out, amount có thể là tiền ra.
        # Ưu tiên: amount_in > amountIn > transferAmount > amount > order_amount
        amount_in_raw = payload.get("amount_in") or payload.get("amountIn")
        if amount_in_raw:
            amount_raw = amount_in_raw
        else:
            amount_raw = (
                payload.get("transferAmount")
                or payload.get("amount")
                or payload.get("order_amount")
                or 0
            )

        try:
            amount = int(float(amount_raw))
        except (TypeError, ValueError):
            amount = 0

        try:
            amount_out = int(float(payload.get("amount_out") or payload.get("amountOut") or 0))
        except (TypeError, ValueError):
            amount_out = 0

        # --- FIX: cải thiện logic detect transfer_type ---
        # Nếu SePay gửi rõ ràng thì dùng, nếu không thì:
        # - Có amount_in > 0 → credit
        # - Chỉ có amount_out > 0 (và amount_in = 0) → debit
        # - Cả hai đều 0 hoặc không rõ → mặc định credit (an toàn hơn, để mark_order_paid check số tiền)
        if not transfer_type:
            if amount > 0:
                transfer_type = "credit"
            elif amount_out > 0:
                transfer_type = "debit"
            else:
                transfer_type = "credit"

        if not transaction_id:
            # Không lý tưởng, nhưng vẫn tạo id ổn định để chống trùng phần nào.
            transaction_id = f"sepay-{reference_code or payment_code or content}-{amount}"

        return SePayTransaction(
            transaction_id=transaction_id,
            payment_code=payment_code,
            content=content,
            transfer_type=transfer_type,
            amount=amount,
            reference_code=reference_code,
            raw=payload,
        )

    @staticmethod
    def extract_payment_code(tx: SePayTransaction) -> str | None:
        # FIX: SePay field `code` thường bị cắt ngắn (vd: DH1779982853 thay vì DH1779982853451).
        # Luôn ưu tiên tìm mã DH dài nhất từ `content` (nội dung chuyển khoản) vì nó chứa đầy đủ.
        # Chỉ fallback sang `payment_code` (field code) nếu content không có.
        content_upper = tx.content.upper()
        matches = re.findall(r"DH\d+", content_upper)
        if matches:
            # Lấy mã dài nhất (đầy đủ nhất)
            return max(matches, key=len)
        if tx.payment_code:
            return tx.payment_code.upper()
        return None
