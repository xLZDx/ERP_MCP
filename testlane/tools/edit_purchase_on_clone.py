"""Edit ONE posted purchase document on the disposable clone 818HA_p2diff and re-post it (adds a known delta to the supplier credit).
Usage: edit_purchase_on_clone.py <base_path> <doc_number> <delta> [--apply]. Without --apply it only prints the document structure."""
import sys
from decimal import Decimal
from pathlib import Path
import win32com.client, win32crypt

base, number, delta = sys.argv[1], sys.argv[2], Decimal(sys.argv[3])
apply = "--apply" in sys.argv
assert base.rstrip("\\").endswith("818HA_p2diff"), "refusing: only the p2diff clone may be modified"
S = Path(r"D:\secrets\erp_mcp")
user = (S / "admin_1c_clone_user.txt").read_text(encoding="utf-8").strip()
pw = win32crypt.CryptUnprotectData((S / "admin_1c_clone_password.dpapi").read_bytes(), None, None, None, 0)[1].decode("utf-8")
conn = win32com.client.Dispatch("V83.COMConnector").Connect(f'File="{base}";Usr="{user}";Pwd="{pw}";')

q = conn.NewObject("Запрос", "ВЫБРАТЬ Д.Ссылка КАК Ссылка ИЗ Документ.ПоступлениеТоваровУслуг КАК Д ГДЕ Д.Номер = &Н И Д.Проведен И Д.Дата >= ДАТАВРЕМЯ(2026,8,1) И Д.Дата < ДАТАВРЕМЯ(2026,9,1)")
q.УстановитьПараметр("Н", number)
sel = q.Выполнить().Выбрать()
assert sel.Следующий(), "document not found"
obj = sel.Ссылка.ПолучитьОбъект()
print("doc:", obj.Номер, obj.Дата, "| total:", obj.СуммаДокумента, "| contractor:", obj.Контрагент.Наименование, "| posted:", obj.Проведен)
for part in ("Товары", "Услуги", "Оборудование", "ОбъектыСтроительства"):
    tp = getattr(obj, part)
    print(" tabular", part, "rows:", tp.Количество(), "| sums:", [tp.Получить(i).Сумма for i in range(tp.Количество())])
if not apply:
    print("dry run, nothing written")
    raise SystemExit
target = next(getattr(obj, p) for p in ("Товары", "Услуги") if getattr(obj, p).Количество() > 0)
row = target.Получить(0)
print("row sum before:", row.Сумма)
row.Сумма = row.Сумма + float(delta)
obj.СуммаДокумента = obj.СуммаДокумента + float(delta)
obj.Записать(conn.РежимЗаписиДокумента.Проведение)
chk = sel.Ссылка.ПолучитьОбъект()
print("after: total", chk.СуммаДокумента, "| posted:", chk.Проведен)
