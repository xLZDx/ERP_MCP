"""Print recent AccessDenied events of the clone event log with every column that may name the object/right."""
import datetime
import sys
from ct14_common import connect_admin

c = connect_admin()
tbl = c.NewObject("ТаблицаЗначений")
minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 5
flt = c.NewObject("Структура")
flt.Вставить("ДатаНачала", datetime.datetime.now() - datetime.timedelta(minutes=minutes))
c.ВыгрузитьЖурналРегистрации(tbl, flt)
cols = [str(col.Имя) for col in tbl.Колонки]
if "--cols" in sys.argv:
    print(cols)
for row in tbl:
    if "AccessDenied" in str(row.Событие) or "Access" in str(row.Событие) and "denied" in str(row.Событие).lower():
        out = []
        for k in ("Дата", "ИмяПользователя", "Метаданные", "ПредставлениеМетаданных", "ПредставлениеДанных", "Комментарий"):
            if k in cols:
                try:
                    v = getattr(row, k)
                    try:
                        v = [str(x) for x in v]
                    except TypeError:
                        v = str(v)[:200]
                    out.append(k + "=" + str(v)[:300])
                except Exception as e:
                    out.append(k + "=ERR")
        print(" | ".join(out))
