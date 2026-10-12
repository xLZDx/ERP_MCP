# CT14 extension spike - final status (clone 818HA_p2diff only)

Date: 2026-10-12. Platform 1C:Enterprise 8.3.27.2342, file base, configuration "БухгалтерияДляМолдовы" 3.0.67.1.

## 1. What was built

- Safety copy before any work: `D:\ERP_MCP_Testbed\1c\reference\working\_bak_818HA_p2diff_pre_ext\1Cv8.1CD` (4377796608 bytes, equal to the clone file at copy time). The clone was not restored; no restore was needed.
- Extension `CT14Cust` (purpose Customization, no modules, no handlers), sources in `testlane/onec_extension/CT14Ext/`:
  adopted `Document.ПоступлениеТоваровУслуг` with own attributes `CT14ИдентификаторИзменения` String(36, indexed) and `CT14ХешИзменения` String(64);
  role `CT14Писатель`; 52 adopted base objects (empty adoption) that the role needs (see section 5).
- APPLIED and ACTIVE in the base (evidence: `ct14_check_ext.py` earlier: attr_count 75 = 73 + 2, both CT14 attributes and the role visible through COM, query on the attribute OK; and the full measurement below ran against it).
- Left on the clone, not deleted: extension `CT14Ext` (first attempt, purpose AddOn, DEACTIVATED), test drafts of purchase receipts (markers `CT14-ITER-MARKER-0001`, six `CT14-PRUNE-*`, `CT14M-86f4a165d45e44e2`; all unposted), infobase user `CT14_NARROW` (its roles are currently the standard accounting roles from measurement phase B) and its Users catalog item. Cleanup is for the operator.

## 2. Platform commands used (credentials injected in memory by `scripts/ct14_common.py`)

`1cv8.exe DESIGNER /F <clone> /N <user> /P <pwd> <command> /Out <log>` with:
`/DumpDBCfgList -AllExtensions`; `/DumpConfigToFiles <dir> [-Extension <name>]` (skeleton and base uuids); `/LoadConfigFromFiles <CT14Ext dir> -Extension CT14Cust` (creates the extension); `/CheckConfig -Extension CT14Ext`; `/UpdateDBCfg -Extension CT14Cust`. Before the update the extension flag "warn about dangerous actions" is turned off through COM (`ct14_ext_flags.py CT14Cust protect=0 safe=0`).

## 3. Defects found on the way (exact evidence)

| Symptom | Cause | Evidence / fix |
| --- | --- | --- |
| `/UpdateDBCfg -Extension` exit 101, empty log, one run hung ~10 min | Dangerous-action protection of a new extension | Event log `DBConfigExtensionUpdateError`: "Security warning ... Attempting to open "CT14Ext"". Fixed by the COM flag above |
| Load exit 1 or hang with no log | Designer shows a modal error dialog even in batch mode | Read through UI Automation (`designer_dialog.ps1`, built into `run_designer`): "document format error: unexpected read property. Current property: InformationRegister, expected property: ChildObjects." Adopted objects need `<ChildObjects/>` |
| Update ok but attributes/role invisible to sessions | Purpose AddOn | `Field not found "Д.CT14ИдентификаторИзменения"`; the same content as Customization is visible. Purpose cannot be changed: "Cannot change the extension purpose because the extension affects data structures" |
| Update exit 1 | Same internal ids in two extensions | "Some internal IDs overlap with the 'CT14Ext' configuration extension" (`ct14_regen_ids.py`) |
| Adopted object ids | Extension object needs NEW own uuid and generated TypeIds; only `ExtendedConfigurationObject` carries the base uuid | Compared with the dump of an existing extension |
| Role rights on base objects ignored | A role in an extension only carries rights for objects the extension adopts | `ПравоДоступа` false for `РегистрСведений.КурсыВалют` until it was adopted |
| BSP failure for the narrow user | Session parameter needs a Users catalog item bound to the infobase user | "Пользователь "CT14_NARROW" не найден в справочнике "Пользователи"" |

## 4. Measurements (as CT14_NARROW with ONLY CT14Писатель + ЗапускВнешнегоСоединения unless stated; raw output of `scripts/ct14_measure.py`)

