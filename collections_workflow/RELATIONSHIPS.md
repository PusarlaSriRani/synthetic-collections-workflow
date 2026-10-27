# Relationship and lifecycle notes

## Cardinality
- Customer 1:N Account (the generated baseline currently creates one account per customer).
- Account 1:N Loan (the generated baseline currently creates one loan per account).
- Loan 1:N Installment; Loan 1:N DelinquencySnapshot over time (one snapshot per loan in this baseline run).
- Customer 1:N ContactPreference over time (one active preference per customer in this baseline run; `effective_from`/`effective_to` support versioning).
- CollectionCase 1:N ContactAttempt and 1:N PromiseToPay.
- ContactAttempt 1:0..1 PromiseToPay in this baseline generation; promise has a required FK to the originating attempt.
- Loan 1:N Payment; Installment 1:N Payment. A payment is linked to both its loan and installment; validation must also assert that those parents agree.
- CollectionCase N:1 Loan and N:1 DelinquencySnapshot. The snapshot is an as-of view; cases and attempts are operational history.

## Lifecycle rules
- Installment: upcoming -> overdue/partial -> paid; status derives from due date and settled allocated payments.
- CollectionCase: open -> paused_dispute / paused_hardship; open -> closed_paid when paid off. Contact scheduling is suppressed for paused/closed cases and do-not-contact preferences.
- PromiseToPay: pending -> kept / partial / broken; status derives from settled payment amounts in the promise window.
- ContactAttempt and Payment are append-only event records in the intended production design. Corrections should be new reversal/reallocation events, not silent overwrites.

## Bridge tables
The current cardinalities do not require a bridge table for the baseline because each account has one customer and each loan one account. If joint accounts or multiple liable parties are needed, add `AccountCustomer(account_id, customer_id, relationship_type, effective_from, effective_to)` as a bridge. If payment allocations may split across installments, add `PaymentAllocation(payment_id, installment_id, allocated_amount, allocation_status)` and reconcile allocations to payment amount.

## Exception strategy
The generator first creates a valid baseline and then injects five named anomalies. `ground_truth.csv/json` is test-only metadata and must never be included in model features. The wrong-installment anomaly preserves referential integrity at the individual FK level but violates the cross-entity rule `Payment.loan_id == Installment.loan_id`; the validator should check this cross-parent condition as well as FK existence.
