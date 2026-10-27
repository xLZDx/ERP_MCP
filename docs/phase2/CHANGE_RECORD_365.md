# Change Record 365 - draft payload-to-1C crosswalk for CREATE_DRAFT

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Documentation only: a DRAFT destination map for the one qualified payload shape (a single line). No source, binding or COM
  change. Sources: `src/erp_mcp_private_writer/com_manifest.py` (payload leaves must equal the bound paths exactly;
  `duplicate_override` and `expected_target_version` are control-only) and
  `docs/phase2/artifacts/CT14_METADATA_INVENTORY_IVAN_2026-10-27.json` (document `ПоступлениеТоваровУслуг`, 73 attributes,
  section `Товары` with 26 columns).

## Draft map (INFERENCE: names match by meaning; none has been written or read back)

| Payload path | 1C destination | Present in inventory | Open question |
|---|---|---|---|
| `organization_ref` | header `Организация` | yes | reference type must be resolved from the ref, not set as text |
| `counterparty_ref` | header `Контрагент` | yes | same |
| `contract_ref` | header `ДоговорКонтрагента` | yes | the contract must belong to the counterparty |
| `supplier_document_number` | header `НомерВходящегоДокумента` | yes | length limit not read |
| `supplier_document_date` | header `ДатаВходящегоДокумента` | yes | date, not date-time |
| `currency` | header `ВалютаДокумента` | yes | code to reference resolution |
| `comment` | header `Комментарий` | yes | none |
| `lines[0].item_ref` | `Товары.Номенклатура` | yes | reference resolution |
| `lines[0].quantity` | `Товары.Количество` | yes | none |
| `lines[0].price` | `Товары.Цена` | yes | none |
| `lines[0].vat_rate_code` | `Товары.СтавкаНДС` | yes | the code must map to an enumeration value; the list is not read |
| `lines[0].amount` | `Товары.Сумма` | yes | the platform may recompute `СуммаНДС` and totals; this must be measured |
| `duplicate_override`, `expected_target_version` | none (control only) | n/a | n/a |

## Not established

- UNKNOWN: value types and lengths, reference lookups, the enumeration behind `vat_rate_code`, and whether setting `Сумма`
  triggers recomputation of `СуммаНДС` and `СуммаДокумента`. These need a read-only value-type inventory or a measurement on the
  clone before the map may become a reviewed binding set.
- Nothing here authorizes composition or a write. The writer stays UNQUALIFIED and disabled.

## Verification state

- RUN: comparison of names against the saved inventory (all 12 destinations found). NOT_RUN: any COM call, any test.
