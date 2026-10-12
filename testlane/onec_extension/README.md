# CT14 extension spike (disposable 1C clone only)

Configuration extension `CT14Cust` (sources in `CT14Ext/`) that adds, to the document `ПоступлениеТоваровУслуг`,
two attributes `CT14ИдентификаторИзменения` (string 36, indexed) and `CT14ХешИзменения` (string 64), and a
least-privilege role `CT14Писатель`. The extension has no modules and no handlers; it does not change base behavior.

## Clone-only guard

`scripts/ct14_common.py` refuses to run unless the target folder name is exactly `818HA_p2diff`
(`guard()`), and every script goes through it. Credentials are never stored in this folder: they are
read from DPAPI-protected files under `D:\secrets\erp_mcp` inside the Python process and injected into the
Designer command line / COM connection string only in memory. The infobase user `CT14_NARROW` gets a fresh
random password on each run (`ct14_narrow_ops.prepare_user`), kept in memory only.

## Rebuild on a clone

Run with the project interpreter and `MSYS_NO_PATHCONV=1` when starting from Git Bash (Git Bash otherwise
rewrites Designer's leading-slash arguments). No `1cv8` process may be running (Designer needs exclusive access).

1. Make a safety copy of `1Cv8.1CD` first (about 4.4 GB).
2. `ct14_build.py --noupdate`: `1cv8.exe DESIGNER /F <clone> /N <user> /P <pwd> /LoadConfigFromFiles CT14Ext -Extension CT14Cust /Out <log>`.
   This creates the extension if it does not exist (COM `РасширенияКонфигурации.Создать()` cannot name it).
3. `ct14_ext_flags.py CT14Cust protect=0 safe=0`: turns off the dangerous-action warning of this extension.
   Without it `/UpdateDBCfg -Extension` exits 101 with an empty log; the event log shows
   `DBConfigExtensionUpdateError`: "Security warning ... Attempting to open <extension>".
4. `1cv8.exe DESIGNER ... /UpdateDBCfg -Extension CT14Cust`, then `ct14_check_ext.py` must report both attributes and the role.

Hard-won constraints: the extension purpose must be Customization (an AddOn extension's objects were not visible
to sessions, and the purpose cannot be changed once data structures are affected); objects adopted from the base
must carry NEW own uuid / generated type ids and only `ExtendedConfigurationObject` holds the base uuid; two
extensions must not share internal ids (`ct14_regen_ids.py`). A role in an extension can only carry rights for
objects the extension adopts, so every base object the role needs must be adopted (`ct14_iterate.py` does this
from the base dump, which comes from `/DumpConfigToFiles <dir>` of the clone; read-only).

## Scripts (`scripts/`)

| Script | Purpose |
| --- | --- |
| `ct14_common.py` | Guard, credentials, Designer runner |
| `ct14_build.py` | Load sources (+ optional `/UpdateDBCfg`) |
| `ct14_ext_flags.py` | Active / safe mode / warning flags of a `CT14*` extension through COM |
| `ct14_check_ext.py` | Verify attributes, role and a query on the attribute |
| `ct14_iterate.py`, `ct14_rights_state.json` | Discover the minimal rights iteratively from event-log AccessDenied events |
| `ct14_narrow_ops.py`, `ct14_rightcheck.py` | Operations and `ПравоДоступа` checks as `CT14_NARROW` |
| `ct14_measure.py` | Marker / immutability / denial measurements |
| `ct14_eventlog.py`, `ct14_denied.py` | Event log diagnostics |
| `ct14_regen_ids.py` | Regenerate extension-owned GUIDs |

Results and the final minimal right list: `STATUS.md`.
