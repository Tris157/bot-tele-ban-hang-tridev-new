"""Test webhook SePay local không cần bank thật.

Cách dùng:
    python scripts/simulate_sepay_webhook.py DH1234567 10000

Trong đó tham số 1 là nội dung CK/payment_code, tham số 2 là amount.
Script sẽ POST payload mẫu vào localhost:8000/webhook/sepay.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/simulate_sepay_webhook.py <payment_code> <amount>")
        raise SystemExit(1)

    payment_code = sys.argv[1].strip().upper()
    amount = int(sys.argv[2])
    transaction_id = f"TEST-{payment_code}-{int(datetime.now().timestamp())}"

    payload = {
        "gateway": "MBBank",
        "transaction_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_number": os.getenv("SEPAY_ACCOUNT_NO", "1234567890"),
        "bank_account_xid": "test-bank-account-xid",
        "va": None,
        "payment_code": payment_code,
        "content": f"{payment_code} chuyen tien",
        "transfer_type": "credit",
        "amount": amount,
        "reference_code": f"FT{transaction_id}",
        "accumulated": 0,
        "transaction_id": transaction_id,
    }

    headers = {"Content-Type": "application/json"}
    mode = os.getenv("SEPAY_AUTH_MODE", "api_key").strip().lower()
    if mode == "api_key":
        api_key = os.getenv("SEPAY_WEBHOOK_API_KEY", "")
        if not api_key:
            print("Thiếu SEPAY_WEBHOOK_API_KEY trong .env")
            raise SystemExit(1)
        headers["Authorization"] = f"Apikey {api_key}"
    elif mode == "secret_key":
        secret_key = os.getenv("SEPAY_WEBHOOK_SECRET_KEY", "")
        if not secret_key:
            print("Thiếu SEPAY_WEBHOOK_SECRET_KEY trong .env")
            raise SystemExit(1)
        headers["X-Secret-Key"] = secret_key

    url = "http://localhost:8000/webhook/sepay"
    response = httpx.post(url, json=payload, headers=headers, timeout=10)
    print(response.status_code)
    print(response.text)


if __name__ == "__main__":
    main()
