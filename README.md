# Telegram Shop Bot + SePay/VietQR

Bot mẫu này có sẵn:

- Xem sản phẩm bằng `/shop`
- Thêm/xóa sản phẩm trong giỏ
- Tạo đơn hàng
- Sinh QR VietQR bằng link ảnh `qr.sepay.vn`
- Hiện trang QR thanh toán riêng cho từng đơn
- Nhận webhook/IPN SePay khi khách bank thành công
- Tự đổi đơn sang `paid`
- Tự gửi nội dung giao hàng cho khách
- Chống xử lý trùng giao dịch bằng `transaction_id/reference_code`
- Admin xem đơn bằng `/admin_orders`

> Lưu ý: chỉ dùng bot này cho sản phẩm/dịch vụ hợp pháp, không bán hàng cấm, hàng giới hạn độ tuổi, hoặc nội dung không phù hợp.

## 1. Chuẩn bị

Cần có:

- Python 3.11+
- Bot Telegram tạo từ `@BotFather`
- Tài khoản SePay đã liên kết tài khoản ngân hàng
- Mã ngân hàng + số tài khoản nhận tiền
- Webhook SePay trỏ về domain public của bạn
- Một domain public để SePay gọi webhook. Khi test local có thể dùng ngrok hoặc cloudflared.

## 2. Cài đặt

Windows:

```bash
cd telegram_shop_bot_sepay
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

macOS/Linux:

```bash
cd telegram_shop_bot_sepay
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. Điền file `.env`

```env
BOT_TOKEN=token_bot_cua_ban
ADMIN_IDS=telegram_id_cua_ban

SEPAY_BANK_CODE=MBBank
SEPAY_ACCOUNT_NO=so_tai_khoan_nhan_tien
SEPAY_ACCOUNT_NAME=TEN CHU TAI KHOAN
SEPAY_QR_TEMPLATE=compact

SEPAY_AUTH_MODE=api_key
SEPAY_WEBHOOK_API_KEY=api_key_webhook_cua_ban
SEPAY_WEBHOOK_SECRET_KEY=

PUBLIC_BASE_URL=https://domain-public-cua-ban
WEB_HOST=0.0.0.0
WEB_PORT=8000
DATABASE_PATH=shop.db
```

Lấy Telegram ID của bạn bằng bot `@userinfobot`, rồi điền vào `ADMIN_IDS`.

## 4. Chạy bot

```bash
python -m app.main
```

Màn hình sẽ in ra webhook URL dạng:

```text
https://domain-public-cua-ban/webhook/sepay
```

Lấy URL đó đăng ký trong dashboard SePay.

## 5. Cấu hình webhook SePay

Trong SePay, tạo webhook/IPN trỏ tới:

```text
https://domain-public-cua-ban/webhook/sepay
```

Nếu dùng xác thực API Key, cấu hình để SePay gửi header:

```text
Authorization: Apikey API_KEY_CUA_BAN
```

Rồi điền cùng key đó vào `.env`:

```env
SEPAY_AUTH_MODE=api_key
SEPAY_WEBHOOK_API_KEY=API_KEY_CUA_BAN
```

Nếu bạn cấu hình kiểu secret key, dùng:

```env
SEPAY_AUTH_MODE=secret_key
SEPAY_WEBHOOK_SECRET_KEY=SECRET_KEY_CUA_BAN
```

## 6. Test local bằng ngrok

Mở terminal khác:

```bash
ngrok http 8000
```

Copy link HTTPS của ngrok, ví dụ:

```text
https://abc-xyz.ngrok-free.app
```

Sửa `.env`:

```env
PUBLIC_BASE_URL=https://abc-xyz.ngrok-free.app
```

Sau đó tắt bot và chạy lại:

```bash
python -m app.main
```

Đăng ký webhook trên SePay:

```text
https://abc-xyz.ngrok-free.app/webhook/sepay
```

## 7. Sửa sản phẩm

Sửa file:

```text
data/products.json
```

Ví dụ:

```json
{
  "id": "goi_vip_1",
  "name": "Gói VIP 1",
  "price": 50000,
  "stock": 100,
  "description": "Mô tả sản phẩm",
  "delivery_text": "Nội dung bot gửi sau khi khách thanh toán"
}
```

Sau khi sửa, chạy lại bot. Code sẽ seed lại sản phẩm vào database.

## 8. Luồng hoạt động

```text
Khách /shop
→ Thêm vào giỏ
→ Tạo đơn
→ Bot sinh payment_code kiểu DH1234567
→ Bot sinh QR VietQR qua qr.sepay.vn
→ Khách quét QR và chuyển khoản đúng nội dung
→ SePay gọi POST /webhook/sepay
→ Server kiểm tra Authorization/X-Secret-Key
→ Server đọc payment_code/content + amount + transaction_id
→ Check đúng đơn + đúng tiền + chưa xử lý transaction_id
→ Mark paid
→ Bot tự gửi delivery_text cho khách
```

## 9. Test webhook không cần bank thật

Sau khi tạo đơn bằng bot, bạn sẽ thấy nội dung chuyển khoản dạng `DH1234567` và tổng tiền.

Chạy:

```bash
python scripts/simulate_sepay_webhook.py <payment_code> <amount>
```

Ví dụ:

```bash
python scripts/simulate_sepay_webhook.py DH1234567 10000
```

Script này chỉ để test local. Khi dùng thật, phải để SePay gọi webhook thật.

## 10. Lưu ý bảo mật

- Không đưa `.env` lên GitHub.
- Không giao hàng khi webhook chưa xác thực header thành công.
- Không chỉ dựa vào ảnh bill.
- Luôn check đúng `payment_code`, đúng `amount`, đúng `status=pending`.
- Luôn chống xử lý trùng bằng `transaction_id/reference_code`.
- Nên deploy lên VPS/Railway/Render/Fly.io thay vì chạy trên máy cá nhân.

## 11. Cấu trúc project

```text
telegram_shop_bot_sepay/
├── app/
│   ├── bot_handlers.py
│   ├── config.py
│   ├── db.py
│   ├── keyboards.py
│   ├── main.py
│   ├── sepay_client.py
│   ├── utils.py
│   └── web_app.py
├── data/
│   └── products.json
├── scripts/
│   └── simulate_sepay_webhook.py
├── .env.example
├── requirements.txt
└── README.md
```
