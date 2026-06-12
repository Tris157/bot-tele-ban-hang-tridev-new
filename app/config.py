from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _split_admin_ids(value: str) -> set[int]:
    ids: set[int] = set()
    for raw in value.split(","):
        raw = raw.strip()
        if raw.isdigit():
            ids.add(int(raw))
    return ids


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]

    # SePay / VietQR
    sepay_bank_code: str
    sepay_account_no: str
    sepay_account_name: str
    sepay_webhook_api_key: str
    sepay_webhook_secret_key: str
    sepay_auth_mode: str
    sepay_qr_template: str

    public_base_url: str
    web_host: str
    web_port: int
    database_path: str
    order_expire_minutes: int

    @property
    def webhook_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/webhook/sepay"

    @property
    def payment_page_base_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/payment"


def get_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("Thiếu BOT_TOKEN trong file .env")

    public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").strip().rstrip("/")

    return Settings(
        bot_token=bot_token,
        admin_ids=_split_admin_ids(os.getenv("ADMIN_IDS", "")),
        sepay_bank_code=os.getenv("SEPAY_BANK_CODE", "").strip(),
        sepay_account_no=os.getenv("SEPAY_ACCOUNT_NO", "").strip(),
        sepay_account_name=os.getenv("SEPAY_ACCOUNT_NAME", "").strip(),
        sepay_webhook_api_key=os.getenv("SEPAY_WEBHOOK_API_KEY", "").strip(),
        sepay_webhook_secret_key=os.getenv("SEPAY_WEBHOOK_SECRET_KEY", "").strip(),
        sepay_auth_mode=os.getenv("SEPAY_AUTH_MODE", "api_key").strip().lower(),
        sepay_qr_template=os.getenv("SEPAY_QR_TEMPLATE", "compact").strip(),
        public_base_url=public_base_url,
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip(),
        web_port=int(os.getenv("WEB_PORT", "8000")),
        database_path=os.getenv("DATABASE_PATH", "shop.db").strip(),
        order_expire_minutes=int(os.getenv("ORDER_EXPIRE_MINUTES", "5")),
    )
