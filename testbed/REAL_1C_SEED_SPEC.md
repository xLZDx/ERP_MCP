# Real 1C synthetic seed specification

The L2/L3 test databases must contain **synthetic data only**. No production/client data may be
copied into this testbed.

## Minimum dataset

Target seed:

- 2–3 organizations;
- at least 50 counterparties split between customers and suppliers;
- at least 100 products/services;
- contracts;
- multiple warehouses;
- bank accounts and cash desk;
- multiple currencies where supported;
- incoming/outgoing payments;
- purchases and sales;
- invoices and shipment/receipt documents;
- returns;
- advances;
- open receivables/payables;
- VAT/tax-relevant examples appropriate to the installed configuration;
- accounting movements/postings;
- payroll and fixed-asset examples only when the installed configuration exposes them;
- data spanning 2–3 financial years when edition limits allow it.

## Required edge cases

The deterministic seed must include:

- normal posted operation;
- unposted document;
- deletion-marked object;
- counterparty with incomplete tax identifier data;
- zero amount;
- negative correction;
- likely duplicate counterparty;
- overdue receivable;
- payment without a directly linked invoice;
- partial payment;
- overpayment/advance;
- goods return;
- closed-period example;
- backdated document;
- multiple currencies;
- different VAT/tax treatments where supported.

## Determinism

Every generated scenario must have a stable scenario ID and expected evidence. Tests should not
depend on UI-generated random identifiers unless the resulting identifiers are captured in the
seed manifest.

## Acceptance

At least the 10 scenarios in `testbed/scenarios/accounting_scenarios.json` must be reconciled
against native 1C UI/reports before a real environment receives production GO.
