# SePay Webhook Order Delivery Bugfix Design

## Overview

This design addresses a critical payment processing bug where SePay webhook payments succeed at the bank level but fail to trigger order fulfillment due to seven distinct root causes. The fix ensures reliable order processing by improving authentication error logging, payment code extraction logic, order lookup strategy, amount tolerance handling, Telegram API error resilience, transaction reference uniqueness, and comprehensive regression prevention.

The approach is surgical: each root cause has a targeted fix that preserves existing behavior for non-buggy cases while correctly handling the problematic scenarios. All fixes are implemented within the existing webhook handler flow in `app/web_app.py`, `app/sepay_client.py`, and `app/db.py`.

## Glossary

- **Bug_Condition (C)**: The condition that triggers order delivery failure - when valid payment webhooks fail to mark orders as paid due to auth failures, code extraction errors, lookup failures, amount mismatches, Telegram errors, or duplicate transaction processing
- **Property (P)**: The desired behavior when valid payments arrive - orders should be reliably marked as paid, accounts assigned, and customers notified without double-processing
- **Preservation**: Existing duplicate detection, transfer type filtering, expired order handling, and stock validation that must remain unchanged
- **sepay_webhook**: The POST handler at `/webhook/sepay` in `app/web_app.py` that processes SePay payment notifications
- **mark_order_paid**: The database method in `app/db.py` that atomically updates order status to paid and records the transaction
- **extract_payment_code**: The method in `app/sepay_client.py` that parses payment codes from webhook transaction data
- **processed_transactions**: Database table storing transaction references to prevent duplicate processing
- **payment_link_id**: The field in orders table storing the payment code (e.g., "DH1779982853451") used for order lookup
- **transfer_type**: The transaction direction indicator in webhook payload (credit/in = money coming in, debit/out = money going out)

## Bug Details

### Bug Condition

The bug manifests when a valid SePay webhook arrives but the order processing fails due to any of seven root causes. The webhook handler is either failing authentication verification with insufficient logging, extracting truncated payment codes, failing order lookup due to query logic, rejecting valid payments due to strict amount comparison, crashing on Telegram API errors, or processing duplicate transactions due to non-unique reference IDs.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type WebhookRequest (SePay payment notification)
  OUTPUT: boolean
  
  RETURN (authenticationFailsWithoutLogging(input)
         OR paymentCodeTruncatedInField(input) 
         OR paymentCodeOnlyInContent(input)
         OR orderLookupFailsDespiteValidCode(input)
         OR amountMismatchDueToBankFees(input)
         OR telegramAPIFailsCausesWebhookFailure(input)
         OR transactionReferenceNotUnique(input))
         AND validPaymentExists(input)
         AND orderShouldBePaid(input)
         AND NOT orderMarkedAsPaid(input.order_code)
