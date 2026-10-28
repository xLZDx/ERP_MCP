"""S12 exit scenarios, live-1C halves (E4 E14 E23 E25 E41) on the disposable clone 818HA_p2diff.

Scope and safety (these are the rules the file enforces, not only describes):

* The only target is the disposable clone. ``ct14_common.guard`` refuses any other base; this file never builds
  a connection string itself.
* Every document write happens inside ``НачатьТранзакцию`` ... ``ОтменитьТранзакцию`` and is rolled back. All
  writes use the least-privilege account ``CT14_NARROW`` (role ``CT14Писатель``). The administrator account is used
  for the setup that ``ct14_narrow_ops.prepare_user`` already performs and for read-only snapshots.
* The ONE persistent, authorized mutation is ``prepare_user``: it resets the password (fresh random, memory only) and
  the role set of the disposable test account ``CT14_NARROW`` and may create/bind its Users catalog item. It is not
  covered by the transaction bracket, so a PRINCIPAL SNAPSHOT (names, authentication flags, sorted role names, Users
  catalog count; never passwords or hashes) is taken before it and compared after the module (teardown) and in a test.
* No POST, no UNPOST, no hard delete. The real CREATE_DRAFT executor (``execute_create_draft``) is the writer.
* Every live test is bracketed: a snapshot of the clone (document count of every document type, plus a hash over
  the key fields of every supplier receipt, plus the number of leftover test documents) is taken before and after
  and must be identical. A difference stops the run (``_STOPPED``) and fails the test.

The change engine (``apply_transition``) is real; the "service glue" that turns 1C reads into engine evidence
(``version_equals_approved``, ``state_digest_equal``) and executor refusals into engine events lives in this file,
because the repository has no production glue yet. A passing test therefore proves the engine, the executor and
the clone behave consistently under that glue, not that a production glue exists.

The file is skipped, with an explicit reason, when the clone, pywin32, the DPAPI credentials or the COM
connection are unavailable. ``SCENARIO_MAP`` ties each exit ID to its live tests; the map tests run without 1C.
"""
from __future__ import annotations

import ast
import contextlib
import datetime
import hashlib
import json
import pathlib
import sys
import types
import uuid
from decimal import Decimal

import pytest

import business_ai_gateway.phase2.change as ch
from business_ai_gateway.phase2.change import (
    Applied,
    Authorization,
    ChangeKind,
    Dispatch,
    ErrorCode,
    Event,
    Execution,
    KillMode,
    LogicalKeyState,
    NonceState,
    ProposeEvidence,
    Refusal,
    Reservation,
)
from erp_mcp_private_writer.com_draft_executor import (
    DraftDestinationSet,
    ExecutorRefusal,
    execute_create_draft,
)
from erp_mcp_private_writer.com_manifest import ComValueAssignment
from erp_mcp_private_writer.refusal_mapping import map_executor_refusal
from erp_mcp_s15.labels import LABEL_MACHINE_VERIFIED
from erp_mcp_s15.reconcile import (
    LedgerChange,
    LedgerListing,
    LedgerStatus,
    OneCDocument,
    OneCListing,
    ReconcileStatus,
    Trigger,
    reconcile,
)
from tests.phase2 import _change_helpers as h
from tests.phase2._change_helpers import (
    APPROVAL_EXPIRES,
    T0,
    UNREADABLE,
    approved,
    claimed,
    good,
    kill,
    validated,
)

THIS = "tests/phase2/test_s12_s13_com_clone_scenarios.py"
OFFLINE = "tests/phase2/test_s12_exit_scenarios_offline.py"
LIVE_EXIT_IDS = ("E4", "E14", "E23", "E25", "E41")
ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "testlane" / "onec_extension" / "scripts"
TAG = "S12S13-"                       # every document this file creates carries this prefix in its incoming number
SCOPE = "clone:818HA_p2diff:Документ.ПоступлениеТоваровУслуг:all-companies:marked-and-unmarked"
PTU = "ПоступлениеТоваровУслуг"

PATH = (Event.PROPOSE, Event.VALIDATE, Event.APPROVE, Event.CLAIM, Event.BEGIN_APPLY, Event.ISSUE_PERMIT,
        Event.MARK_DISPATCHED)
ALL_READINGS = (kill(KillMode.STOP_ADMIT), kill(KillMode.STOP_EFFECTS), kill(KillMode.REVOKE), UNREADABLE)
READING_IDS = ("STOP_ADMIT", "STOP_EFFECTS", "REVOKE", "UNREADABLE")

_STOPPED: list[str] = []              # set when a before/after snapshot differs: nothing else may run


# ---------------------------------------------------------------------------------------------------------------------
# Clone access (skips with an explicit reason; never prints credentials)
# ---------------------------------------------------------------------------------------------------------------------

def _q(conn, text, **params):
    query = conn.NewObject("Запрос")
    query.Текст = text
    for key, value in params.items():
        query.УстановитьПараметр(key, value)
    return query.Выполнить().Выбрать()


def _one_int(conn, text, **params) -> int:
    sel = _q(conn, text, **params)
    sel.Следующий()
    return int(sel.N)


def _xml(conn, value) -> str:
    return "" if value is None else str(conn.XMLСтрока(value))


def _num(value) -> str:
    return format(Decimal(repr(value)).normalize() if isinstance(value, float) else Decimal(value).normalize(), "f")


@contextlib.contextmanager
def rolled_back_txn(conn):
    """The only way this file opens a write scope: the transaction is always cancelled."""
    conn.НачатьТранзакцию()
    try:
        yield
    finally:
        conn.ОтменитьТранзакцию()
    assert not conn.ТранзакцияАктивна(), "transaction still active after rollback"


