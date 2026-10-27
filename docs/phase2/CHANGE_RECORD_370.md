# Change Record 370 - amount recomputation when a goods line is set (in-memory probe)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session. Evidence and documentation only.
- A COM probe as the clone administrator on the local disposable clone `818HA_p2diff`. It creates a document object in memory
  only: nothing is written, posted or saved (the script has no write call).

## Result (FACT: tool output of this run, exit code 0)

- After setting quantity 2 and price 10 on a new goods row: VAT amount 0.0, line amount 0.0, document total 0.0.
- After then setting the line amount to 20: VAT amount 0.0, line amount 20.0, document total 0.0.
- So, at property-set time in this configuration, setting quantity, price or amount recomputes neither the line VAT amount nor the
  document total, and the line amount is not derived from quantity and price.

## Consequences (INFERENCE)

- The payload carries line amount but no VAT amount and no document total. A draft written exactly from the payload would hold
  a zero VAT amount and a zero document total unless the writer sets them or a write-time handler recomputes them.
- Whether the write itself (module handlers on write) recomputes them was not measured; that needs a write to the clone and is
  the next measurement. The binding set must not claim a complete draft until it is known.

## Not established

- UNKNOWN: write-time recomputation, posting behavior, and behavior of the production base. NOT_RUN: any write, any test.