END FUNCTION
```

### Examples

**Root Cause 1: Authentication Failure**
- Webhook arrives with header `Authorization: Bearer abc123` (wrong format)
- Expected: SePay format is `Authorization: Apikey abc123`
- Current behavior: Returns 401, logs only "Sai Authorization header"
- Impact: Admin cannot diagnose misconfiguration without detailed logs

**Root Cause 2: Payment Code Truncation**
- Webhook `payment_code` field: "DH1779982" (truncated by SePay)
- Webhook `content` field: "Chuyen khoan DH1779982853451 thanh toan"
- Current behavior: Uses truncated code, fails to find order
- Impact: Valid payment rejected with "Không tìm thấy đơn"

**Root Cause 3: Payment Code Extraction Priority**
- Webhook has `content`: "Transfer for DH1779982853451"
- Webhook `payment_code` field: null or empty
- Current behavior: May fail to extract code if only checking `payment_code`
- Impact: Order not found despite code present in content

**Root Cause 4: Order Lookup Strategy**
- Database has order_code=1779982853451, payment_link_id="DH1779982853451", status="pending"
- Webhook sends payment_code="DH1779982853451"
- Current behavior: Lookup works correctly in current implementation
- Edge case: If multiple orders share same payment_link_id (shouldn't happen but possible), must prioritize "pending" status

**Root Cause 5: Amount Tolerance**
- Order total: 50,000đ
- Customer payment: 50,005đ (bank added small fee)
- Current behavior: Strict equality check rejects with "Số tiền không khớp"
- Impact: Valid payment rejected due to minor difference

**Root Cause 6: Telegram API Error**
- Order marked as paid successfully
- Telegram API returns 400 (user blocked bot) or network timeout
- Current behavior: Exception propagates, webhook returns 500, SePay retries
- Impact: Duplicate processing possible if transaction reference check fails

**Root Cause 7: Transaction Reference Uniqueness**
- Webhook transaction_id: "" (empty)
- Webhook reference_code: "" (empty)
- Current behavior: Fallback to `f"sepay-{payment_code}-{amount}"` may not be unique if same payment_code is used multiple times
- Impact: Duplicate webhooks may bypass processed_transactions check

**Edge Case: Combined Failures**
- Payment code truncated + Telegram error = order found but delivery fails and webhook returns 500
- Expected: Extract full code from content, handle Telegram error gracefully, return 200

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Duplicate detection via `processed_transactions` table must continue to work
- Transfer type filtering (reject debit/out transactions) must continue to work  
- Expired order rejection must continue to work
- Already-paid order handling must continue to work
- Stock validation and rollback must continue to work
- Account assignment logic must continue to work
- Cart clearing after successful payment must continue to work

**Scope:**
All inputs that do NOT involve the seven specific root causes should be completely unaffected by this fix. This includes:
- Valid webhooks with correct auth, correct codes, matching amounts, working Telegram API
- Duplicate webhooks (should continue to be detected and ignored)
- Invalid transfer types (should continue to be ignored)
- Expired orders (should continue to be rejected)
- Invalid amounts outside tolerance (should continue to be rejected if truly wrong)

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Authentication Failure Logging**: The `verify_webhook_request` method in `sepay_client.py` returns generic error messages like "Sai Authorization header" without logging the actual header received or expected format, making debugging impossible

2. **Payment Code Field Truncation**: SePay's `payment_code` field is sometimes truncated (e.g., "DH1779982" instead of "DH1779982853451"), but the `extract_payment_code` method in current code already prioritizes `content` field - however, the regex may not select the **longest** match if multiple codes exist

3. **Order Lookup Query**: The `get_order_by_payment_code` method already has correct logic with `ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, id DESC`, but edge cases may exist where multiple orders share payment_link_id

4. **Amount Comparison Strictness**: The `mark_order_paid` method uses strict equality `if order_total != paid_amount` (current code actually has tolerance: `max(int(order_total * 0.01), 1000)`), so this may already be partially fixed but needs verification

5. **Telegram API Exception Handling**: The webhook handler in `web_app.py` does NOT wrap `bot.send_message` calls in try-except blocks, so any Telegram error causes the webhook to return 500, triggering SePay retry

6. **Transaction Reference Construction**: The `parse_transaction` method falls back to constructing reference as `f"sepay-{payment_code}-{amount}"`, which may not be unique if the same payment_code is reused or if payment_code is null

7. **Duplicate Processing Race Condition**: If Telegram error causes 500 return before `processed_transactions` is recorded, the retry may reprocess the same transaction

## Correctness Properties

Property 1: Bug Condition - Valid Payments Trigger Order Fulfillment

_For any_ webhook input where authentication is valid, payment code exists (in content or payment_code field), order is found, amount is within tolerance, and order is in pending status, the fixed webhook handler SHALL mark the order as paid, assign accounts, send delivery messages (with error handling), notify admins (with error handling), and return 200 success.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**

Property 2: Preservation - Non-Buggy Payment Processing Unchanged

_For any_ webhook input that does NOT match the bug conditions (duplicate transactions, wrong transfer type, expired orders, already-paid orders, insufficient stock), the fixed code SHALL produce exactly the same behavior as the original code, preserving duplicate detection, transfer filtering, expiration handling, and stock validation.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

## Fix Implementation

### Summary of Changes

**Already Correct (No Changes Needed):**
- ✅ Payment code extraction prioritizes `content` field and selects longest match
- ✅ Order lookup uses `payment_link_id` and prioritizes pending orders
- ✅ Amount tolerance allows max(1% of total, 1000đ) variance
- ✅ Duplicate detection via `processed_transactions` happens first in transaction
- ✅ Transaction ordering in `mark_order_paid` is correct and idempotent
- ✅ Database schema has all required tables, indexes, and constraints

**Changes Required:**
- ⚠️ Add detailed logging when authentication fails (show format, mode, sanitized headers)
- ⚠️ Add explicit logging of payment code extraction source and result
- ⚠️ Add logging of amount tolerance calculation and comparison
- ⚠️ Wrap Telegram API calls in try-except to prevent 500 errors causing SePay retries
- ⚠️ Improve transaction reference uniqueness fallback (add timestamp or content hash)
- ⚠️ Add comprehensive logging throughout webhook flow for debugging

**Key Insight:**
Most root causes are already partially or fully addressed in the current code! The main issue is lack of visibility (logging) and Telegram error handling. The fixes are primarily about making the existing logic more robust and observable.

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/sepay_client.py`