def count_receipts(conn) -> int:
    return _one_int(conn, f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК N ИЗ Документ.{PTU} КАК Д")


def count_tagged(conn) -> int:
    return _one_int(conn, f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК N ИЗ Документ.{PTU} КАК Д "
                          "ГДЕ Д.НомерВходящегоДокумента ПОДОБНО &П", П=TAG + "%")


def snapshot(conn, doc_types) -> dict:
    """Selected-field regression snapshot: counts of every document type plus a 12-hex digest of selected receipt
    fields (and the data version) of every supplier receipt. It is not full-object equivalence."""
    counts = {}
    for name in doc_types:
        n = _one_int(conn, f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК N ИЗ Документ.{name} КАК Д")
        if n:
            counts[name] = n
    sel = _q(conn, "ВЫБРАТЬ Д.Ссылка КАК Р, Д.Номер КАК Н, "
                   "РАЗНОСТЬДАТ(ДАТАВРЕМЯ(1, 1, 1), Д.Дата, МИНУТА) КАК Т, СЕКУНДА(Д.Дата) КАК Сек, Д.Проведен КАК П, "
                   "Д.ПометкаУдаления КАК М, Д.СуммаДокумента КАК С, Д.CT14ИдентификаторИзменения КАК К, "
                   "Д.CT14ХешИзменения КАК Х, Д.ВерсияДанных КАК Версия, Д.НомерВходящегоДокумента КАК ВН, "
                   f"Д.Комментарий КАК Ком ИЗ Документ.{PTU} КАК Д УПОРЯДОЧИТЬ ПО Д.Ссылка")
    digest = hashlib.sha256()
    rows = posted = 0
    while sel.Следующий():
        rows += 1
        posted += 1 if sel.П else 0
        digest.update(json.dumps([_xml(conn, sel.Р), str(sel.Н), int(sel.Т), int(sel.Сек), bool(sel.П), bool(sel.М), str(sel.С),
                                  str(sel.К), str(sel.Х), str(sel.Версия), str(sel.ВН), str(sel.Ком)],
                                 ensure_ascii=True).encode("ascii") + b"\n")
    return {"document_types_with_rows": len(counts), "documents_total": sum(counts.values()),
            "receipts": counts.get(PTU, 0), "receipts_rows_hashed": rows, "receipts_posted": posted,
            "receipts_hash12": digest.hexdigest()[:12], "tagged_leftovers": count_tagged(conn)}


REVIEWED_NARROW_ROLES = ("CT14Писатель", "ЗапускВнешнегоСоединения")
_USER_FLAGS = ("АутентификацияСтандартная", "АутентификацияОС", "АутентификацияOpenID",
               "ПоказыватьВСпискеВыбора", "ЗапрещеноИзменятьПароль", "ПарольУстановлен", "РежимЗапуска", "Язык",
               "ПолноеИмя", "ПользовательОС")


def principal_snapshot(admin, narrow_name: str) -> dict:
    """Read-only (admin): every infobase user with its authentication flags and sorted role names, plus the Users
    catalog item count and whether a ``narrow_name`` item exists. Passwords and hashes are never read."""
    users = {}
    for user in admin.ПользователиИнформационнойБазы.ПолучитьПользователей():
        attrs = {}
        for flag in _USER_FLAGS:
            try:
                attrs[flag] = str(getattr(user, flag))
            except Exception:  # noqa: BLE001 - attribute not available in this platform build: recorded as such
                attrs[flag] = "<n/a>"
        attrs["roles"] = sorted(str(r.Имя) for r in user.Роли)
        users[str(user.Имя)] = attrs
    items = _one_int(admin, "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК N ИЗ Справочник.Пользователи КАК П")
    bound = _one_int(admin, "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК N ИЗ Справочник.Пользователи КАК П ГДЕ П.Наименование = &Н",
                     Н=narrow_name)
    return {"users": users, "users_catalog_items": items, "narrow_item_exists": bound > 0}


def principal_violations(before: dict, after: dict, narrow_name: str) -> list[str]:
    """Differences that the authorized CT14_NARROW reset does not explain (empty list = clean)."""
    bad = []
    added = sorted(set(after["users"]) - set(before["users"]))
    removed = sorted(set(before["users"]) - set(after["users"]))
    if added:
        bad.append(f"users added: {added}")
    if removed:
        bad.append(f"users removed: {removed}")
    for name in sorted(set(before["users"]) & set(after["users"])):
        if name == narrow_name:
            continue
        old, new = before["users"][name], after["users"][name]
        if old != new:
            bad.append(f"user {name} changed: {({k: (old[k], new[k]) for k in old if old[k] != new[k]})}")
    if narrow_name in after["users"] and after["users"][narrow_name]["roles"] != sorted(REVIEWED_NARROW_ROLES):
        bad.append(f"{narrow_name} roles are {after['users'][narrow_name]['roles']}")
    created = int(after["narrow_item_exists"]) - int(before["narrow_item_exists"])
    rise = after["users_catalog_items"] - before["users_catalog_items"]
    if rise != created or rise not in (0, 1):
        bad.append(f"Users catalog items rose by {rise} (allowed: only the one {narrow_name} binding item)")
    return bad


@pytest.fixture(scope="module")
def onec(request):
    if sys.platform != "win32":
        pytest.skip("SKIP_REASON: the 1C COM clone lane runs on Windows only")
    try:
        import win32com.client  # noqa: F401
        import win32crypt  # noqa: F401
    except ImportError:
        pytest.skip("SKIP_REASON: pywin32 (win32com / win32crypt) is not importable in this interpreter")
    if not SCRIPTS.is_dir():
        pytest.skip("SKIP_REASON: testlane/onec_extension/scripts is missing")
    sys.path.insert(0, str(SCRIPTS))
    try:
        import ct14_common as cc
        import ct14_narrow_ops as ops
    except Exception as exc:  # noqa: BLE001 - explicit skip reason, class name only
        pytest.skip(f"SKIP_REASON: CT14 helper scripts are not importable ({type(exc).__name__})")
    if not pathlib.Path(cc.CLONE_PATH).is_dir():
        pytest.skip(f"SKIP_REASON: the disposable clone {cc.CLONE_NAME} is not present on this machine")
    if not (cc.SECRETS / "admin_1c_clone_user.txt").is_file() or not (cc.SECRETS / "admin_1c_clone_password.dpapi").is_file():
        pytest.skip("SKIP_REASON: the DPAPI clone administrator credentials are not provisioned")
    try:
        pre_admin = cc.connect_admin()
        principals_before = principal_snapshot(pre_admin, cc.NARROW_USER)     # BEFORE the persistent mutation
        admin, narrow_pw = ops.prepare_user(ops.ROLES)     # existing setup: CT14_NARROW with the two narrow roles only
        narrow = cc.connect(cc.NARROW_USER, narrow_pw)
    except Exception as exc:  # noqa: BLE001 - explicit skip reason, class name only (a message could carry secrets)
        pytest.skip(f"SKIP_REASON: COM connection to the clone failed ({type(exc).__name__})")
    sel = _q(admin, "ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Р, Д.Владелец КАК Кон, Д.Организация КАК Орг, "
                    "Д.ВалютаВзаиморасчетов КАК Вал ИЗ Справочник.ДоговорыКонтрагентов КАК Д "
                    "ГДЕ НЕ Д.ЭтоГруппа И НЕ Д.ПометкаУдаления")
    if not sel.Следующий():
        pytest.skip("SKIP_REASON: the clone has no counterparty contract to reference")
    refs = {"ctr": _xml(admin, sel.Р), "cpt": _xml(admin, sel.Кон), "org": _xml(admin, sel.Орг),
            "cur": _xml(admin, sel.Вал)}
    item = _q(admin, "ВЫБРАТЬ ПЕРВЫЕ 1 Н.Ссылка КАК Р ИЗ Справочник.Номенклатура КАК Н "
                     "ГДЕ НЕ Н.ЭтоГруппа И НЕ Н.ПометкаУдаления")
    if not item.Следующий():
        pytest.skip("SKIP_REASON: the clone has no nomenclature item to reference")
    refs["item"] = _xml(admin, item.Р)
    doc_types = [str(md.Имя) for md in admin.Метаданные.Документы]
    ns = types.SimpleNamespace(admin=admin, narrow=narrow, refs=refs, doc_types=doc_types, name=cc.CLONE_NAME,
                               narrow_user=cc.NARROW_USER, principals_before=principals_before)

    def verify_principals():          # module-scoped finalizer: a violation is reported as a teardown error
        after = principal_snapshot(admin, cc.NARROW_USER)
        pre = principals_before
        print("PRINCIPALS " + json.dumps(
            {"before": {"users": {k: v["roles"] for k, v in sorted(pre["users"].items())},
                        "catalog_items": pre["users_catalog_items"], "narrow_item_exists": pre["narrow_item_exists"]},
             "after": {"users": {k: v["roles"] for k, v in sorted(after["users"].items())},
                       "catalog_items": after["users_catalog_items"], "narrow_item_exists": after["narrow_item_exists"]},
             "narrow_pre_run_roles": pre["users"].get(cc.NARROW_USER, {}).get("roles"),
             "narrow_item_created_in_this_run": after["narrow_item_exists"] and not pre["narrow_item_exists"]},
            ensure_ascii=True, sort_keys=True))
        bad = principal_violations(pre, after, cc.NARROW_USER)
        assert not bad, f"PRINCIPALS CHANGED beyond the authorized {cc.NARROW_USER} reset: {bad}"

    request.addfinalizer(verify_principals)
    yield ns


@pytest.fixture
def bracket(onec, request):
    """Before/after snapshot of the clone around one live test; any difference stops the run."""
    if _STOPPED:
        pytest.fail(f"STOPPED: an earlier scenario changed the clone ({_STOPPED[0]})")
    before = snapshot(onec.admin, onec.doc_types)
    yield before
    after = snapshot(onec.admin, onec.doc_types)
    print("EVIDENCE " + json.dumps({"test": request.node.name, "clone": onec.name, "before": before, "after": after},
                                   ensure_ascii=True, sort_keys=True))
    if before != after:
        _STOPPED.append(request.node.name)
        diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        pytest.fail(f"CLONE CHANGED by {request.node.name}: {diff}")


def test_principals_are_unchanged_except_the_authorized_narrow_reset_and_narrow_has_only_the_two_reviewed_roles(onec):
    after = principal_snapshot(onec.admin, onec.narrow_user)
    assert principal_violations(onec.principals_before, after, onec.narrow_user) == []
    assert after["users"][onec.narrow_user]["roles"] == sorted(REVIEWED_NARROW_ROLES)
    # effective roles seen from the narrow session itself: nothing beyond the two reviewed roles
    current = onec.narrow.ПользователиИнформационнойБазы.ТекущийПользователь()
    assert sorted(str(r.Имя) for r in current.Роли) == sorted(REVIEWED_NARROW_ROLES)
    # the checker can fail: an extra role / a changed other user / a removed user / extra catalog items are reported
    tampered = json.loads(json.dumps(after))
    tampered["users"][onec.narrow_user]["roles"] = sorted([*REVIEWED_NARROW_ROLES, "Полные права"])
    assert principal_violations(onec.principals_before, tampered, onec.narrow_user)
    others = [n for n in after["users"] if n != onec.narrow_user]
    if others:
        tampered = json.loads(json.dumps(after))
        tampered["users"][others[0]]["roles"] = [*tampered["users"][others[0]]["roles"], "X"]
        assert principal_violations(onec.principals_before, tampered, onec.narrow_user)
        tampered = json.loads(json.dumps(after))
        del tampered["users"][others[0]]
        assert principal_violations(onec.principals_before, tampered, onec.narrow_user)
    tampered = json.loads(json.dumps(after))
    tampered["users_catalog_items"] += 2
    assert principal_violations(onec.principals_before, tampered, onec.narrow_user)


# ---------------------------------------------------------------------------------------------------------------------
# Draft inputs, content digest, version, hand edit
# ---------------------------------------------------------------------------------------------------------------------

H_PROPS = (("h.org", "Организация"), ("h.cpt", "Контрагент"), ("h.ctr", "ДоговорКонтрагента"),
           ("h.num", "НомерВходящегоДокумента"), ("h.date", "ДатаВходящегоДокумента"),
           ("h.cur", "ВалютаДокумента"), ("h.com", "Комментарий"))
L_PROPS = (("l.item", "Номенклатура"), ("l.qty", "Количество"), ("l.price", "Цена"), ("l.vat", "СтавкаНДС"),
           ("l.amount", "Сумма"), ("l.vatamt", "СуммаНДС"))
DEST = DraftDestinationSet(
    PTU, H_PROPS, "Товары", L_PROPS,
    (("h.org", "Организации"), ("h.cpt", "Контрагенты"), ("h.ctr", "ДоговорыКонтрагентов"),
     ("h.cur", "Валюты"), ("l.item", "Номенклатура")),
    "CT14ИдентификаторИзменения", "CT14ХешИзменения",
    enumerations=(("l.vat", "СтавкиНДС"),), constants=(("СуммаВключаетНДС", True),), dates=("h.date",),
    numbers=("l.qty", "l.price", "l.amount", "l.vatamt"))
DOC_DATE = datetime.datetime(2026, 10, 27, 12, 0, 0)  # noqa: DTZ001 - the executor requires a naive datetime


def content_digest(header: dict, lines: list[dict]) -> str:
    """The digest this file uses as both the manifest marker and the recomputed content hash (plan A10 leaves the
    production definition UNKNOWN; this one is stated, deterministic and computed from the same fields on both sides)."""
    canon = {"h": {k: header[k] for k in sorted(header)}, "l": [{k: ln[k] for k in sorted(ln)} for ln in lines]}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()


def draft_values(onec, number: str, qty="2", price="10", amount="20", vat_amount="1.82", comment="s12s13 live"):
    r = onec.refs
    vals = {"h.org": r["org"], "h.cpt": r["cpt"], "h.ctr": r["ctr"], "h.num": number, "h.date": "2026-10-27",
            "h.cur": r["cur"], "h.com": comment, "l.item": r["item"], "l.qty": qty, "l.price": price,
            "l.vat": "НДС_10", "l.amount": amount, "l.vatamt": vat_amount}
    values = tuple(ComValueAssignment(p, "SetValue", "String", vals[p]) for p, _ in H_PROPS + L_PROPS)
    digest = content_digest(
        {"org": vals["h.org"], "cpt": vals["h.cpt"], "ctr": vals["h.ctr"], "num": number, "date": "2026-10-27",
         "cur": vals["h.cur"], "com": comment},
        [{"item": vals["l.item"], "qty": _num(qty), "price": _num(price), "vat": "НДС_10", "amount": _num(amount),
          "vatamt": _num(vat_amount)}])
    return values, digest


def read_receipts(conn, *, marker: str | None = None) -> list[dict]:
    """Read-only: every supplier receipt (optionally only those with one marker) with its computed content digest."""
    where = "" if marker is None else "ГДЕ Д.CT14ИдентификаторИзменения = &М"
    params = {} if marker is None else {"М": marker}
    head = _q(conn, "ВЫБРАТЬ Д.Ссылка КАК Р, Д.Организация КАК Орг, Д.Контрагент КАК Кон, Д.ДоговорКонтрагента КАК Дог, "
                    "Д.НомерВходящегоДокумента КАК Ном, ГОД(Д.ДатаВходящегоДокумента) КАК Г, "
                    "МЕСЯЦ(Д.ДатаВходящегоДокумента) КАК М, ДЕНЬ(Д.ДатаВходящегоДокумента) КАК Дн, "
                    "Д.ВалютаДокумента КАК Вал, Д.Комментарий КАК Ком, Д.CT14ИдентификаторИзменения КАК К, "
                    "Д.CT14ХешИзменения КАК Х, Д.ВерсияДанных КАК Версия, Д.Проведен КАК П "
                    f"ИЗ Документ.{PTU} КАК Д {where} УПОРЯДОЧИТЬ ПО Д.Ссылка", **params)
    docs: dict[str, dict] = {}
    while head.Следующий():
        ref = _xml(conn, head.Р)
        docs[ref] = {"ref": ref, "marker": str(head.К or ""), "marker_hash": str(head.Х or ""),
                     "version": str(head.Версия), "posted": bool(head.П), "lines": [],
                     "header": {"org": _xml(conn, head.Орг), "cpt": _xml(conn, head.Кон), "ctr": _xml(conn, head.Дог),
                                "num": str(head.Ном), "date": f"{int(head.Г):04d}-{int(head.М):02d}-{int(head.Дн):02d}",
                                "cur": _xml(conn, head.Вал), "com": str(head.Ком)}}
    lines = _q(conn, "ВЫБРАТЬ Т.Ссылка КАК Р, Т.Номенклатура КАК Н, Т.Количество КАК Кол, Т.Цена КАК Цена, "
                     "Т.СтавкаНДС КАК НДС, Т.Сумма КАК Сум, Т.СуммаНДС КАК СумНДС "
                     f"ИЗ Документ.{PTU}.Товары КАК Т УПОРЯДОЧИТЬ ПО Т.Ссылка, Т.НомерСтроки")
    while lines.Следующий():
        doc = docs.get(_xml(conn, lines.Р))
        if doc is not None:
            doc["lines"].append({"item": _xml(conn, lines.Н), "qty": _num(lines.Кол), "price": _num(lines.Цена),
                                 "vat": _xml(conn, lines.НДС), "amount": _num(lines.Сум),
                                 "vatamt": _num(lines.СумНДС)})
    for doc in docs.values():
        doc["content_hash"] = content_digest(doc["header"], doc["lines"])
    return list(docs.values())


def read_one(conn, marker: str) -> dict:
    found = read_receipts(conn, marker=marker)
    assert len(found) == 1, len(found)
    return found[0]


def hand_edit(conn, marker: str, comment: str) -> None:
    """A human edits the draft by hand (plain write, never posting); only inside a rolled-back transaction."""
    sel = _q(conn, f"ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Р ИЗ Документ.{PTU} КАК Д ГДЕ Д.CT14ИдентификаторИзменения = &М",
             М=marker)
    assert sel.Следующий()
    obj = sel.Р.ПолучитьОбъект()
    obj.Комментарий = comment
    obj.Записать(conn.РежимЗаписиДокумента.Запись)


def make_port(connection, values, digest, change_id, expected_total=None):
    def call():
        return execute_create_draft(connection, values, DEST, change_id=change_id, manifest_sha256=digest,
                                    document_date=DOC_DATE, expected_total=expected_total)
    return call


class WriteCountingConnection:
    """Wraps the connection that is really passed to the executor and counts document creates and writes.

    A refused path must leave both counters at 0 (the guarded connection is the one the code under test uses); the
    control path must make them positive, which proves the counter can see a write.
    """

    class _Doc:
        def __init__(self, doc, owner):
            object.__setattr__(self, "_d", doc)
            object.__setattr__(self, "_o", owner)

        def __getattr__(self, name):
            value = getattr(self._d, name)
            if name == "Записать":
                def counted(*args):
                    self._o.writes += 1
                    return value(*args)
                return counted
            return value

        def __setattr__(self, name, value):
            setattr(self._d, name, value)

    class _Manager:
        def __init__(self, manager, owner):
            self._m, self._o = manager, owner

        def __getattr__(self, name):
            if name == "СоздатьДокумент":
                def create():
                    self._o.creates += 1
                    return WriteCountingConnection._Doc(self._m.СоздатьДокумент(), self._o)
                return create
            return getattr(self._m, name)

    class _Documents:
        def __init__(self, documents, owner):
            self._ds, self._o = documents, owner

        def __getattr__(self, name):
            return WriteCountingConnection._Manager(getattr(self._ds, name), self._o)

    def __init__(self, conn):
        self._c = conn
        self.writes = 0
        self.creates = 0

    def __getattr__(self, name):
        value = getattr(self._c, name)
        return WriteCountingConnection._Documents(value, self) if name == "Документы" else value


class LostResponseConnection:
    """Wraps a real connection: the document write really happens, then the call raises as if the reply was lost."""

    class _Doc:
        def __init__(self, doc):
            object.__setattr__(self, "_d", doc)

        def __getattr__(self, name):
            value = getattr(self._d, name)
            if name == "Записать":
                def write_then_lose(*args):
                    value(*args)
                    raise RuntimeError("connection lost after the write was sent")
                return write_then_lose
            return value

        def __setattr__(self, name, value):
            setattr(self._d, name, value)

    class _Manager:
        def __init__(self, manager):
            self._m = manager

        def __getattr__(self, name):
            if name == "СоздатьДокумент":
                return lambda: LostResponseConnection._Doc(self._m.СоздатьДокумент())
            return getattr(self._m, name)

    class _Documents:
        def __init__(self, documents):
            self._ds = documents

        def __getattr__(self, name):
            return LostResponseConnection._Manager(getattr(self._ds, name))

    def __init__(self, conn):
        self._c = conn

    def __getattr__(self, name):
        value = getattr(self._c, name)
        return LostResponseConnection._Documents(value) if name == "Документы" else value


# ---------------------------------------------------------------------------------------------------------------------
# Engine driver (real apply_transition) with the live port
# ---------------------------------------------------------------------------------------------------------------------

CONSISTENT_LINE = {"item_ref": "it-1", "quantity": "2", "price": "10.50", "vat_rate_code": "VAT20",
                   "amount": "21.00", "vat_amount": "3.50"}


def raw_ok(**over):
    """A CREATE_DRAFT proposal whose line amounts are consistent (independent of the shared helper's defaults)."""
    payload_over = {"lines": [dict(CONSISTENT_LINE)], **over.pop("payload_over", {})}
    return h.raw_create(payload_over=payload_over, **over)


def good_live(event, rec, now, **over):
    if event is Event.PROPOSE:
        kill_reading = over.pop("kill", ch.SWITCH_OFF)
        return ProposeEvidence(
            proposal=h.proposal(raw_ok()), schema_valid=True, scope_resolved=True, requester_entitled=True,
            epoch_read=True, logical_key=LogicalKeyState.UNUSED, now=now, kill=kill_reading, **over)
    return good(event, rec, now, **over)


class LiveSvc:
    def __init__(self, rec=None, now=T0):
        self.rec, self.now, self.port_calls = rec, now, 0

    def ev(self, event, **over):
        res = apply_transition(self.rec, event, good_live(event, self.rec, self.now, **over))
        if type(res) is Applied and res.record is not None:
            self.rec = res.record
        return res

    def run(self, upto: int):
        for event in PATH[:upto]:
            assert type(self.ev(event)) is Applied, event
        return self

    def call_port(self, port):
        """The only COM-reaching path. Reachable only after MARK_DISPATCHED; maps the executor outcome to an event."""
        assert self.rec is not None and self.rec.dispatch is Dispatch.DISPATCHED, "port called without DISPATCHED"
        self.port_calls += 1
        try:
            result = port()
        except ExecutorRefusal as exc:
            exc.with_traceback(None)
            return exc
        return result

    @staticmethod
    def refusal_event(refusal: ExecutorRefusal) -> Event:
        """The engine event for an executor refusal, from the production mapping (not hand-picked in the test)."""
        return Event[map_executor_refusal(refusal.code, refusal.outcome_unknown).value]


apply_transition = ch.apply_transition


def ok(res):
    assert type(res) is Applied, res
    return res.record


def refused(res, code):
    assert type(res) is Refusal, res
    assert res.code is ErrorCode(code), (res.code, code)


# ---------------------------------------------------------------------------------------------------------------------
# E4: rejected / expired / digest-changed / stale-version approval paths leave the 1C snapshot unchanged
# ---------------------------------------------------------------------------------------------------------------------

def test_e4_live_rejected_expired_digest_changed_and_stale_approval_paths_write_nothing_to_1c(onec, bracket):
    narrow = onec.narrow
    number = TAG + uuid.uuid4().hex[:8]
    values, digest = draft_values(onec, number)
    marker = str(uuid.uuid4())
    counting = WriteCountingConnection(narrow)      # the connection handed to the executor: counts creates and writes
    port = make_port(counting, values, digest, marker)

    with rolled_back_txn(narrow):
        in_txn_before = count_receipts(narrow)
        # reject: the change can never be approved, claimed or written
        s = LiveSvc().run(2)
        assert ok(s.ev(Event.REJECT)).lifecycle is ch.Lifecycle.REJECTED
        for event in (Event.APPROVE, Event.CLAIM, Event.BEGIN_APPLY, Event.ISSUE_PERMIT, Event.MARK_DISPATCHED):
            assert type(s.ev(event)) is Refusal, event
        # expiry: at the deadline the claim is refused; the sweep terminates the change
        late = LiveSvc(approved(), now=APPROVAL_EXPIRES)
        refused(late.ev(Event.CLAIM), "APPROVAL_EXPIRED")
        swept = LiveSvc(approved(), now=APPROVAL_EXPIRES + datetime.timedelta(seconds=1))
        assert ok(swept.ev(Event.EXPIRE)).authorization is Authorization.EXPIRED
        assert type(swept.ev(Event.CLAIM)) is Refusal       # an EXPIRED authorization is final
        # digest changed after approval (real digests)
        original = h.proposal(raw_ok())
        changed = h.proposal(raw_ok(payload_over={"comment": "changed after approval"}))
        bound = ch.approval_digest(original) == ch.approval_digest(changed)
        assert bound is False
        refused(LiveSvc(validated()).ev(Event.APPROVE, digest_bound=bound), "DIGEST_MISMATCH")
        # a change claimed but not begun is held back by a stale state digest (the live version variant is in E23)
        s2 = LiveSvc().run(4)
        refused(s2.ev(Event.BEGIN_APPLY, state_digest_equal=False), "DIGEST_MISMATCH")
        for who in (s, late, swept, s2):
            assert who.port_calls == 0
        assert (counting.creates, counting.writes) == (0, 0)      # the counted connection saw nothing on refused paths
        assert count_receipts(narrow) == in_txn_before            # no write inside the transaction either
        # control: the very same counted port, once the approved path reaches it, is seen creating and writing
        ctl = LiveSvc().run(7)
        assert not isinstance(ctl.call_port(port), ExecutorRefusal)
        assert ctl.port_calls == 1 and counting.creates >= 1 and counting.writes >= 1
        assert count_receipts(narrow) == in_txn_before + 1


def test_e4_live_control_the_harness_can_see_a_write_and_rollback_restores_the_snapshot(onec, bracket):
    """Falsifiability: the same harness, on the fully approved path, DOES change the in-transaction count."""
    narrow = onec.narrow
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    marker = str(uuid.uuid4())
    with rolled_back_txn(narrow):
        before = count_receipts(narrow)
        s = LiveSvc().run(7)
        outcome = s.call_port(make_port(narrow, values, digest, marker, expected_total="20"))
        assert not isinstance(outcome, ExecutorRefusal), getattr(outcome, "code", None)
        assert s.port_calls == 1
        ok(s.ev(Event.CALL_SUCCESS))
        assert count_receipts(narrow) == before + 1
        stored = read_one(narrow, marker)
        assert stored["content_hash"] == digest and stored["marker_hash"] == digest and stored["posted"] is False


# ---------------------------------------------------------------------------------------------------------------------
# E14: POST-side approval paths, plus a live state digest
# ---------------------------------------------------------------------------------------------------------------------

def test_e14_live_post_paths_without_a_valid_own_approval_do_not_post_or_write(onec, bracket):
    narrow = onec.narrow
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    marker = str(uuid.uuid4())
    kw = {"kind": ChangeKind.POST, "parent_change_id": "parent9", "target_ref": "doc9"}
    with rolled_back_txn(narrow):
        before_count = count_receipts(narrow)
        # the draft whose approval the POST would depend on exists in 1C (created by the real executor)
        s0 = LiveSvc().run(7)
        assert not isinstance(s0.call_port(make_port(narrow, values, digest, marker)), ExecutorRefusal)
        approved_state = read_one(narrow, marker)["content_hash"]
        assert approved_state == digest
        # only the draft's approval: the POST needs its own, and its parent verified
        post = LiveSvc(h.proposed(**kw))
        ok(post.ev(Event.VALIDATE, key_state=h.BusinessKeyState.NOT_CHECKED))
        assert type(post.ev(Event.CLAIM)) is Refusal
        ok(post.ev(Event.APPROVE))
        refused(post.ev(Event.CLAIM, parent_verified=False), "PARENT_NOT_VERIFIED")
        # replayed / expired nonce and expired approval
        v = LiveSvc(validated(**kw))
        for nonce in (NonceState.CONSUMED, NonceState.EXPIRED, NonceState.INVALID):
            refused(v.ev(Event.APPROVE, nonce=nonce), "APPROVAL_NONCE_INVALID")
        refused(LiveSvc(approved(**kw), now=APPROVAL_EXPIRES + datetime.timedelta(seconds=1)).ev(Event.CLAIM),
                "APPROVAL_EXPIRED")
        # the draft is edited by hand after the POST was approved: the live digest differs, begin-apply refuses
        hand_edit(narrow, marker, "edited after the post was approved")
        now_state = read_one(narrow, marker)
        assert now_state["content_hash"] != approved_state
        cl = LiveSvc(claimed(**kw))
        refused(cl.ev(Event.BEGIN_APPLY, state_digest_equal=(now_state["content_hash"] == approved_state)),
                "DIGEST_MISMATCH")
        assert cl.rec.execution is Execution.NOT_STARTED
        for who in (post, v, cl):
            assert who.port_calls == 0
        # nothing posted, nothing else written: the only document is the draft, still unposted and still the edited one
        assert count_receipts(narrow) == before_count + 1
        assert read_one(narrow, marker)["posted"] is False
        assert read_one(narrow, marker)["content_hash"] == now_state["content_hash"]


# ---------------------------------------------------------------------------------------------------------------------
# E23: hand edit between preview and apply
# ---------------------------------------------------------------------------------------------------------------------

def test_e23_live_hand_edit_between_preview_and_apply_is_caught_by_the_1c_data_version_and_nothing_is_written(onec, bracket):
    narrow = onec.narrow
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    marker = str(uuid.uuid4())
    with rolled_back_txn(narrow):
        s0 = LiveSvc().run(7)
        assert not isinstance(s0.call_port(make_port(narrow, values, digest, marker)), ExecutorRefusal)
        preview = read_one(narrow, marker)
        # control: re-reading without an edit gives the same version (no spurious STALE_VERSION)
        assert read_one(narrow, marker)["version"] == preview["version"] != ""
        unedited = LiveSvc().run(4)
        ok(unedited.ev(Event.BEGIN_APPLY, version_equals_approved=(read_one(narrow, marker)["version"] == preview["version"])))
        # the human edit
        hand_edit(narrow, marker, "hand edit between preview and apply")
        edited = read_one(narrow, marker)
        assert edited["version"] != preview["version"] and edited["content_hash"] != preview["content_hash"]
        count_after_edit = count_receipts(narrow)
        s = LiveSvc().run(4)
        refused(s.ev(Event.BEGIN_APPLY, version_equals_approved=(edited["version"] == preview["version"])),
                "STALE_VERSION")
        assert s.rec.execution is Execution.NOT_STARTED and s.port_calls == 0
        # nothing was written by the refused apply: same count, same version, same content as right after the edit
        again = read_one(narrow, marker)
        assert count_receipts(narrow) == count_after_edit
        assert (again["version"], again["content_hash"]) == (edited["version"], edited["content_hash"])


def test_e23_live_executor_total_check_detects_a_stale_preview_only_after_the_write(onec, bracket):
    """The executor's own comparison (expected_total) is post-write: it reports the mismatch with the document id and
    marks the outcome unknown, but the draft already exists. Recorded as an observation in the report."""
    narrow = onec.narrow
    stale_preview_total = "20"                                   # preview: qty 2 * price 10
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8], price="15", amount="30")  # apply sees the edited source
    marker = str(uuid.uuid4())
    with rolled_back_txn(narrow):
        before = count_receipts(narrow)
        s = LiveSvc().run(7)
        outcome = s.call_port(make_port(narrow, values, digest, marker, expected_total=stale_preview_total))
        assert isinstance(outcome, ExecutorRefusal) and outcome.code == "COM_WRITTEN_READBACK_MISMATCH"
        assert outcome.outcome_unknown is True and uuid.UUID(outcome.document_ref)
        event = s.refusal_event(outcome)
        assert event is Event.CALL_UNKNOWN
        res = ok(s.ev(event))
        assert res.execution is Execution.APPLY_UNKNOWN and res.execution is not Execution.FAILED_APPLY
        assert count_receipts(narrow) == before + 1              # the draft landed (detected after, not before)
        assert read_one(narrow, marker)["posted"] is False


