"""Iterative discovery of the minimal rights of role CT14Писатель.

Loop: write Rights.xml from the state -> load extension + /UpdateDBCfg -> run the operations as CT14_NARROW
(roles: CT14Писатель + ЗапускВнешнегоСоединения only) -> read AccessDenied events of the event log (they name the
object) -> add the next right of the ladder for each denied object. State is kept in ct14_rights_state.json.

Ladder per object kind: Read -> Update -> Insert (Insert only for reference-like objects). Delete is never added.
"""
import datetime
import gc
import json
import re
import sys
import time
import uuid
from pathlib import Path

from ct14_common import connect_admin, run_designer, EXT_NAME
import ct14_narrow_ops as ops

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "CT14Ext"
STATE = HERE / "ct14_rights_state.json"
RIGHTS_XML = SRC / "Roles" / "CT14Писатель" / "Ext" / "Rights.xml"
BUILD_LOG = r"D:\Temp\ct14work\iter_build.log"
MARKER = "CT14-ITER-MARKER-0001"
BASE_DUMP = Path(r"D:\Temp\ct14work")  # full /DumpConfigToFiles of the base configuration (read-only source of base uuids)
FOLDER = {
    "Catalog": "Catalogs", "Document": "Documents", "InformationRegister": "InformationRegisters",
    "AccumulationRegister": "AccumulationRegisters", "AccountingRegister": "AccountingRegisters",
    "CalculationRegister": "CalculationRegisters", "ChartOfAccounts": "ChartsOfAccounts",
    "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes", "ChartOfCalculationTypes": "ChartsOfCalculationTypes",
    "Constant": "Constants", "Enum": "Enums", "SessionParameter": "SessionParameters", "Sequence": "Sequences",
    "DocumentJournal": "DocumentJournals", "ExchangePlan": "ExchangePlans", "Task": "Tasks", "BusinessProcess": "BusinessProcesses",
}

KIND = {
    "Справочник": "Catalog", "Документ": "Document", "РегистрСведений": "InformationRegister",
    "РегистрНакопления": "AccumulationRegister", "РегистрБухгалтерии": "AccountingRegister",
    "РегистрРасчета": "CalculationRegister", "ПланСчетов": "ChartOfAccounts",
    "ПланВидовХарактеристик": "ChartOfCharacteristicTypes", "ПланВидовРасчета": "ChartOfCalculationTypes",
    "Константа": "Constant", "Перечисление": "Enum", "ПараметрСеанса": "SessionParameter",
    "Последовательность": "Sequence", "ЖурналДокументов": "DocumentJournal", "ПланОбмена": "ExchangePlan",
    "ЗадачаБП": "Task", "БизнесПроцесс": "BusinessProcess", "Задача": "Task",
}
REF_LIKE = {"Catalog", "Document", "ChartOfAccounts", "ChartOfCharacteristicTypes", "ChartOfCalculationTypes", "ExchangePlan", "BusinessProcess", "Task"}
CORE = {
    "Document.ПоступлениеТоваровУслуг": ["Read", "Insert", "Update", "Posting", "UndoPosting"],
    "Document.ПоступлениеТоваровУслуг.Attribute.CT14ИдентификаторИзменения": ["View", "Edit"],
    "Document.ПоступлениеТоваровУслуг.Attribute.CT14ХешИзменения": ["View", "Edit"],
}


def ladder(kind):
    if kind == "SessionParameter":
        return ["Get", "Set"]
    if kind == "Enum":
        return ["View"]
    if kind in REF_LIKE:
        return ["Read", "Update", "Insert"]
    return ["Read", "Update"]


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def write_rights(state):
    merged = {k: list(v) for k, v in CORE.items()}
    for obj, rights in state.items():
        merged.setdefault(obj, [])
        for r in rights:
            if r not in merged[obj]:
                merged[obj].append(r)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<Rights xmlns="http://v8.1c.ru/8.2/roles" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="Rights" version="2.20">',
             "\t<setForNewObjects>false</setForNewObjects>", "\t<setForAttributesByDefault>false</setForAttributesByDefault>",
             "\t<independentRightsOfChildObjects>false</independentRightsOfChildObjects>"]
    for obj in sorted(merged):
        parts.append("\t<object>\n\t\t<name>%s</name>" % obj)
        for r in merged[obj]:
            parts.append("\t\t<right><name>%s</name><value>true</value></right>" % r)
        parts.append("\t</object>")
    parts.append("</Rights>")
    RIGHTS_XML.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="")


def build():
    for cmd in (["/LoadConfigFromFiles", str(SRC), "-Extension", EXT_NAME], ["/UpdateDBCfg", "-Extension", EXT_NAME]):
        rc = run_designer(cmd, BUILD_LOG)
        if rc != 0:
            raise SystemExit("designer failed rc=%s for %s" % (rc, cmd[0]))