**Function**: `verify_webhook_request`

**Specific Changes**:
1. **Enhanced Authentication Logging**: Add detailed logging when authentication fails
   - Log the received Authorization header (sanitized)
   - Log the expected header format
   - Log the auth mode being used (api_key, secret_key, none)
   - This enables quick diagnosis of misconfiguration issues

**Function**: `extract_payment_code`

**Specific Changes**:
2. **Longest Match Selection**: Ensure regex extraction selects longest DH code
   - Current code: `matches = re.findall(r"DH\d+", content_upper)` then `return max(matches, key=len)`
   - Verify this is working correctly and prioritizes content over payment_code field
   - This is already implemented correctly, but add explicit comment explaining the priority

**File**: `app/db.py`

**Function**: `mark_order_paid`

**Specific Changes**:
3. **Amount Tolerance Verification**: Confirm tolerance logic is working
   - Current code: `tolerance = max(int(order_total * 0.01), 1000)`
   - This is already correct (1% or 1000đ, whichever is larger)
   - Add test to verify it works for edge cases

**File**: `app/web_app.py`

**Function**: `sepay_webhook`

**Specific Changes**:
4. **Telegram API Error Handling**: Wrap all `bot.send_message` calls in try-except
   - Wrap customer delivery message send in try-except, log error, continue
   - Wrap each admin notification in try-except, log error, continue
   - This prevents Telegram failures from causing 500 response and SePay retry
   
5. **Transaction Reference Uniqueness**: Improve reference ID construction
   - Verify `parse_transaction` constructs unique reference from transaction_id, reference_code, or fallback
   - Current fallback: `f"sepay-{payment_code}-{amount}"` is NOT unique if same code reused
   - NEW fallback: `f"sepay-{payment_code}-{amount}-{int(time.time())}"` adds timestamp for uniqueness
   - Alternative: Use `f"sepay-{reference_code or payment_code}-{amount}-{hashlib.md5(content.encode()).hexdigest()[:8]}"` for deterministic uniqueness
   - Ensure `processed_transactions` check happens FIRST in mark_order_paid before any state changes

6. **Authentication Failure Detail Logging**: Log full context when auth fails
   - Log request headers (sanitized)
   - Log auth mode configuration
   - Log expected vs received values

7. **Payment Code Extraction Robustness**: Verify content is prioritized
   - Current implementation already does this correctly
   - Add explicit logging of extraction source (content vs payment_code field)

### Implementation Details

**sepay_client.py changes:**

