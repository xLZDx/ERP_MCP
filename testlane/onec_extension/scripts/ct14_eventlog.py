"""Print recent Error/Warning event log records of the clone (diagnostics for Designer failures)."""
import datetime
import sys
from ct14_common import connect_admin

c = connect_admin()
tbl = c.NewObject("ТаблицаЗначений")
start = datetime.datetime.now() - datetime.timedelta(minutes=int(sys.argv[1]) if len(sys.argv) > 1 else 60)
flt = c.NewObject("Структура")
flt.Вставить("ДатаНачала", start)
c.ВыгрузитьЖурналРегистрации(tbl, flt)
n = 0
for row in tbl:
    lvl = str(row.Уровень)
    if True:
        print(row.Дата, lvl, str(row.Событие), "|", str(row.Комментарий)[:600])
        n += 1
print("rows", tbl.Количество(), "shown", n)
