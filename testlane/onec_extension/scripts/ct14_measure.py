"""CT14 measurements on the clone. One COM session at a time. Prints one JSON document; never prints credentials.

Phases: A = writer role (CT14Писатель + ЗапускВнешнегоСоединения), B = standard accounting roles, C = admin queries.
Nothing is deleted. Test drafts stay in the clone (operator decides on cleanup).
"""
import gc
import json
import sys
import uuid

import ct14_narrow_ops as ops
from ct14_common import connect, connect_admin, NARROW_USER

STANDARD = ["БазовыеПраваБСП", "ДобавлениеИзменениеДанныхБухгалтерии", "ЧтениеДанныхБухгалтерии",
            "ДобавлениеИзменениеОбщейБухгалтерскойНСИ", "ЧтениеОбщейБухгалтерскойНСИ", "ЗапускВнешнегоСоединения"]
PAYMENT_DOCS = ["ПлатежноеПоручение", "РасходныйКассовыйОрдер", "СписаниеСРасчетногоСчета", "ПриходныйКассовыйОрдер",
                "ПоступлениеНаРасчетныйСчет", "ПлатежноеТребование", "ОплатаПлатежнойКартой"]
R = {}


def probe(key, fn):
    try:
        R[key] = fn()
    except Exception as e:
        R[key] = "ERROR: " + str(e)[:350]


