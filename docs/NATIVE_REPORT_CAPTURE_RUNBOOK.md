# Native 1C report capture runbook (818HA reference clone)

Status: **PROPOSED** until the accountant approves the ten-case list in section 7. No business figure appears in this
document; expected values stay in the private testbed (`D:\ERP_MCP_Testbed\1c\reference\native_reports\`), never in Git.

## 1. Why this exists

Every semantic story of the real-1C L2 lane ends as `SEMANTIC_PROFILE_UNVALIDATED` because a profile can be validated only by
`scripts/semantic_profiles.py validate` with **at least ten distinct `NATIVE_UI_REPORT` cases, each with a 64-hex report
sha256** (`scripts/real1c/evidence.py`). This runbook says what to capture, who captures it and how it is recorded.

## 2. Evidence classes (what counts)

| Class | Produced by | Counts for `validate` |
|---|---|---|
| `NATIVE_UI_REPORT` | A person runs a standard report in the 1C client and exports it | **Yes**, the only class that counts |
| `NATIVE_ENGINE_REPORT` | `scripts/real1c/native_engine_reports.py` runs the same standard report objects through the 1C engine as the read-only reader | No (comparison and preparation only) |
| `NATIVE_COM_QUERY` | Read-only 1C queries of the lane oracle | No (comparison only) |

The engine report removes the typing work and lets the accountant compare a screen with an exported sheet quickly. It does not
replace the human step: nobody compared it with what the 1C client shows.

## 3. Roles

- **Accountant / owner of the 818HA data** runs the reports in the 1C client, signs each case PASS or FAIL, approves the list in
  section 7 and supplies external documents (bank statements, filed declarations with receipts, supplier PDFs, customs acts).
- **Operator** runs `validate` with the evidence file and owns the decision on the profile mapping.
- **Engineering** prepares the engine reports, hashes files and keeps the evidence manifest consistent. Engineering never
  signs a case PASS.

## 4. Capture rules

1. Use the disposable reference clone and the reference period 2026-08-01..2026-08-31 (copy date 2026-09-15).
2. Record the report name, filters, analytics and generation timestamp for every case.
3. Export the native report (XLSX or MXL) or keep enough native UI evidence to reproduce the value.
4. Hash the file: `Get-FileHash -Algorithm SHA256 <file>`.
5. Store the file and `evidence.json` under the private `native_reports/captures/<case_id>/` folder, never in Git, logs or chat.
6. **Never use ERP_MCP output as the expected value.**
7. If the native report granularity differs from the candidate calculation, mark the case `INCONCLUSIVE`.

## 5. Engine reports (optional preparation)

```text
$env:PYTHONPATH = '.'
python -m scripts.real1c.native_engine_reports [--report <name>]
```

- Identity: always `ERP_MCP_TEST_READER` (DPAPI secret, fixed path). There is no user argument, no environment switch and no
  `Admin_1C` fallback.
- The reader is **not write-free** in 1C terms: a read-only `AccessRight` sweep found Insert/Update/Delete rights on some
  service catalogs and registers (HR attached-file catalogs, report variants and settings, HR classifiers). No document,
  accounting register or chart of accounts is writable and the reader has no Administration right. The sweep is recorded in the
  run manifest (`reader_write_rights`) and the run is refused if the reader may write documents, accounting registers or charts
  of accounts, or administer the configuration. Removing the remaining rights is an operator decision on the clone.
- Gates before any report: reader write denial on the disposable probe clone must be `PASS_WRITE_DENIED` (only a genuine 1C
  rights refusal counts; any other error is inconclusive and refuses the run); the reference
  manifest hash is verified; the metadata fingerprint and every table count the reader can read must equal the reference
  manifest baseline; after the run the readable fingerprint must be identical. The reader cannot read every table, so the
  manifest records the coverage (`fingerprint_coverage`). Any mismatch voids the outputs.
- Allowlisted reports (data composition route): `ДоходыРасходы`, `ДоходыИРасходыПоДокументам`, `ОстаткиДенежныхСредств`,
  `ОстаткиТоваров`, `ДвижениеТоваров`, `ЗадолженностьПоставщикам`, `ВзаиморасчетыСКонтрагентами`.
- Module-driven standard reports (trial balance, account card, account turnovers, `КнигаПокупок_МД`) return an empty sheet when
  executed through an external connection because their composition lives in an interactive form. They are recorded
  `EMPTY` or `UNAVAILABLE`, not retried and not elevated; the accountant produces them in the 1C client.
- Output: `D:\ERP_MCP_Testbed\real1c_e2e\private_evidence\native_engine_reports\run_<timestamp>\*.xlsx` and `manifest.json`
  (class `NATIVE_ENGINE_REPORT`, `validating: false`). The generator refuses to write inside the repository.

## 6. Recording a case

`native-evidence.json` (the file passed to `validate --evidence-file`; keep it outside Git):

```json
{
  "native_reconciliation_cases": [
    {
      "case_id": "NR-02",
      "status": "PASS",
      "evidence_class": "NATIVE_UI_REPORT",
      "native_report_ref": "native_reports/captures/NR-02/native_report.xlsx",
      "native_report_sha256": "<64 hex characters>",
      "report_name": "<1C report name as shown in the client>",
      "period": "2026-08-01..2026-08-31",
      "generated_at": "<ISO timestamp shown by the client>",
      "signed_by": "<accountant>"
    }
  ]
}
```

`status` is `PASS` only when the accountant compared the native figure with the gateway answer and they agree; otherwise
`FAIL` or `INCONCLUSIVE`. Only `PASS` cases with a valid sha256 count, and the guard needs ten distinct `case_id` values.

## 7. The ten cases (PROPOSED, for accountant approval)

| Case | What is confirmed | Native report to run in the 1C client | Story groups it supports (indicative) |
|---|---|---|---|
| NR-01 | Month-close overall status | Trial balance plus the regulated month-close and cost-allocation operations | month-close verdict, closing completeness |
| NR-02 | Account 216.1 ending balance at 31.08 | Account card or trial balance for 216.1 | balance and turnover semantics |
| NR-03 | Account 811.1 August turnover | Account card for 811.1 | balance and turnover semantics, closing of income and expense |
| NR-04 | Account 821 August turnover | Account card for 821 with cost-allocation detail | closing of income and expense |
| NR-05 | Account 211 negative positions | Analytic trial balance by item and warehouse | inventory semantics |
| NR-06 | Account 211 positions without August movement | Movements by item and warehouse for August | inventory semantics |
| NR-07 | Account 241.1 cash balance and end-of-day sign | Cashbook or account card by cash desk and day | cash semantics, cash limit |
| NR-08 | The 21 supplied invoices are located | Purchase and receipt documents and the VAT purchase register | invoice reconciliation |
| NR-09 | Payments with missing receipts | Bank, advance-report and purchase documents | invoice reconciliation |
| NR-10 | Receipts of 31.08 without source documents | Receipt register for 2026-08-31 | document-date semantics |

Additional scenarios after the ten mandatory cases: settlements with suppliers and customers by counterparty and contract,
the July and August VAT registers, supplier card and tax id, and item detail for the largest receipts.

Accountant approval: ____________________  date: ____________  (list approved / changes requested)

## 8. What cannot be generated

Bank statements, filed declarations with their receipts, supplier PDFs, customs acts, e-Factura registers and the
accountant's PASS decision are external. Engineering does not fabricate them and the lane never infers them.

## 9. After ten PASS cases

The operator runs `scripts/semantic_profiles.py validate --profile-id <id> --evidence-file native-evidence.json --actor <id>`.
Validation rechecks source metadata fingerprints, acknowledged drift, exact scope, every mapping's explicit confirmation and
the ten-case evidence set; failure leaves the profile unvalidated. Note that `payable.balance` and `receivable.balance` need an
accumulation register of settlements with counterparties; none was found among the 76 accumulation registers of the 818HA
configuration (supplier settlements are booked on account 521 in the accounting register, whose published OData record has no
sub-account fields for the counterparty). The mapping decision belongs to the operator.
