"""Read the EFFECTIVE rights (ПравоДоступа) of CT14_NARROW holding only CT14Писатель + ЗапускВнешнегоСоединения for every
object listed in the committed Rights.xml, plus View/Edit on both marker attributes, and compare with the committed rights.

Read-only on the clone except resetting the roles/password of CT14_NARROW (done by prepare_user). One COM session at a time.
Prints a JSON summary; no credentials.
"""
import gc
import json
import re
from pathlib import Path

import ct14_narrow_ops as ops
from ct14_common import connect, NARROW_USER

RIGHTS = Path(__file__).resolve().parent.parent / "CT14Ext" / "Roles" / "CT14Писатель" / "Ext" / "Rights.xml"
COLL = {"Catalog": "Справочники", "Document": "Документы", "InformationRegister": "РегистрыСведений",
        "AccumulationRegister": "РегистрыНакопления", "AccountingRegister": "РегистрыБухгалтерии",
        "Constant": "Константы", "Sequence": "Последовательности", "SessionParameter": "ПараметрыСеанса"}
RU = {"Read": "Чтение", "Insert": "Добавление", "Update": "Изменение", "Posting": "Проведение", "UndoPosting": "ОтменаПроведения",
      "Get": "Получение", "Set": "Установка", "Delete": "Удаление", "View": "Просмотр", "Edit": "Редактирование",
      "InteractiveDelete": "ИнтерактивноеУдаление", "InteractiveSetDeletionMark": "ИнтерактивнаяПометкаУдаления",
      "InteractiveDeleteMarked": "ИнтерактивноеУдалениеПомеченных"}
PROBE = list(RU)


def committed():
    text = RIGHTS.read_text(encoding="utf-8")
    out = {}
    for om in re.finditer(r"<object>(.*?)</object>", text, re.S):
        body = om.group(1)
        nm = re.search(r"<name>([^<]+)</name>", body).group(1)
        out[nm] = {m.group(1) for m in re.finditer(r"<right>\s*<name>([^<]+)</name>\s*<value>true</value>", body)}
    return out


def main():
    c, pw = ops.prepare_user(ops.ROLES)
    del c
    gc.collect()
    n = connect(NARROW_USER, pw)
    md = n.Метаданные
    com = committed()
    result = {"roles": ops.ROLES, "committed_objects": len(com), "mismatch": {}, "extra_effective_beyond_committed": {}, "listed_but_not_effective": {}}
    effective_all = {}
    for obj, granted in sorted(com.items()):
        parts = obj.split(".")
        if len(parts) == 4 and parts[2] == "Attribute":
            mdobj = getattr(md, COLL[parts[0]])
            mdobj = getattr(mdobj, parts[1]).Реквизиты.Найти(parts[3])
        else:
            mdobj = getattr(getattr(md, COLL[parts[0]]), parts[1])
        eff = set()
        for r in PROBE:
            try:
                if n.ПравоДоступа(RU[r], mdobj):
                    eff.add(r)
            except Exception:
                pass  # right not applicable to this object kind
        effective_all[obj] = sorted(eff)
        if eff - granted:
            result["extra_effective_beyond_committed"][obj] = sorted(eff - granted)
        if granted - eff:
            result["listed_but_not_effective"][obj] = sorted(granted - eff)
    # the two marker attributes are not in Rights.xml any more: read their effective rights explicitly
    d = md.Документы.ПоступлениеТоваровУслуг
    for attr in ("CT14ИдентификаторИзменения", "CT14ХешИзменения"):
        a = d.Реквизиты.Найти(attr)
        eff = []
        for r in ("View", "Edit"):
            if n.ПравоДоступа(RU[r], a):
                eff.append(r)
        effective_all["Document.ПоступлениеТоваровУслуг.Attribute." + attr] = eff
    result["effective"] = effective_all
    forbidden = {"Delete", "InteractiveDelete", "InteractiveSetDeletionMark", "InteractiveDeleteMarked"}
    result["effective_forbidden_anywhere"] = {k: sorted(set(v) & forbidden) for k, v in effective_all.items() if set(v) & forbidden}
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