```python
async def verify_webhook_request(self, request: Request) -> tuple[bool, str]:
    """Verify request đến từ SePay with detailed logging on failure."""
    mode = self.auth_mode or "api_key"
    if mode == "none":
        return True, "OK"

    if mode == "api_key":
        if not self.webhook_api_key:
            print(f"  [AUTH ERROR] Missing SEPAY_WEBHOOK_API_KEY in configuration")
            return False, "Server thiếu SEPAY_WEBHOOK_API_KEY"
        auth = request.headers.get("authorization", "").strip()
        expected = f"Apikey {self.webhook_api_key}"
        if auth != expected:
            # Enhanced logging - sanitize by showing only format
            auth_format = auth.split()[0] if auth else "(empty)"
            print(f"  [AUTH ERROR] Authorization header mismatch")
            print(f"    Received format: {auth_format}")
            print(f"    Expected format: Apikey <key>")
            print(f"    Auth mode: {mode}")
            return False, "Sai Authorization header"
        return True, "OK"

    if mode == "secret_key":
        if not self.webhook_secret_key:
            print(f"  [AUTH ERROR] Missing SEPAY_WEBHOOK_SECRET_KEY in configuration")
            return False, "Server thiếu SEPAY_WEBHOOK_SECRET_KEY"
        secret = request.headers.get("x-secret-key", "").strip()
        if secret != self.webhook_secret_key:
            print(f"  [AUTH ERROR] X-Secret-Key mismatch")
            print(f"    Received: {'(present)' if secret else '(missing)'}") 
            print(f"    Auth mode: {mode}")
            return False, "Sai X-Secret-Key header"
        return True, "OK"

    return False, f"SEPAY_AUTH_MODE không hợp lệ: {mode}"


@staticmethod
def extract_payment_code(tx: SePayTransaction) -> str | None:
    """Extract payment code, prioritizing content field over payment_code field.
    
    SePay's payment_code field is sometimes truncated (e.g., DH1779982 instead of 
    DH1779982853451). Always search transaction content first and select the longest
    match to ensure we get the complete order code.
    """
    # Priority 1: Search transaction content for full payment code
    content_upper = tx.content.upper()
    matches = re.findall(r"DH\d+", content_upper)
    if matches:
        longest_match = max(matches, key=len)
        print(f"  [PAYMENT CODE] Extracted from content: {longest_match}")
        return longest_match
    
    # Priority 2: Fallback to payment_code field (may be truncated)
    if tx.payment_code:
        print(f"  [PAYMENT CODE] Using payment_code field: {tx.payment_code.upper()}")
        return tx.payment_code.upper()
    
    print(f"  [PAYMENT CODE] Not found in content or payment_code field")
    return None
```

**web_app.py changes:**

```python
@app.post("/webhook/sepay")
async def sepay_webhook(request: Request):
    print("=" * 60)
    print("SePay webhook received!")

    ok, reason = await sepay.verify_webhook_request(request)
    if not ok:
        print(f"  [AUTH FAIL] {reason}")
        # Enhanced logging already in verify_webhook_request
        return JSONResponse({"success": False, "message": reason}, status_code=401)
    print("  [AUTH] OK")

    # ... existing payload parsing ...

    # ... existing transfer_type check ...

    payment_code = sepay.extract_payment_code(tx)
    if not payment_code:
        print(f"  [SKIP] No payment code found")
        print(f"    Content: {tx.content!r}")
        print(f"    Payment code field: {tx.payment_code!r}")
        return {"success": True, "message": "No payment code found"}
    print(f"  [PAYMENT CODE] {payment_code}")

    # ... existing order lookup ...

    # CRITICAL FIX: Improve reference uniqueness
    import time
    reference = tx.transaction_id or tx.reference_code or f"sepay-{payment_code}-{tx.amount}-{int(time.time())}"
    print(f"  [MARK PAID] order_code={order['order_code']}, amount={tx.amount}, reference={reference}")
    
    changed, message, paid_order = await db.mark_order_paid(
        order_code=int(order["order_code"]),
        amount=tx.amount,
        reference=reference,
    )

    if not changed:
        # ... existing duplicate/error handling ...
        pass

    # ... existing account assignment ...

    # ... existing profile creation ...

    # CRITICAL FIX: Wrap Telegram sends in try/except
    try:
        await bot.send_message(
            chat_id=int(paid_order["user_id"]),
            text=build_delivery_message(paid_order),
        )
        print(f"  [TELEGRAM] Delivery message sent to user {paid_order['user_id']}")
    except Exception as exc:
        print(f"  [TELEGRAM ERROR] Failed to send delivery to user {paid_order['user_id']}: {exc}")
        # CRITICAL: Continue processing, do not raise

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
            # CRITICAL: Continue to next admin, do not raise

    print(f"  [DONE] Order {paid_order['order_code']} fully processed!")
    print("=" * 60)
    return {"success": True}
```