# ---------------------------------------------------------------------------------------------------------------------
# E41: kill switch
# ---------------------------------------------------------------------------------------------------------------------

def test_e41_live_kill_switch_blocks_every_boundary_with_zero_com_writes(onec, bracket):
    narrow = onec.narrow
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    marker = str(uuid.uuid4())
    port_calls = []
    counting = WriteCountingConnection(narrow)
    port = make_port(counting, values, digest, marker)
    with rolled_back_txn(narrow):
        before = count_receipts(narrow)
        for reading in ALL_READINGS:
            for boundary in range(len(PATH)):
                s = LiveSvc().run(boundary)
                rec_before = s.rec
                refused(s.ev(PATH[boundary], kill=reading), "KILL_SWITCH_ACTIVE")
                assert s.rec == rec_before and s.port_calls == 0
                with pytest.raises(AssertionError, match="without DISPATCHED"):
                    s.call_port(port)                            # the COM-reaching path is shut at the engine state
                port_calls.append(s.port_calls)
        assert sum(port_calls) == 0 and len(port_calls) == len(ALL_READINGS) * len(PATH)
        assert (counting.creates, counting.writes) == (0, 0)
        assert count_receipts(narrow) == before
        # control: the same counted port written through a fully approved path is seen (the counter is not vacuous)
        ctl = LiveSvc().run(7)
        assert not isinstance(ctl.call_port(port), ExecutorRefusal)
        assert counting.creates >= 1 and counting.writes >= 1 and count_receipts(narrow) == before + 1


