# Change Record 372 - CORRECTION: the VAT enumeration names do not match their rates

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session. Evidence and documentation only.
- Artifact: `docs/phase2/artifacts/CT14_VAT_ENUMERATION_SEMANTICS_2026-10-27.json`. Read-only COM queries as the clone
  administrator on the local disposable clone `818HA_p2diff`; metadata synonyms and aggregate sums only.

## Correction (my error)

Change Records 367 and 368 mapped payload codes to enumeration values "by name" (`VAT20` to `НДС20`, `VAT10` to `НДС10`). The
enumeration synonyms show that this is wrong in this configuration (a Moldovan accounting configuration whose value names are
legacy):

| Enumeration value | Synonym (the rate the user sees) |
|---|---|
| `НДС18` | 20% |
| `НДС10` | 8% |
| `НДС_10` | 10% |
| `НДС0` | 0% |
| `НДС20` | "(not used) 20%" |
| `НДС12`, `НДС6`, `НДС15` | 12%, 6%, 15% |
| `БезНДС` | no VAT |

- The aggregates agree with the synonyms. Lines stored with `НДС18` carry a VAT amount of 16.666% of the line amount, which is
  20/120 for an amount that includes VAT. Lines stored with `НДС10` carry 7.406%, which is 8/108.
- Consequences: the earlier draft `VAT20` to `НДС20` would have selected an unused value, and `VAT10` to `НДС10` would have
  booked 10% goods at 8%. The mapping must be `VAT20` to `НДС18`, `VAT10` to `НДС_10`, `VAT0` to `НДС0`, and an eight-percent
  code, if the contract ever has one, to `НДС10`.
- The 4 lines the clone holds at `НДС10` are eight-percent lines, so the usage evidence of Change Record 368 does not support
  `VAT10` to `НДС10`. That record's conclusion is withdrawn.
- Nothing was wired into code: the production binding set is still empty, so no wrong mapping ever reached an assignment.

## Line VAT amount rule (INFERENCE from the aggregates)

- In this clone every receipt has the flag "amount includes VAT" set. For rated lines the stored VAT amount equals the line amount
  times rate / (100 + rate), within rounding (differences of a few units over millions); one rated line has a zero VAT amount.
- Change Record 371 showed that the platform does not compute the line VAT amount on write. A writer that must produce a
  complete draft therefore has to compute it from the reviewed rate and set it explicitly, or deliberately leave it zero; this
  is a design decision and an accounting-rule review item, not settled here.

## Not established

- UNKNOWN: the rounding rule of the platform's own form, behavior with the flag unset, other configurations, and whether the
  payload contract should carry the rate as a number instead of a code. NOT_RUN: any test, GPT-PM review of this record.

## Addendum (GPT-PM minor N-02): the includes-VAT flag

- A read-only count of all receipt documents in the clone grouped by the flag "amount includes VAT" returned a single group:
  true, 740 documents. So "every receipt has the flag set" holds for this clone (no false and no empty values); the aggregates above
  therefore cover all rated lines.