**db.py changes:**

```python
async def mark_order_paid(
    self,
    *,
    order_code: int,
    amount: int,
    reference: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Idempotent: webhook gọi trùng sẽ không nhả đơn lần 2.
    
    CRITICAL ORDER OF OPERATIONS (already correct in current implementation):
    1. BEGIN IMMEDIATE (acquire write lock)
    2. Check processed_transactions FIRST (duplicate detection)
    3. Check order exists
    4. Check if already paid (record in processed_transactions even if no-op)
    5. Check order status is pending
    6. Check order expiration
    7. Check amount tolerance
    8. Check stock availability
    9. Update stock
    10. Update order status to paid
    11. INSERT into processed_transactions (in same transaction)
    12. COMMIT (release lock)
    
    This ordering guarantees idempotency even if Telegram API fails after commit.
    """
    async with aiosqlite.connect(self.path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")

        # CRITICAL: Check processed_transactions FIRST before any other logic
        existing = await db.execute_fetchall(
            "SELECT reference FROM processed_transactions WHERE reference = ?",
            (reference,),
        )
        if existing:
            await db.commit()
            print(f"  [DUPLICATE] Transaction {reference} already processed")
            return False, "Giao dịch đã xử lý trước đó.", None

        # ... existing order lookup ...

        # ... existing status checks ...

        # Amount tolerance check (already correct, just add logging)
        order_total = int(order["total"])
        paid_amount = int(amount)
        tolerance = max(int(order_total * 0.01), 1000)
        if abs(order_total - paid_amount) > tolerance:
            await db.rollback()
            print(f"  [AMOUNT MISMATCH] Order: {order_total}, Paid: {paid_amount}, Tolerance: {tolerance}, Diff: {abs(order_total - paid_amount)}")
            return False, f"Số tiền không khớp: đơn={order_total}, nhận={paid_amount}.", None

        # ... rest of existing logic ...
        
        # CRITICAL: Record transaction in processed_transactions (already done correctly)
        await db.execute(
            """
            INSERT INTO processed_transactions(reference, order_code, amount, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (reference, order_code, amount, datetime.now().isoformat(timespec="seconds")),
        )
        await db.commit()
        # ... return success ...
```

**Notes:**
- The current implementation already has the correct order of operations
- Main changes are adding logging statements for debugging
- The tolerance calculation is already correct (max of 1% or 1000đ)
- Duplicate detection already happens first
- The only enhancement needed is better logging output

### Database Schema Changes

**No schema migrations required**. All necessary tables and indexes already exist:

**Existing Tables Used:**
- `orders`: Contains `payment_link_id` field for order lookup (already indexed)
- `processed_transactions`: Reference TEXT PRIMARY KEY for duplicate detection
- `order_items`: Stores order line items
- `order_accounts`: Stores assigned accounts for paid orders

**Existing Indexes Verified:**
- `idx_orders_payment_link_id`: Critical for fast webhook order lookup
- `processed_transactions.reference`: Primary key provides automatic index for duplicate check

