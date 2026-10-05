# 1C testbed

The project uses three verification levels.

| Level | Purpose | Backend |
|---|---|---|
| L1 | CI/unit/contract | Fake1C deterministic OData fixture |
| L2 | developer integration | real file-mode 1C accounting test instance with synthetic data |
| L3 | production parity | 1C Server + PostgreSQL/MS SQL equivalent deployment |

## L1 — Fake1C

`testbed/fake1c/` serves deterministic OData-like responses for:
- `$metadata`;
- catalogs;
- documents;
- accounting/accumulation register-shaped fixtures;
- both JSON and Atom response profiles.

This level is fast and must run in CI.

## L2 — real 1C test instance

Do not emulate internal 1C SQL tables. Use a real 1C information base and connect through the same
public integration boundary used by ERP_MCP.

Suggested workstation layout:

```text
D:\1C-Test\
  Accounting\
  snapshots\
  seed\
```

Synthetic seed should cover multiple organizations, counterparties, products/services, warehouses,
bank/cash, sales, purchases, returns, partial payments, overpayments, VAT/accounting movements and
deliberate anomalies.

No real client/personal data belongs in the testbed.

## L3 — production parity

Run the same contract/scenario suite against a server-mode 1C environment and its supported DBMS.

## Snapshot rule

Real-1C integration tests must start from a known snapshot and produce deterministic evidence.
Snapshot restore is an environment operation, not something the MCP production process performs.