def denied_events():
    """All AccessDenied events as (date string, [metadata names]). Dates compare as strings (ISO format)."""
    c = connect_admin()
    tbl = c.NewObject("ТаблицаЗначений")
    flt = c.NewObject("Структура")
    flt.Вставить("ДатаНачала", datetime.datetime.now() - datetime.timedelta(hours=6))
    c.ВыгрузитьЖурналРегистрации(tbl, flt)
    found = []
    for row in tbl:
        if "AccessDenied" in str(row.Событие):
            names = []
            try:
                names = [str(x) for x in row.Метаданные]
            except TypeError:
                pass
            found.append((str(row.Дата), names))
    del tbl, flt, c
    gc.collect()
    return found


def names_from_error(err):
    """Objects named only in the error text: 'Insufficient rights to use table "X"' and 'context attribute (SessionParam)'."""
    out = []
    for m in re.finditer(r'Insufficient rights to use table \\?"([^"\\]+)', err):
        out.append(m.group(1))
    for m in re.finditer(r"context attribute \((\w+)\)", err):
        nm = m.group(1)
        if (BASE_DUMP / "SessionParameters" / (nm + ".xml")).exists():
            out.append("ПараметрСеанса." + nm)
        elif (BASE_DUMP / "Constants" / (nm + ".xml")).exists():
            out.append("Константа." + nm)
    return out


def adopt(kind, name):
    """Adopt a base object into the extension without changes (a role can only carry rights for objects the extension owns)."""
    dst = SRC / FOLDER[kind] / (name + ".xml")
    if dst.exists():
        return False
    src = BASE_DUMP / FOLDER[kind] / (name + ".xml")
    text = src.read_text(encoding="utf-8-sig")
    base_uuid = re.search(r'<%s uuid="([^"]+)">' % kind, text).group(1)
    T = "\t"
    header = text[: text.index(T + "<%s " % kind)]
    m = re.search(r"<InternalInfo>.*?</InternalInfo>|<InternalInfo/>", text, re.S)
    ii = re.sub(r"(<xr:(?:TypeId|ValueId|ObjectId)>)[^<]+(</xr:)", lambda mm: mm.group(1) + str(uuid.uuid4()) + mm.group(2), m.group(0)) if m else None
    lines = [
        T + '<%s uuid="%s">' % (kind, uuid.uuid4()),
        *([T * 2 + ii] if ii else []),
        T * 2 + "<Properties>",
        T * 3 + "<ObjectBelonging>Adopted</ObjectBelonging>",
        T * 3 + "<Name>%s</Name>" % name,
        T * 3 + "<Comment/>",
        T * 3 + "<ExtendedConfigurationObject>%s</ExtendedConfigurationObject>" % base_uuid,
        T * 2 + "</Properties>",
        *([T * 2 + "<ChildObjects/>"] if "<ChildObjects" in text else []),
        T + "</%s>" % kind,
        "</MetaDataObject>",
        "",
    ]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(header + "\n".join(lines), encoding="utf-8", newline="")
    cfg = SRC / "Configuration.xml"
    ct = cfg.read_text(encoding="utf-8")
    ct = ct.replace(T * 2 + "</ChildObjects>", T * 3 + "<%s>%s</%s>\n" % (kind, name, kind) + T * 2 + "</ChildObjects>")
    cfg.write_text(ct, encoding="utf-8", newline="")
    return True


def to_rights_name(ru):
    kind_ru, _, name = ru.partition(".")
    kind = KIND.get(kind_ru)
    if not kind:
        return None, None
    return kind, kind + "." + name.split(".")[0]


def main(max_iter=150, rebuild_first=True):
    state = load_state()
    for seed in [a for a in sys.argv[1:] if "." in a]:  # manual seeds: Kind.Name (English kind), granted with the full ladder
        kind_en, nm = seed.split(".", 1)
        adopt(kind_en, nm)
        state[seed] = list(ladder(kind_en))
        print("seeded", seed, state[seed])
    c, pw = ops.prepare_user()
    del c
    gc.collect()
    first = True
    for it in range(1, max_iter + 1):
        if rebuild_first or not first:
            write_rights(state)
            build()
        first = False
        base_dates = [d for d, _ in denied_events()]
        base_max = max(base_dates) if base_dates else ""
        st = ops.run_ops(None, pw, marker=MARKER)
        gc.collect()
        print("iter", it, st.get("step"), "ok" if st.get("ok") else "FAIL", flush=True)
        if st.get("ok"):
            print(json.dumps(st, ensure_ascii=False))
            return 0
        denied = sorted(set(n for d, names in denied_events() if d > base_max for n in names) | set(names_from_error(st.get("error", ""))))
        print("  denied:", denied, "\n  error:", st.get("error", "")[:250], flush=True)
        changed = False
        for ru in denied:
            kind, obj = to_rights_name(ru)
            if not obj:
                print("  cannot map", ru)
                continue
            if adopt(kind, obj.split(".", 1)[1]):
                changed = True
                print("  adopted", obj)
            have = state.setdefault(obj, [])
            for r in ladder(kind):
                if r not in have:
                    have.append(r)
                    changed = True
                    print("  +", obj, r)
                    break
        save_state(state)
        if not changed:
            print("no new right could be derived; stopping")
            return 2
    return 3


if __name__ == "__main__":
    sys.exit(main())