**Runtime Verification Needed:**
- Confirm `idx_orders_payment_link_id` exists (created in db.py line ~145)
- Confirm `processed_transactions` table has PRIMARY KEY on reference column (guarantees uniqueness)
- Confirm transaction isolation level (BEGIN IMMEDIATE) prevents race conditions

**Critical Implementation Order:**
The `mark_order_paid` function MUST follow this exact sequence to prevent race conditions:
1. `BEGIN IMMEDIATE` - acquire write lock
2. Check `processed_transactions` for duplicate - RETURN EARLY if exists
3. Check order exists and status
4. Check order expiration
5. Check amount tolerance
6. Check stock availability
7. Update stock
8. Update order status
9. INSERT into `processed_transactions` - MUST happen in same transaction
10. `COMMIT` - release lock

This ordering ensures that if webhook returns 500 due to Telegram error AFTER step 10, the retry will be caught by step 2. The duplicate check MUST happen before any state changes.

**No Schema Changes Required Because:**
1. `payment_link_id` field already exists and is indexed
2. `processed_transactions.reference` already uses TEXT PRIMARY KEY for uniqueness
3. Amount tolerance is application-level logic, not schema constraint
4. Telegram error handling is application-level, no DB changes needed
5. All lookup queries already use proper indexes

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate each of the 7 root causes on unfixed code, then verify the fixes work correctly and preserve existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate each root cause BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write simulated webhook requests for each root cause scenario and run against the UNFIXED code to observe failures and understand the exact failure modes.

**Test Cases**:
1. **Auth Failure Test**: Send webhook with `Authorization: Bearer key` instead of `Apikey key` (will fail with 401, check logs for detail)
2. **Truncated Code Test**: Send webhook with payment_code="DH1779982" and content="Transfer DH1779982853451" (will fail to find order on unfixed code)
3. **Content-Only Code Test**: Send webhook with payment_code=null, content="DH1779982853451" (may fail if priority wrong)
4. **Amount Tolerance Test**: Send webhook with amount=50005 for order with total=50000 (check if current tolerance works)
5. **Telegram Error Test**: Mock bot.send_message to raise exception (will cause 500 on unfixed code)
6. **Reference Uniqueness Test**: Send webhook with empty transaction_id and reference_code (check if fallback is unique)
7. **Combined Failure Test**: Truncated code + Telegram error (worst case scenario)

**Expected Counterexamples**:
- Auth failures return 401 but logs don't show received vs expected headers
- Truncated payment codes fail to find orders despite full code in content
- Telegram errors cause webhook to return 500 instead of 200
- Non-unique references may allow duplicate processing
- Amount mismatches reject valid payments with minor bank fees

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := sepay_webhook_fixed(input)
  ASSERT result.status_code = 200
  ASSERT order.status = "paid"
  ASSERT customer_received_delivery_message OR telegram_error_logged
  ASSERT processed_transactions.contains(input.reference)
