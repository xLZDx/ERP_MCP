"""Does the external connection see objects of other (pre-existing) extensions? Read-only."""
from ct14_common import connect_admin

c = connect_admin()
md = c.Метаданные
print("EF_rq_54815 common template visible:", md.ОбщиеМакеты.Найти("EF_rq_54815") is not None)
for x in c.РасширенияКонфигурации.Получить():
    print(str(x.Имя), "scope", c.Строка(x.ОбластьДействия), "active", bool(x.Активно), "safe", bool(x.БезопасныйРежим), "allroles", bool(x.ИспользоватьОсновныеРолиДляВсехПользователей))
try:
    print("ext_count_in_metadata:", [str(e.Имя) for e in md.Расширения] if hasattr(md, "Расширения") else "no attr")
except Exception as e:
    print("ERR", str(e)[:100])