@pytest.mark.parametrize("reading", ALL_READINGS, ids=READING_IDS)
def test_e41_live_in_flight_call_with_a_lost_reply_stays_unknown_not_failed_and_is_found_by_marker(onec, bracket, reading):
    """Reply loss is INJECTED inside an open, rolled-back transaction (real write, then a raised error). A real session
    loss and an uncertain commit are NOT_RUN."""
    narrow = onec.narrow
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    marker = str(uuid.uuid4())
    with rolled_back_txn(narrow):
        before = count_receipts(narrow)
        s = LiveSvc().run(7)                                     # DISPATCHED while the switch was off
        outcome = s.call_port(make_port(LostResponseConnection(narrow), values, digest, marker))
        assert isinstance(outcome, ExecutorRefusal) and outcome.code == "COM_WRITE_OUTCOME_UNKNOWN"
        assert outcome.outcome_unknown is True
        # the switch is active while the call is in flight: the outcome is UNKNOWN, never FAILED, reservation kept
        assert s.refusal_event(outcome) is Event.CALL_UNKNOWN
        rec = ok(s.ev(s.refusal_event(outcome), kill=reading))
        assert rec.execution is Execution.APPLY_UNKNOWN and rec.execution is not Execution.FAILED_APPLY
        assert rec.reservation is Reservation.RESERVED
        assert type(s.ev(Event.MARK_DISPATCHED, kill=reading)) is Refusal and s.port_calls == 1
        # the reply was lost but the write really landed: exactly one document, found by the change-id marker
        assert count_receipts(narrow) == before + 1
        assert read_one(narrow, marker)["marker"] == marker
        # recovery by marker lookup (read-only) resolves it under the active switch
        resolved = ok(s.ev(Event.RESOLVE_FOUND, kill=reading))
        assert resolved.execution is not Execution.FAILED_APPLY


