"""Probe state/properties of extension CT14Ext through the COM extension manager."""
from ct14_common import connect_admin

c = connect_admin()
ext = [x for x in c.РасширенияКонфигурации.Получить() if str(x.Имя) == "CT14Ext"][0]
for name in ("Имя", "Активно", "БезопасныйРежим", "ЗащитаОтОпасныхДействий", "ИспользоватьОсновныеРолиДляВсехПользователей",
             "Версия", "НазначениеРасширения", "ОбластьДействия", "УникальныйИдентификатор", "КонтрольнаяСумма", "Синоним"):
    try:
        print(name, "=", str(getattr(ext, name))[:80])
    except Exception as e:
        print(name, "ERR", str(e)[:80])
try:
    r = ext.ПроверитьМожноПрименить(c.ПредставлениеРасширенияОбласти if False else None)
    print("ПроверитьМожноПрименить:", [str(x.Описание)[:200] for x in r])
except Exception as e:
    print("ПроверитьМожноПрименить ERR", str(e)[:200])
