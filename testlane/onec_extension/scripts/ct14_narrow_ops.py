"""Operations performed as the infobase user CT14_NARROW (roles: CT14Писатель + ЗапускВнешнегоСоединения only).

Used by the iterative right discovery: prints one JSON object {"ok": bool, "step": ..., "error": ...}.
Nothing is deleted; created drafts are left in the clone (test data, operator decides on cleanup).
"""
import json
import secrets
import sys
import uuid
from ct14_common import connect_admin, connect, NARROW_USER, EXT_NAME

ROLES = ["CT14Писатель", "ЗапускВнешнегоСоединения"]


def prepare_user(roles=None):
    """(Re)set CT14_NARROW with ONLY the requested roles and a fresh random password kept in memory."""
    c = connect_admin()
    pw = secrets.token_urlsafe(18)
    u = c.ПользователиИнформационнойБазы.НайтиПоИмени(NARROW_USER)
    assert u is not None, "CT14_NARROW does not exist"
    u.Пароль = pw
    u.АутентификацияСтандартная = True
    for r in [str(x.Имя) for x in u.Роли]:
        u.Роли.Удалить(c.Метаданные.Роли.Найти(r))
    for r in (roles or ROLES):
        u.Роли.Добавить(c.Метаданные.Роли.Найти(r))
    u.Записать()
    # BSP needs a Users catalog item bound to the infobase user (session parameter ТекущийПользователь).
    qu = c.NewObject("Запрос", "ВЫБРАТЬ ПЕРВЫЕ 1 П.Ссылка КАК Ссылка ИЗ Справочник.Пользователи КАК П ГДЕ П.Наименование = &Н")
    qu.УстановитьПараметр("Н", NARROW_USER)
    sel = qu.Выполнить().Выбрать()
    if not sel.Следующий():
        item = c.Справочники.Пользователи.СоздатьЭлемент()
        item.Наименование = NARROW_USER
        item.ИдентификаторПользователяИБ = c.NewObject("УникальныйИдентификатор", c.XMLСтрока(u.УникальныйИдентификатор))
        item.ОбменДанными.Загрузка = True  # skip BSP handlers: only bind the catalog item to the IB user
        item.Записать()
    else:
        item = sel.Ссылка.ПолучитьОбъект()
        if c.XMLСтрока(item.ИдентификаторПользователяИБ) != c.XMLСтрока(u.УникальныйИдентификатор):
            item.ИдентификаторПользователяИБ = c.NewObject("УникальныйИдентификатор", c.XMLСтрока(u.УникальныйИдентификатор))
            item.ОбменДанными.Загрузка = True  # skip BSP handlers: only bind the catalog item to the IB user
            item.Записать()
    return c, pw



def run_ops(c_admin, pw, post=True, marker=None):
    """If marker is given and a draft with that marker exists it is reused (keeps the iteration from piling up drafts)."""
    n = connect(NARROW_USER, pw)
    st = {"step": "start"}
    try:
        marker = marker or str(uuid.uuid4())
        st["step"] = "narrow_find_existing_by_marker"
        qm = n.NewObject("Запрос", "ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Ссылка ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ Д.CT14ИдентификаторИзменения = &М")
        qm.УстановитьПараметр("М", marker)
        sm = qm.Выполнить().Выбрать()
        if sm.Следующий():
            o = sm.Ссылка.ПолучитьОбъект()
            st["reused_draft"] = True
        else:
            st["step"] = "narrow_find_source"
            q = n.NewObject("Запрос", "ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Ссылка ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ Д.Проведен И Д.Дата >= ДАТАВРЕМЯ(2026,8,1) И Д.Дата < ДАТАВРЕМЯ(2026,9,1) УПОРЯДОЧИТЬ ПО Д.Дата")
            s = q.Выполнить().Выбрать(); s.Следующий()
            st["step"] = "narrow_read_source"
            so = s.Ссылка.ПолучитьОбъект()
            st["step"] = "copy"
            o = so.Скопировать()
            st["step"] = "set_marker"
            o.CT14ИдентификаторИзменения = marker
            o.CT14ХешИзменения = "0" * 64
            o.Комментарий = "CT14 narrow draft"
            st["step"] = "write_draft"
            o.Записать(n.РежимЗаписиДокумента.Запись)
        if post:
            st["step"] = "post"
            o.Записать(n.РежимЗаписиДокумента.Проведение)
            st["step"] = "read_movements"
            d = n.Метаданные.Документы.ПоступлениеТоваровУслуг
            cnt = {}
            for mv in d.Движения:
                full = str(mv.ПолноеИмя())
                qq = n.NewObject("Запрос", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ " + full + " КАК Р ГДЕ Р.Регистратор = &Р")
                qq.УстановитьПараметр("Р", o.Ссылка)
                r = qq.Выполнить().Выбрать(); r.Следующий(); cnt[full] = int(r.К)
            st["movements"] = cnt
            st["step"] = "unpost"
            o2 = o.Ссылка.ПолучитьОбъект()
            o2.Записать(n.РежимЗаписиДокумента.ОтменаПроведения)
        st["step"] = "done"
        st["ok"] = True
    except Exception as e:
        st["ok"] = False
        st["error"] = str(e)[:700]
    return st


if __name__ == "__main__":
    c, pw = prepare_user()
    print(json.dumps(run_ops(c, pw), ensure_ascii=False, indent=1))