def test_e41_live_a_refusal_before_any_write_is_failed_apply_not_unknown_and_writes_nothing(onec, bracket):
    narrow = onec.narrow
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    broken = tuple(ComValueAssignment(v.property_path, "SetValue", "String",
                                      str(uuid.uuid4()) if v.property_path == "l.item" else v.value) for v in values)
    marker = str(uuid.uuid4())
    counting = WriteCountingConnection(narrow)
    with rolled_back_txn(narrow):
        before = count_receipts(narrow)
        s = LiveSvc().run(7)
        outcome = s.call_port(make_port(counting, broken, digest, marker))
        assert isinstance(outcome, ExecutorRefusal) and outcome.code == "COM_REFERENCE_NOT_FOUND"
        assert outcome.outcome_unknown is False
        assert (counting.creates, counting.writes) == (0, 0)     # refused before any document object existed
        event = s.refusal_event(outcome)
        assert event is Event.REFUSED_BEFORE_WRITE
        rec = ok(s.ev(event))
        assert rec.execution is Execution.FAILED_APPLY and rec.reservation is Reservation.RELEASED
        assert count_receipts(narrow) == before


# ---------------------------------------------------------------------------------------------------------------------
# E25: ledger vs 1C skew through the S15 reconcile logic fed by a real read-only 1C listing
# ---------------------------------------------------------------------------------------------------------------------