def by_marker_count(conn, marker):
    q = conn.NewObject("Запрос", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ Д.CT14ИдентификаторИзменения = &М")
    q.УстановитьПараметр("М", marker)
    s = q.Выполнить().Выбрать(); s.Следующий()
    return int(s.К)


def comment_count(conn, text):
    q = conn.NewObject("Запрос", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ ПОДСТРОКА(Д.Комментарий, 1, 100) = &М")
    q.УстановитьПараметр("М", text)
    s = q.Выполнить().Выбрать(); s.Следующий()
    return int(s.К)


def first_posted_source(n):
    q = n.NewObject("Запрос", "ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Ссылка ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ Д.Проведен И Д.Дата >= ДАТАВРЕМЯ(2026,8,1) И Д.Дата < ДАТАВРЕМЯ(2026,9,1) УПОРЯДОЧИТЬ ПО Д.Дата")
    s = q.Выполнить().Выбрать(); s.Следующий()
    return s.Ссылка


def phase_a():
    c, pw = ops.prepare_user(ops.ROLES)
    del c
    gc.collect()
    n = connect(NARROW_USER, pw)
    md = n.Метаданные
    R["A_roles"] = ops.ROLES
    marker = "CT14M-" + uuid.uuid4().hex[:16]
    hsh = uuid.uuid4().hex + uuid.uuid4().hex
    R["A_marker"] = marker
    # A1 create draft with marker in the same write
    o = first_posted_source(n).ПолучитьОбъект().Скопировать()
    o.CT14ИдентификаторИзменения = marker
    o.CT14ХешИзменения = hsh
    o.Комментарий = "CT14 measurement draft"
    o.Записать(n.РежимЗаписиДокумента.Запись)
    ref = o.Ссылка
    R["A1_draft_written_with_marker_same_write"] = True
    R["A1_draft_not_posted"] = not bool(ref.Проведен)
    ro = ref.ПолучитьОбъект()
    R["A1_readback_marker_equal"] = (str(ro.CT14ИдентификаторИзменения) == marker and str(ro.CT14ХешИзменения) == hsh)
    R["A2_equality_query_count_as_writer"] = by_marker_count(n, marker)
    # A3 post / movements / unpost
    v0 = str(ro.ВерсияДанных)
    ro.Записать(n.РежимЗаписиДокумента.Проведение)
    R["A3_posted"] = bool(ref.Проведен)
    mv = {}
    for m in md.Документы.ПоступлениеТоваровУслуг.Движения:
        full = str(m.ПолноеИмя())
        q = n.NewObject("Запрос", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ " + full + " КАК Р ГДЕ Р.Регистратор = &Р")
        q.УстановитьПараметр("Р", ref)
        s = q.Выполнить().Выбрать(); s.Следующий()
        mv[full] = int(s.К)
    R["A3_movement_registers_read"] = len(mv)
    R["A3_movement_registers_nonzero"] = {k: v for k, v in mv.items() if v}
    lines = ref.ПолучитьОбъект()
    R["A3_lines_read"] = {"Товары": int(lines.Товары.Количество()), "Услуги": int(lines.Услуги.Количество())}
    R["A3_marker_intact_after_post"] = by_marker_count(n, marker) == 1
    # A4 stale version: second writer changes the draft, the first snapshot's version is now stale
    o_u = ref.ПолучитьОбъект()
    o_u.Записать(n.РежимЗаписиДокумента.ОтменаПроведения)
    R["A3_unposted"] = not bool(ref.Проведен)
    snap1 = ref.ПолучитьОбъект(); snap2 = ref.ПолучитьОбъект()
    v_before = str(snap1.ВерсияДанных)
    snap1.Комментарий = "writer 1"; snap1.Записать(n.РежимЗаписиДокумента.Запись)
    v_after = str(ref.ПолучитьОбъект().ВерсияДанных)
    R["A4_version_changes_on_write"] = v_before != v_after
    R["A4_stale_snapshot_detected_by_version_compare"] = str(snap2.ВерсияДанных) != v_after
    try:
        snap2.Комментарий = "writer 2 (stale)"; snap2.Записать(n.РежимЗаписиДокумента.Запись)
        R["A4_platform_rejects_stale_write"] = False
    except Exception as e:
        R["A4_platform_rejects_stale_write"] = "REJECTED: " + str(e)[:200]
    # A5 rights
    d = md.Документы.ПоступлениеТоваровУслуг
    rights = {}
    for nm, right in (("Добавление", "Добавление"), ("Изменение", "Изменение"), ("Чтение", "Чтение"), ("Проведение", "Проведение"),
                      ("ОтменаПроведения", "ОтменаПроведения"), ("Удаление", "Удаление"),
                      ("ИнтерактивноеУдаление", "ИнтерактивноеУдаление"),
                      ("ИнтерактивнаяПометкаУдаления", "ИнтерактивнаяПометкаУдаления"),
                      ("ИнтерактивноеУдалениеПомеченных", "ИнтерактивноеУдалениеПомеченных")):
        try:
            rights["receipt_" + nm] = bool(n.ПравоДоступа(right, d))
        except Exception as e:
            rights["receipt_" + nm] = "ERROR: " + str(e)[:80]
    for pd in PAYMENT_DOCS:
        for right in ("Добавление", "Изменение", "Удаление"):
            try:
                rights["%s_%s" % (pd, right)] = bool(n.ПравоДоступа(right, getattr(md.Документы, pd)))
            except Exception as e:
                rights["%s_%s" % (pd, right)] = "ERROR: " + str(e)[:80]
    for catalog in ("ДоговорыКонтрагентов", "Склады", "Контрагенты", "Номенклатура"):
        try:
            rights["catalog_%s_Изменение" % catalog] = bool(n.ПравоДоступа("Изменение", getattr(md.Справочники, catalog)))
        except Exception as e:
            rights["catalog_%s_Изменение" % catalog] = "ERROR: " + str(e)[:80]
    for attr in ("CT14ИдентификаторИзменения", "CT14ХешИзменения"):
        a = d.Реквизиты.Найти(attr)
        for right in ("Просмотр", "Редактирование"):
            try:
                rights["attr_%s_%s" % (attr, right)] = bool(n.ПравоДоступа(right, a))
            except Exception as e:
                rights["attr_%s_%s" % (attr, right)] = "ERROR: " + str(e)[:80]
    for right in ("Администрирование", "АдминистрированиеДанных", "ОбновлениеКонфигурацииБазыДанных", "ИнтерактивноеОткрытиеВнешнихОтчетовИОбработок", "ТонкийКлиент", "ВебКлиент", "ТолстыйКлиент", "МобильныйКлиент"):
        try:
            rights["config_" + right] = bool(n.ПравоДоступа(right, md))
        except Exception as e:
            rights["config_" + right] = "ERROR: " + str(e)[:80]
    R["A5_rights"] = rights
    # A6 add a payment document is denied by 1C
    for pd in ("ПлатежноеПоручение", "РасходныйКассовыйОрдер"):
        def add_payment(pd=pd):
            doc = getattr(n.Документы, pd).СоздатьДокумент()
            doc.Дата = n.ТекущаяДата()
            doc.Записать(n.РежимЗаписиДокумента.Запись)
            return "WRITTEN (unexpected)"
        probe("A6_add_" + pd, add_payment)
    # A7 delete denied (right is false, so the call is refused by the platform; never run when the right is true)
    if not bool(n.ПравоДоступа("Удаление", d)):
        def try_delete():
            ref.ПолучитьОбъект().Удалить()
            return "DELETED (unexpected)"
        probe("A7_delete_receipt", try_delete)
    else:
        R["A7_delete_receipt"] = "SKIPPED: delete right is true"
    R["A8_final_marker_count_equality"] = by_marker_count(n, marker)
    del n
    gc.collect()
    return marker


def phase_b(marker):
    c, pw = ops.prepare_user(STANDARD)
    del c
    gc.collect()
    n = connect(NARROW_USER, pw)
    d = n.Метаданные.Документы.ПоступлениеТоваровУслуг
    R["B_roles"] = STANDARD
    for attr in ("CT14ИдентификаторИзменения", "CT14ХешИзменения"):
        a = d.Реквизиты.Найти(attr)
        for right in ("Просмотр", "Редактирование"):
            probe("B_attr_%s_%s" % (attr, right), lambda a=a, right=right: bool(n.ПравоДоступа(right, a)))
    probe("B_receipt_Изменение", lambda: bool(n.ПравоДоступа("Изменение", d)))
    # B1 reading receipts with standard roles (earlier problem: record-level restriction)
    def read_by_marker():
        q = n.NewObject("Запрос", "ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Ссылка ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ Д.CT14ИдентификаторИзменения = &М")
        q.УстановитьПараметр("М", marker)
        s = q.Выполнить().Выбрать()
        if not s.Следующий():
            return "NOT VISIBLE to this user"
        return s.Ссылка
    r = None
    try:
        r = read_by_marker()
        R["B1_read_by_marker"] = "visible" if not isinstance(r, str) else r
    except Exception as e:
        R["B1_read_by_marker"] = "ERROR: " + str(e)[:300]
    if r is not None and not isinstance(r, str):
        def edit_comment():
            o = r.ПолучитьОбъект(); o.Комментарий = "edited by a standard-role user"; o.Записать(n.РежимЗаписиДокумента.Запись)
            return "comment edit written"
        probe("B2_standard_user_edits_comment", edit_comment)
        R["B2_marker_survives_comment_edit"] = by_marker_count(n, marker) == 1
        def change_marker():
            o = r.ПолучитьОбъект(); o.CT14ИдентификаторИзменения = "TAMPERED"; o.Записать(n.РежимЗаписиДокумента.Запись)
            return "marker change WRITTEN by non-writer"
        probe("B3_standard_user_changes_marker_programmatically", change_marker)
        def restore():
            return None
        R["B3_marker_now"] = None
    del n
    gc.collect()


def phase_c(marker):
    c = connect_admin()
    q = c.NewObject("Запрос", "ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка КАК Ссылка, Д.CT14ИдентификаторИзменения КАК М, Д.Комментарий КАК К ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ Д.CT14ИдентификаторИзменения = &М ИЛИ Д.CT14ИдентификаторИзменения = &Т")
    q.УстановитьПараметр("М", marker)
    q.УстановитьПараметр("Т", "TAMPERED")
    s = q.Выполнить().Выбрать()
    if s.Следующий():
        R["C_marker_value_now_is_tampered"] = str(s.М) == "TAMPERED"
        R["C_comment_now"] = str(s.К)
        # restore the marker (admin has all rights) so the draft stays findable
        o = s.Ссылка.ПолучитьОбъект()
        o.CT14ИдентификаторИзменения = marker
        o.Записать(c.РежимЗаписиДокумента.Запись)
    R["C_equality_count_after_restore"] = by_marker_count(c, marker)
    R["C_comment_search_for_old_comment_text"] = comment_count(c, "CT14 measurement draft")
    del c
    gc.collect()


if __name__ == "__main__":
    mk = None
    try:
        mk = phase_a()
    except Exception as e:
        R["A_FATAL"] = str(e)[:500]
    if mk:
        try:
            phase_b(mk)
        except Exception as e:
            R["B_FATAL"] = str(e)[:500]
        try:
            phase_c(mk)
        except Exception as e:
            R["C_FATAL"] = str(e)[:500]
    print(json.dumps(R, ensure_ascii=False, indent=1))
