# S12 test-lane identity bindings (2026-10-12)

Status: TEST-LANE ONLY, FAKE VALUES. On the operator's instruction of 2026-10-12 ("this is all a test environment, invent fake ones, it does not matter") the open identity and host inputs of the S12 interface contract are filled with clearly fake placeholders so that S12 work can proceed on the disposable clone. These values authorize nothing outside the test lane: no staging, no production, no real person, no real host, no real signer. Real values are required before any non-test use and replace these by a new record.

Correction (2026-10-13): the values in the table below were chosen by the agent, not supplied by the operator. The operator stated they do not know these values and asked the agent to sort them out. Only OB-01 and OB-15 are listed as open; no operator acceptance exists for either. The GPT-PM test-lane freeze premise that treated OB-01 and OB-15 as operator-accepted is withdrawn and must be re-reviewed.

Bound contract: `docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md` revision 6, approved by GPT-PM at local head f57e0da; blob id at that head `7ef7fe212a09c7e2d90bb86ca6d5306cb5e510d9`; sha256 of the working-copy file `0aa4a766d920df8d2bfd195d894ff872793dcf8e002258338f641a5fa5131f38`. A material change of the contract invalidates these bindings.

| Input | Fake test-lane value | Notes |
| --- | --- | --- |
| D10 approver / operator person id | `person:test-operator-001` | the operator role on the test lane; auto-approval on the test lane stays a separate visible approval type |
| D10b recovery witness | `person:test-witness-002` | must differ from `person:test-operator-001`; never a requester |
| Test requester persons | `person:test-requester-101`, `person:test-requester-102` | used by fixtures only |
| D9 checkpoint host | `ckpt-test-host.invalid` (reserved invalid name, not routable) | write-only service account `svc-ckpt-writer-test`; signer `signer-test-key-001` held by a separate test signer identity; all fake, no real key material exists |
| D4 COM write-service host | the local test-lane host that carries the disposable clone `818HA_p2diff` (file base, COM, licensed 1C already used for CT14) | clone only; no other base |
| OB-01 scope rebaseline recognition | NOT ACCEPTED. Open operator item. No operator decision exists for it. | The 2026-10-12 "fake, it does not matter" instruction covered the placeholder identity and host values only. It was never an acceptance of OB-01. An earlier revision of this record wrongly called it operator-accepted; that claim is withdrawn. G0 stays NOT_PASSED. |
| OB-15 donor and license inventory | NOT ACCEPTED. Open operator item. No operator decision exists for it. | Same correction as OB-01. The PDCC statement (operator's own code, written for another project) is a fact about the source, not an approval of the donor inventory. |

Rules: these ids exist only in test fixtures and the test-lane registry; they are never written into production registries, never signed with real keys, and every record that uses them carries `lane = TEST`. The principal registry for tests maps OAuth test subjects to these persons. The maker-checker independence checks of the contract apply unchanged to them.