class CloneReceiptLookup:
    """Read-only S15 ``OneCLookupPort`` over the clone: all supplier receipts of all companies, marked or not.

    Truthful declaration: the query has no marker, company, deletion-mark or date filter, so
    ``population_scope`` names exactly that population and ``enumerates_unmarked`` is True.
    """

    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _doc(d: dict) -> OneCDocument:
        return OneCDocument(d["ref"], d["marker"] or None, d["marker_hash"] or None, d["content_hash"])

    def list_documents(self) -> OneCListing:
        docs = tuple(self._doc(d) for d in read_receipts(self._conn))
        return OneCListing(True, docs, population_scope=SCOPE, enumerates_unmarked=True)

    def find_by_change_id(self, change_id: str):
        found = read_receipts(self._conn, marker=change_id)
        return self._doc(found[0]) if found else None


class FakeLedger:
    def __init__(self, *changes):
        self._changes = changes

    def list_changes(self):
        return LedgerListing(True, tuple(self._changes))


def _kinds(report, **where):
    return sorted(f.kind for f in report.findings
                  if all(getattr(f, k) == v for k, v in where.items()))


def test_e25_live_ledger_vs_1c_skew_is_surfaced_in_both_directions_from_a_real_listing(onec, bracket):
    narrow, admin = onec.narrow, onec.admin
    lookup = CloneReceiptLookup(narrow)
    # independent ground truth from a different connection, before the transaction starts
    unmarked_truth = _one_int(admin, f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК N ИЗ Документ.{PTU} КАК Д "
                                     "ГДЕ Д.CT14ИдентификаторИзменения = \"\" ИЛИ Д.CT14ХешИзменения = \"\"")
    marked_truth = count_receipts(admin) - unmarked_truth
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    marker = str(uuid.uuid4())
    absent_change = str(uuid.uuid4())
    with rolled_back_txn(narrow):
        # (0) the real population: every unmarked receipt is a finding, every marked one without a ledger row is orphan
        base = reconcile(Trigger.STARTUP, FakeLedger(), lookup, required_scope=SCOPE)
        assert base.status is ReconcileStatus.DIRTY
        assert _kinds(base).count("UNMARKED_DOCUMENT") == unmarked_truth
        assert _kinds(base).count("ORPHAN_MARKER") == marked_truth
        # the listing must declare its population: a different required scope is never CLEAN
        wrong = reconcile(Trigger.STARTUP, FakeLedger(), lookup, required_scope=SCOPE + ":other")
        assert (wrong.status, wrong.reason) == (ReconcileStatus.INCONCLUSIVE, "POPULATION_NOT_ESTABLISHED")

        # (1) a marked document exists in 1C but the ledger has no record of it -> ORPHAN_MARKER for exactly it
        s = LiveSvc().run(7)
        out = s.call_port(make_port(narrow, values, digest, marker))
        assert not isinstance(out, ExecutorRefusal)
        no_ledger = reconcile(Trigger.PERIODIC, FakeLedger(), lookup, required_scope=SCOPE)
        assert _kinds(no_ledger, change_id=marker) == ["ORPHAN_MARKER"]
        assert _kinds(no_ledger, document_ref=out.document_ref) == ["ORPHAN_MARKER"]
        assert _kinds(no_ledger).count("ORPHAN_MARKER") == marked_truth + 1

        # (2) an out-of-band receipt with NO marker appears in 1C (a hand-made copy) -> one more UNMARKED_DOCUMENT
        src = _q(narrow, f"ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Р ИЗ Документ.{PTU} КАК Д "
                         "ГДЕ Д.CT14ИдентификаторИзменения = \"\" УПОРЯДОЧИТЬ ПО Д.Дата")
        assert src.Следующий()
        copy = src.Р.ПолучитьОбъект().Скопировать()
        copy.CT14ИдентификаторИзменения = ""
        copy.CT14ХешИзменения = ""
        copy.НомерВходящегоДокумента = TAG + "oob"
        copy.Записать(narrow.РежимЗаписиДокумента.Запись)
        with_oob = reconcile(Trigger.PERIODIC, FakeLedger(), lookup, required_scope=SCOPE)
        assert _kinds(with_oob).count("UNMARKED_DOCUMENT") == unmarked_truth + 1

        # (3) the ledger has the record for the real document -> no finding for it; and a ledger record WITHOUT a
        #     document -> LEDGER_MISSING_IN_1C for exactly that change
        ledger = FakeLedger(LedgerChange(marker, digest, LedgerStatus.APPLIED),
                            LedgerChange(absent_change, "d" * 64, LedgerStatus.APPLIED))
        both = reconcile(Trigger.PERIODIC, ledger, lookup, required_scope=SCOPE)
        assert _kinds(both, change_id=marker) == []
        assert _kinds(both, change_id=absent_change) == ["LEDGER_MISSING_IN_1C"]
        assert both.status is ReconcileStatus.DIRTY and both.label == LABEL_MACHINE_VERIFIED

        # (4) a hand edit of the documented draft after it was ledgered -> CONTENT_CHANGED for that change only
        hand_edit(narrow, marker, "edited after the ledger recorded it")
        edited = reconcile(Trigger.PERIODIC, ledger, lookup, required_scope=SCOPE)
        assert _kinds(edited, change_id=marker) == ["CONTENT_CHANGED"]
        assert _kinds(edited, change_id=absent_change) == ["LEDGER_MISSING_IN_1C"]


