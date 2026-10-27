# Synthetic Collections Workflow Dataset

## Purpose
A deterministic, wholly synthetic dataset for testing fair, explainable delinquency prioritization, contact scheduling, promise tracking and payment reconciliation. No real personal or financial data is used.

## Reproduce
```bash
python generate_data.py --loans 10000 --seed 20261022 --out output
```
For a quick starter set: `python generate_data.py --loans 100 --seed 20261022 --out starter_output`. The same seed and scale produce byte-identical logical rows; SQLite file bytes may vary by runtime version.

## Files
- One CSV and JSON file per entity: Customer, Account, Loan, Installment, DelinquencySnapshot, ContactPreference, ContactAttempt, PromiseToPay, Payment, CollectionCase.
- `ground_truth.csv/json`: labelled injected exceptions and expected safe decisions; **exclude from model features**.
- `data_dictionary.json`: field types, requirements, enums, units and validation guidance.
- `collections_seed.sqlite` and `seed.sql`: SQLite schema and seed data.
- `source_manifest.json`, `checksums.json`, `validation_summary.json`: provenance, integrity evidence and row counts.

## Core decisions
- DPD = days from the oldest unpaid due installment to the snapshot date, floored at zero.
- Arrears = sum of outstanding amounts on due installments.
- Score = capped combination of arrears (0–30), DPD (0–40) and risk band (5/15/25), capped at 100. This is an operational prioritization aid, not a creditworthiness or legal decision.
- Disputed cases and hardship cases are paused for review; do-not-contact preferences suppress proactive scheduling. No threats, repeated-contact escalation, or legal-status assumptions are encoded.
- Contact window is local time in Asia/Kolkata, with customer-specific allowed start/end values.
- Promise status is reconciled from settled payments between promise date and due date.

## Known limitations / review notes
- A 3-installment-per-loan schedule gives exactly 30,000 installments for 10,000 loans and spans up to 12 months.
- `ground_truth` anomalies are intentionally injected after baseline generation; related reconciliation checks can therefore fail by design. Treat these as exception-path test fixtures, not clean production records.
- This starter uses one account per customer and one loan per account. The schema supports extension to multiple loans/accounts with bridge tables if the business needs many-to-many relationships.
- Review local consumer-protection, privacy, contact-time and debt-collection requirements before any real-world deployment.
