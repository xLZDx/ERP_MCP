"""Check that the CT14Ext extension is active and its objects are visible through the external connection."""
import json
from ct14_common import connect_admin

c = connect_admin()
md = c.Метаданные
R = {"extensions": [(str(x.Имя), bool(x.Активно)) for x in c.РасширенияКонфигурации.Получить() if str(x.Имя) == "CT14Cust"]}
d = md.Документы.ПоступлениеТоваровУслуг
names = [str(a.Имя) for a in d.Реквизиты]
R["attr_count"] = len(names)
R["ct14_attrs"] = [n for n in names if n.startswith("CT14")]
R["ct14_roles"] = [str(r.Имя) for r in md.Роли if str(r.Имя).startswith("CT14")]
try:
    q = c.NewObject("Запрос", "ВЫБРАТЬ ПЕРВЫЕ 1 Д.CT14ИдентификаторИзменения КАК М ИЗ Документ.ПоступлениеТоваровУслуг КАК Д")
    q.Выполнить()
    R["query_on_attr"] = "OK"
except Exception as e:
    R["query_on_attr"] = "ERR " + str(e)[:200]
print(json.dumps(R, ensure_ascii=False))
