# Bugfix Requirements Document

## Introduction

This document specifies the fix for a critical bug in the SePay webhook payment processing flow. When customers make payments via Vietnamese bank transfer (VietQR/SePay), the money successfully arrives in the bank account and SePay sends a webhook to `/webhook/sepay`, but the order status fails to change to "paid" and customers do not receive their purchased accounts.

This bug causes:
- Customer frustration (paid but didn't receive product)
- Manual admin intervention required
- Revenue loss if customers abandon orders
- Support overhead

The fix must ensure that valid payment webhooks reliably trigger order fulfillment while preventing double-processing and preserving existing behavior for edge cases.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN SePay webhook authentication fails (incorrect header format or missing credentials) THEN the webhook returns 401 and SePay retries indefinitely but the order never gets marked as paid

1.2 WHEN the payment code in webhook payload is truncated (e.g., "DH1779982" instead of "DH1779982853451") THEN the system fails to find the matching order and returns 400

1.3 WHEN the payment code exists in transaction content but not in the `payment_code` field THEN the system may fail to extract the payment code correctly

1.4 WHEN webhook payload amount exactly matches order total but the order lookup fails due to `payment_link_id` mismatch THEN the order is not found and payment is not processed

1.5 WHEN strict amount comparison rejects payments with minor bank fee differences (e.g., customer pays 50,005đ for 50,000đ order) THEN the order is rejected with "amount mismatch" error

1.6 WHEN Telegram API fails while sending delivery message (network error, bot blocked by user, invalid chat_id) THEN the webhook returns 500, SePay retries, but duplicate detection may fail causing double-processing

1.7 WHEN the transaction reference ID is not unique or missing THEN duplicate payments may be processed multiple times for the same order

### Expected Behavior (Correct)

2.1 WHEN SePay webhook authentication fails due to misconfiguration THEN the system SHALL return 401 with clear error message AND log the authentication failure details for debugging

2.2 WHEN payment code is truncated in the `payment_code` field but exists fully in transaction `content` field THEN the system SHALL extract the longest matching DH code from content using regex pattern `DH\d+`

2.3 WHEN extracting payment code from webhook THEN the system SHALL prioritize searching transaction content over the `payment_code` field AND select the longest match found

2.4 WHEN looking up order by payment code THEN the system SHALL search using `payment_link_id` field AND prioritize "pending" status orders over other statuses

2.5 WHEN comparing payment amount to order total THEN the system SHALL allow tolerance of max(1% of order total, 1000đ) to account for bank fees

2.6 WHEN Telegram API fails during delivery message or admin notification THEN the system SHALL catch the exception, log the error, continue processing, and return 200 success to prevent SePay retry

2.7 WHEN processing a webhook transaction THEN the system SHALL use transaction_id as primary reference, falling back to reference_code, and construct a unique reference from payment_code+amount if neither exists AND check `processed_transactions` table before processing

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a webhook for an already-processed transaction arrives (duplicate webhook) THEN the system SHALL CONTINUE TO return success (200) without reprocessing using the `processed_transactions` table

3.2 WHEN webhook transfer_type is "debit" or "out" (money going out) THEN the system SHALL CONTINUE TO ignore the transaction and return success without processing

3.3 WHEN order status is already "paid" THEN the system SHALL CONTINUE TO skip payment processing and return success to prevent double-fulfillment

3.4 WHEN order has expired (past expires_at timestamp) THEN the system SHALL CONTINUE TO reject the payment and mark order as "expired"

3.5 WHEN product stock is insufficient after payment confirmation THEN the system SHALL CONTINUE TO reject the payment and rollback the transaction

3.6 WHEN account assignment fails due to insufficient available accounts THEN the system SHALL CONTINUE TO return the appropriate error message without affecting payment confirmation

3.7 WHEN non-buggy payment conditions occur (correct auth, correct payment code, matching amount, valid order) THEN the system SHALL CONTINUE TO mark order as paid, assign accounts, clear customer cart, send delivery message, and notify admins