| Capability | Result | Evidence |
| --- | --- | --- |
| Marker written in the same write as a new draft | SUPPORTED | `Записать(Запись)` of a copied receipt with both attributes set; read back equal; document not posted |
| Written through COM object property access | SUPPORTED | `o.CT14ИдентификаторИзменения = ...` via the external connection |
| Equality query by the attribute | SUPPORTED | `ГДЕ Д.CT14ИдентификаторИзменения = &М` returns 1; the attribute is indexed. Comment text search by the old comment returns 0 after a comment edit (the unbounded Комментарий is not a reliable marker) |
| Marker survives a user edit of Комментарий | SUPPORTED | Standard-role user edited the comment, count by marker still 1 |
| Marker immutable for a non-writer user | UNSUPPORTED (by roles) | A user with only standard accounting roles changed the marker programmatically: "marker change WRITTEN by non-writer", value became TAMPERED (restored by admin afterwards). Attribute-level View/Edit rights are interface rights: the writer role itself has attribute Edit = false by `ПравоДоступа` and still wrote the marker; the standard roles give attribute View/Edit = true by inheritance from document Update. Only a BeforeWrite handler in the extension (excluded by the brief) or a hash/integrity check by the consumer can detect tampering |
| Record-level restriction on reading receipts | Not reproduced | Both the writer role and the standard-role user read receipts by marker and by source query without restriction in this run; the custom role never triggered it |
| Create draft, post, read movements by registrar, read lines, unpost | SUPPORTED | posted = true; 39 movement registers read (nonzero: `РегистрНакопления.НДСПредъявленный` 1, `РегистрБухгалтерии.Хозрасчетный` 2); lines read (Услуги 1); unposted = true; marker intact after post |
| Stale-version rejection | SUPPORTED | Second object snapshot write fails: "Operation cannot be performed due to version mismatch or lack of database record (entry may have been modified or deleted)!"; `ВерсияДанных` changes on write and a stale snapshot differs |
| Add payment documents denied | SUPPORTED | `ПравоДоступа("Добавление")` false for ПлатежноеПоручение, РасходныйКассовыйОрдер, СписаниеСРасчетногоСчета, ПриходныйКассовыйОрдер, ПоступлениеНаРасчетныйСчет, ПлатежноеТребование, ОплатаПлатежнойКартой (also Изменение, Удаление false); `СоздатьДокумент().Записать()` on ПлатежноеПоручение and РасходныйКассовыйОрдер: "Access violation!" |
| Delete denied | SUPPORTED | receipt Удаление, ИнтерактивноеУдаление, ИнтерактивнаяПометкаУдаления, ИнтерактивноеУдалениеПомеченных all false; `Удалить()` attempt: "Access violation!" (called only because the right was false) |
| No administration | SUPPORTED | Администрирование, АдминистрированиеДанных, ОбновлениеКонфигурацииБазыДанных false; catalog Изменение false for ДоговорыКонтрагентов, Склады, Контрагенты, Номенклатура |

## 5. Final minimal right list of `CT14Писатель` (52 objects; no Delete, no Interactive*, no administration)

- `Document.ПоступлениеТоваровУслуг`: Read, Insert, Update, Posting, UndoPosting; attributes `CT14ИдентификаторИзменения` and `CT14ХешИзменения`: View, Edit (interface rights; they evaluate false for this role, see section 4).
- `Sequence.ДокументыОрганизаций`: Read, Update (removing Update fails at post: "РаботаСПоследовательностямиСобытия.Модуль(122) ... Access violation").
- Read only: `Document.СчетФактураПолученный`; Catalogs ДоговорыКонтрагентов, Склады, ИдентификаторыОбъектовМетаданных; Constants ОграничиватьДоступНаУровнеЗаписейУниверсально, ПервоеОбновлениеДоступаЗавершилось; AccountingRegister Хозрасчетный; 19 AccumulationRegisters and 21 InformationRegisters (the 39 movement registers of the receipt plus КурсыВалют, НастройкаВремениДокументов).
- Get only: session parameters ВыполняетсяОбновлениеИБ, ПараметрыОбработчикаОбновления, ОтключениеОбновленияКлючейДоступа, ОграничениеДоступаНаУровнеЗаписейУниверсально.
- Pruning (one removal per Designer rebuild, full chain re-run each time): Update/Insert on Catalog.Склады and ДоговорыКонтрагентов and Update on InformationRegister.КурсыВалют were removable (posting writes movements without register Update). Update on the sequence was not removable. Read rights were added only after a real denial; they were not pruned individually.
- The exact list is in `scripts/ct14_rights_state.json` and `CT14Ext/Roles/CT14Писатель/Ext/Rights.xml`.
- The coordinator's bulk "Read on everything" approach was NOT used: the iteration (about 40 rounds of about 1 minute each, driven by event-log AccessDenied events) already converged on a verified minimal set, and bulk Read would contradict least privilege and require adopting thousands of objects.

## 6. Residual risks and not done

- Marker immutability is not enforceable by roles for API/COM writers (section 4). Mitigation outside this scope: BeforeWrite handler in the extension, or a hash/consumer-side integrity check (the `CT14ХешИзменения` attribute exists for that).
- The attributes are visible in the document UI (extension attributes of an adopted document); the writer role itself has no interactive rights.
- Configuration upgrade drift: adopted objects are mapped by id; a base configuration update that changes adopted objects requires the extension to be re-synchronised (Designer: update adopted objects), and the 52 adopted objects widen that surface.
- Designer exclusivity: every Designer run needs no open sessions; a modal error dialog blocks a batch run until dismissed (handled by the UI Automation watcher). The role discovery depends on event-log AccessDenied entries; session parameters and some objects are named only in the error text.
- Not verified: behavior on any base other than the clone, in staging or production; UI-level behavior; the earlier record-level restriction could not be reproduced (cause unknown).