def test_e41_e25_live_unknown_outcome_ledger_row_is_resolved_by_marker_lookup_never_by_resend(onec, bracket):
    narrow = onec.narrow
    lookup = CloneReceiptLookup(narrow)
    values, digest = draft_values(onec, TAG + uuid.uuid4().hex[:8])
    marker, never_written = str(uuid.uuid4()), str(uuid.uuid4())
    with rolled_back_txn(narrow):
        before = count_receipts(narrow)
        s = LiveSvc().run(7)
        out = s.call_port(make_port(LostResponseConnection(narrow), values, digest, marker))
        assert isinstance(out, ExecutorRefusal) and out.outcome_unknown is True
        ledger = FakeLedger(LedgerChange(marker, digest, LedgerStatus.UNKNOWN_OUTCOME),
                            LedgerChange(never_written, "e" * 64, LedgerStatus.UNKNOWN_OUTCOME))
        report = reconcile(Trigger.AFTER_RESTORE, ledger, lookup, required_scope=SCOPE)
        assert dict(report.unknown_outcomes) == {marker: "FOUND_BY_MARKER", never_written: "NOT_FOUND_BY_MARKER"}
        assert _kinds(report, change_id=marker) == ["NEEDS_LEDGER_RESOLUTION"]
        assert _kinds(report, change_id=never_written) == ["UNRESOLVED_UNKNOWN_OUTCOME"]
        assert report.status is ReconcileStatus.DIRTY
        assert count_receipts(narrow) == before + 1              # the lookup is read-only: still exactly one document