END FOR
```

**Test Approach**: Run simulated webhooks for each root cause scenario against FIXED code and verify:
- Auth failures are logged with full detail
- Truncated codes are extracted from content successfully  
- Orders are found and marked as paid
- Telegram errors are caught and logged without failing webhook
- References are unique and prevent duplicates
- Amount tolerance accepts minor differences

5. Amount tolerance accepts minor differences

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT sepay_webhook_original(input) = sepay_webhook_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for valid webhooks, duplicate webhooks, wrong transfer types, expired orders, and insufficient stock scenarios, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Valid Payment Preservation**: Observe that correctly formatted webhooks with matching codes and amounts work on unfixed code, verify this continues after fix
2. **Duplicate Detection Preservation**: Observe that duplicate transaction references are rejected, verify this continues after fix
3. **Transfer Type Filtering Preservation**: Observe that debit/out transactions are ignored, verify this continues after fix
4. **Expired Order Preservation**: Observe that payments for expired orders are rejected, verify this continues after fix
5. **Stock Validation Preservation**: Observe that insufficient stock causes rollback, verify this continues after fix
6. **Amount Rejection Preservation**: Observe that truly incorrect amounts (outside tolerance) are rejected, verify this continues after fix

### Unit Tests

- Test `verify_webhook_request` with various auth headers and modes, verify logging output
- Test `extract_payment_code` with truncated payment_code and full content, verify longest match
- Test `mark_order_paid` with amounts within and outside tolerance
- Test webhook handler with mocked Telegram API failures
- Test reference uniqueness construction with various input combinations
- Test `get_order_by_payment_code` with multiple orders having same payment_link_id

### Property-Based Tests

- Generate random webhook payloads and verify that valid payments always succeed
- Generate random payment codes (truncated and full) and verify extraction always finds longest match
- Generate random amounts within tolerance and verify acceptance
- Generate random Telegram errors and verify webhook always returns 200
- Generate random transaction references and verify uniqueness
- Test that all non-buggy inputs produce identical results before and after fix

### Integration Tests

- Test full webhook flow from auth to delivery with all 7 root cause scenarios
- Test combined failure scenarios (multiple root causes at once)
- Test edge cases where order lookup has multiple matches
- Test concurrent webhook processing to verify transaction locking works
- Test SePay retry scenarios to verify idempotency
- Test real bank transfer scenarios with actual VietQR codes and SePay webhook format

### Monitoring and Observability Recommendations

After implementing the fixes, add these monitoring practices:

**Log Aggregation:**
- Collect all webhook logs with structured format (JSON)
- Track authentication failure rates by auth_mode
- Track payment code extraction success/failure rates
- Track amount mismatch occurrences with tolerance calculations
- Track Telegram API failure rates by error type

**Metrics to Track:**
- Webhook authentication success rate (should be >99%)
- Order lookup success rate (should be >95% for valid webhooks)
- Payment processing success rate (should be >98%)
- Telegram delivery success rate (acceptable at >80% due to user blocks)
- Average webhook processing time (should be <500ms)
- Duplicate webhook rate (normal to have 1-5% retries)

**Alerts to Configure:**
- Alert if webhook auth failures >5% in 5 minutes
- Alert if order lookup failures >10% in 5 minutes
- Alert if payment processing failures >5% in 5 minutes
- Alert if Telegram failures >50% in 5 minutes (may indicate bot token issue)
- Alert if duplicate transaction rate >20% (may indicate timeout issues)

**Dashboard Widgets:**
- Webhook processing funnel (received → authenticated → order found → payment processed → delivered)
- Error breakdown by root cause (auth, lookup, amount, telegram, etc.)
- Processing time percentiles (p50, p95, p99)
- Recent failed webhooks with full context for debugging

## Testing Strategy

### Validation Approach

- Test `verify_webhook_request` with various auth headers and modes, verify logging output
- Test `extract_payment_code` with truncated payment_code and full content, verify longest match
- Test `mark_order_paid` with amounts within and outside tolerance
- Test webhook handler with mocked Telegram API failures
- Test reference uniqueness construction with various input combinations
- Test `get_order_by_payment_code` with multiple orders having same payment_link_id

### Property-Based Tests

- Generate random webhook payloads and verify that valid payments always succeed
- Generate random payment codes (truncated and full) and verify extraction always finds longest match
- Generate random amounts within tolerance and verify acceptance
- Generate random Telegram errors and verify webhook always returns 200
- Generate random transaction references and verify uniqueness
- Test that all non-buggy inputs produce identical results before and after fix

### Integration Tests

- Test full webhook flow from auth to delivery with all 7 root cause scenarios
- Test combined failure scenarios (multiple root causes at once)
- Test edge cases where order lookup has multiple matches
- Test concurrent webhook processing to verify transaction locking works
- Test SePay retry scenarios to verify idempotency
- Test real bank transfer scenarios with actual VietQR codes and SePay webhook format


---

## Implementation Checklist

Use this checklist during implementation to ensure all fixes are applied:

### Phase 1: Enhanced Logging (Low Risk, High Value)
- [ ] Add detailed authentication failure logging in `verify_webhook_request`
- [ ] Add payment code extraction source logging in `extract_payment_code`
- [ ] Add amount tolerance calculation logging in `mark_order_paid`
- [ ] Add transaction reference logging in webhook handler
- [ ] Add order lookup logging with query details

### Phase 2: Telegram Error Handling (Critical for Stability)
- [ ] Wrap customer delivery message send in try-except
- [ ] Wrap admin notification sends in try-except
- [ ] Log Telegram errors with full exception details
- [ ] Verify webhook returns 200 even when Telegram fails
- [ ] Test with mocked Telegram failures

### Phase 3: Transaction Reference Uniqueness (Critical for Idempotency)
- [ ] Review current fallback reference construction
- [ ] Add timestamp to fallback reference: `sepay-{code}-{amount}-{timestamp}`
- [ ] OR add content hash: `sepay-{code}-{amount}-{hash}`
- [ ] Verify `processed_transactions` check happens first in transaction
- [ ] Test with duplicate webhooks having empty transaction_id

### Phase 4: Verification and Testing
- [ ] Run unit tests for each root cause scenario
- [ ] Run integration tests for combined failure scenarios
- [ ] Test with real SePay webhook payloads (use `/scripts/simulate_sepay_webhook.py`)
- [ ] Verify idempotency with duplicate webhook sends
- [ ] Monitor logs for proper detail level

### Phase 5: Deployment and Monitoring
- [ ] Deploy changes to staging environment
- [ ] Test with real bank transfers on staging
- [ ] Set up log aggregation and alerts
- [ ] Deploy to production
- [ ] Monitor webhook success rates for 24 hours
- [ ] Document any additional edge cases discovered

## Risk Assessment

| Change | Risk Level | Mitigation |
|--------|------------|------------|
| Enhanced logging | Low | Read-only, no logic changes |
| Telegram error handling | Medium | Could mask delivery failures, mitigated by logging |
| Reference uniqueness | Medium | Could break duplicate detection if done wrong, mitigated by testing |
| Amount tolerance | Low | Already implemented, just adding logging |
| Auth failure detail | Low | Informational only, no logic change |

**Overall Risk**: Low-Medium

**Recommended Deployment**: Blue-green deployment with 10% traffic rollout first, monitor for 1 hour, then full rollout.

**Rollback Plan**: If webhook failure rate exceeds 5% after deployment, rollback immediately. The changes are backward compatible, so rollback is safe.

## Success Criteria

After implementation and deployment, success is measured by:

1. **Zero orders lost** - All paid bank transfers result in delivered accounts
2. **<1% webhook failures** - Excludes legitimate rejections (wrong amount, expired orders)
3. **Authentication failures clearly diagnosed** - Logs show exact mismatch
4. **Telegram errors do not cause retries** - All Telegram errors caught and logged
5. **No duplicate order fulfillment** - All retries detected by processed_transactions
6. **Payment code extraction success rate >99%** - Even with truncated codes
7. **Amount tolerance working** - Bank fees up to tolerance accepted

## Conclusion

This design provides a comprehensive fix for all 7 root causes of the SePay webhook order delivery bug. The approach is:

- **Surgical**: Each fix targets a specific root cause without affecting other logic
- **Observable**: Enhanced logging provides visibility into webhook processing
- **Resilient**: Telegram error handling prevents cascading failures
- **Idempotent**: Transaction reference uniqueness ensures no duplicate processing
- **Preservative**: Existing behavior for non-buggy cases remains unchanged
- **Testable**: Clear test cases for each root cause and preservation scenarios

The key insight is that most root causes are already addressed in the current code. The main improvements are adding logging for debugging, wrapping Telegram calls to prevent 500 errors, and ensuring transaction reference uniqueness. These changes will make the webhook handler robust, observable, and reliable for production use.
