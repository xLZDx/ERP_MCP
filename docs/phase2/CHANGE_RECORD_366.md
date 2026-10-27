# Change Record 366 - value types of the CREATE_DRAFT destinations (read-only)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Evidence only: `docs/phase2/artifacts/CT14_DRAFT_DESTINATION_TYPES_2026-10-27.json`. Follows Change Record 365 (draft crosswalk).
- A read-only COM session as the clone administrator on the local disposable clone `818HA_p2diff`; metadata names, types and
  qualifiers only. No rows, no write, no credentials in the output (exit code 0).

## Result (FACT: from the saved JSON)

| Destination | Type |
|---|---|
| header `Организация` | reference to catalog `Организации` |
| header `Контрагент` | reference to catalog `Контрагенты` |
| header `ДоговорКонтрагента` | reference to catalog `ДоговорыКонтрагентов` |
| header `НомерВходящегоДокумента` | string, length 30 |
| header `ДатаВходящегоДокумента` | date and time |
| header `ВалютаДокумента` | reference to catalog `Валюты` |
| header `Комментарий` | string, unlimited length |
| `Товары.Номенклатура` | reference to catalog `Номенклатура` |
| `Товары.Количество` | number 15,3 |
| `Товары.Цена`, `Товары.Сумма`, `Товары.СуммаНДС` | number 15,2 |
| `Товары.СтавкаНДС` | reference to enumeration `СтавкиНДС`, 20 values (for example `НДС20`, `НДС12`, `НДС6`, `НДС0`, `БезНДС`) |

## Consequences for the crosswalk (INFERENCE)

- Five references need a lookup by the identifier carried in the payload; none can be set as text.
- `supplier_document_number` longer than 30 characters cannot be stored; the writer must refuse, not truncate.
- `supplier_document_date` is a date but the destination is date-time; the time part must be fixed explicitly.
- `vat_rate_code` needs an explicit code-to-enumeration table; the list has several near-duplicate values, so the table must be
  reviewed, not guessed. Prices and amounts carry two decimals, quantity three.

## Not established

- UNKNOWN: the date composition qualifier, how payload identifiers map to catalog items, and whether setting `Сумма` recomputes
  `СуммаНДС` and the document total (needs a write measurement on the clone). Nothing here authorizes composition or a write.

## Verification state

- RUN: the read-only script once. NOT_RUN: any write, any test, GPT-PM review of this record.
