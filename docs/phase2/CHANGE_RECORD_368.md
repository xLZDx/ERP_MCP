# Change Record 368 - VAT enumeration usage in the clone's receipt lines (read-only)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session. Documentation and counts only.
- A read-only COM query as the clone administrator on the local disposable clone `818HA_p2diff`: line counts per VAT
  enumeration value in the goods lines of `ПоступлениеТоваровУслуг`. No amounts, no names, no document identifiers are saved.

## Result (FACT: tool output of this run, exit code 0)

| Enumeration value | Goods lines |
|---|---|
| `БезНДС` | 69 |
| `НДС18` | 751 |
| `НДС10` | 4 |

- The clone never uses `НДС_10`, `НДС20`, `НДС0` or any advance, import or reverse-taxation value in receipt lines.

## Consequences for Change Record 367 (INFERENCE)

- `VAT10` can be mapped to `НДС10`: it is the only ten-percent value present in real receipt lines. This is usage evidence from
  one clone, not a rule of the configuration; the mapping still needs review.
- `VAT0` to `НДС0` and `VAT20` to `НДС20` stay name-based: the clone holds no line with either value, so nothing shows how
  this configuration treats them.
- The clone data contains an eighteen-percent rate that the synthetic vocabulary does not cover; a payload with that rate has no
  mapping and must be refused, like any other unmapped code.

## Wording correction to Change Record 367 (GPT-PM minor N-01)

- The statement that the only VAT codes in the repository are synthetic is too broad (a test uses the literal `"20"`). The accurate
  statement is: the synthetic-data vocabulary contains `VAT0`, `VAT10` and `VAT20`; no closed production VAT vocabulary exists.

## Not established

- UNKNOWN: recomputation of totals when `Сумма` is set (needs a write measurement); direct source assertion of the 32-character
  limit and focused tests of valid length, overlength, unmapped code and refusal path (GPT-PM minor N-02).

## Verification state

- RUN: the read-only query once. NOT_RUN: any write, any test, GPT-PM review of this record.