# ---------------------------------------------------------------------------------------------------------------------
# Scenario map (checked without 1C)
# ---------------------------------------------------------------------------------------------------------------------

def _t(name: str) -> str:
    return f"{THIS}::{name}"


def _o(name: str) -> str:
    return f"{OFFLINE}::{name}"


STATUSES = ("PASS", "PARTIAL", "NOT_RUN")
SCENARIO_MAP = {
    "E4": {
        "status": "PARTIAL",
        "status_note": "PARTIAL at exit-scenario level; PASS only for the measured component/live-clone subset",
        "live": [_t("test_e4_live_rejected_expired_digest_changed_and_stale_approval_paths_write_nothing_to_1c"),
                 _t("test_e4_live_control_the_harness_can_see_a_write_and_rollback_restores_the_snapshot")],
        "offline": [_o("test_e4_rejected_change_can_never_be_approved_claimed_or_written")],
        "not_run": "ledger rows (PostgreSQL integration); production glue that reads the real 1C version/digest and maps "
                   "executor refusals to engine events; production evidence/content-hash derivation (UNKNOWN)",
    },
    "E14": {
        "status": "PARTIAL",
        "live": [_t("test_e14_live_post_paths_without_a_valid_own_approval_do_not_post_or_write")],
        "offline": [_o("test_e14_post_with_only_the_draft_approval_is_refused_until_its_own_parent_is_verified_and_approved")],
        "not_run": "a real POST/UNPOST (forbidden on this run): posted flag and registrar rows after a refused POST on a posted target",
    },
    "E23": {
        "status": "PARTIAL",
        "live": [_t("test_e23_live_hand_edit_between_preview_and_apply_is_caught_by_the_1c_data_version_and_nothing_is_written"),
                 _t("test_e23_live_executor_total_check_detects_a_stale_preview_only_after_the_write")],
        "offline": [_o("test_e23_manual_edit_between_preview_and_apply_is_rejected_on_the_version_before_any_call")],
        "not_run": "edit inside the compare-and-write interval: no live UPDATE executor exists; the executor has no expected-version check",
    },
    "E25": {
        "status": "PARTIAL",
        "status_note": "PARTIAL at exit-scenario level; PASS only for the measured component/live-clone subset",
        "live": [_t("test_e25_live_ledger_vs_1c_skew_is_surfaced_in_both_directions_from_a_real_listing"),
                 _t("test_e41_e25_live_unknown_outcome_ledger_row_is_resolved_by_marker_lookup_never_by_resend")],
        "offline": [],
        "not_run": "the real PostgreSQL ledger (FakeLedger is used); the production evidence/content-hash definition "
                   "(test-local, production UNKNOWN, plan A10); production glue for 1C reads",
    },
    "E41": {
        "status": "PARTIAL",
        "live": [_t("test_e41_live_kill_switch_blocks_every_boundary_with_zero_com_writes"),
                 _t("test_e41_live_in_flight_call_with_a_lost_reply_stays_unknown_not_failed_and_is_found_by_marker"),
                 _t("test_e41_live_a_refusal_before_any_write_is_failed_apply_not_unknown_and_writes_nothing"),
                 _t("test_e41_e25_live_unknown_outcome_ledger_row_is_resolved_by_marker_lookup_never_by_resend")],
        "offline": [_o("test_e41_in_flight_call_reaches_a_terminal_or_unknown_state_and_no_new_call_begins")],
        "not_run": "the real kill-switch store and an operator in-flight list (gap G3); a genuinely severed COM session "
                   "and an uncertain commit (reply loss is injected inside an open, rolled-back transaction)",
    },
}


def _module_functions(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def test_scenario_map_covers_exactly_the_live_exit_ids_and_has_valid_statuses():
    assert tuple(SCENARIO_MAP) == LIVE_EXIT_IDS
    for eid, entry in SCENARIO_MAP.items():
        assert entry["status"] in STATUSES, eid
        assert entry["live"] and entry["not_run"].strip(), eid
        if eid in ("E4", "E25"):
            assert "PASS only for the measured component/live-clone subset" in entry["status_note"], eid


def test_scenario_map_references_resolve_to_existing_test_functions():
    cache: dict[str, set[str]] = {}
    for eid, entry in SCENARIO_MAP.items():
        for node in entry["live"] + entry["offline"]:
            file_part, _, func = node.partition("::")
            assert func.startswith("test_"), (eid, node)
            if file_part not in cache:
                assert (ROOT / file_part).is_file(), (eid, node)
                cache[file_part] = _module_functions(ROOT / file_part)
            assert func in cache[file_part], (eid, node)


def test_every_live_test_in_this_file_is_mapped():
    mapped = {n.split("::")[1] for e in SCENARIO_MAP.values() for n in e["live"]}
    own = {n for n in _module_functions(pathlib.Path(__file__))
           if n.startswith(("test_e4_live", "test_e14_live", "test_e23_live", "test_e25_live", "test_e41_live",
                            "test_e41_e25_live"))}
    assert own == mapped, (own - mapped, mapped - own)
