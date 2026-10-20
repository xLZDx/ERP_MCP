"""Create an EMPTY configuration extension CT14Ext on the clone through the COM extension manager (clone only)."""
import json
from ct14_common import connect_admin, EXT_NAME

c = connect_admin()
R = {}
mgr = c.РасширенияКонфигурации
existing = [str(x.Имя) for x in mgr.Получить()]
R["existing_before"] = existing
if EXT_NAME in existing:
    R["result"] = "already exists"
else:
    ext = mgr.Создать()
    ext.Имя = EXT_NAME
    ext.Синоним = "CT14 marker and writer role spike"
    ext.НазначениеРасширения = c.НазначениеРасширенияКонфигурации.Дополнение
    try:
        ext.Записать()
        R["result"] = "created with Записать()"
    except Exception as e:
        R["result"] = "ERR " + str(e)[:300]
R["existing_after"] = [str(x.Имя) for x in mgr.Получить()]
print(json.dumps(R, ensure_ascii=False, indent=1))
