"""Turn off safe mode for the code-free CT14Ext extension (the other extensions on the clone also run with safe mode off)."""
from ct14_common import connect_admin

c = connect_admin()
ext = [x for x in c.РасширенияКонфигурации.Получить() if str(x.Имя) == "CT14Ext"][0]
ext.ЗащитаОтОпасныхДействий.ПредупреждатьОбОпасныхДействиях = False
ext.БезопасныйРежим = False
ext.Записать()
ext = [x for x in c.РасширенияКонфигурации.Получить() if str(x.Имя) == "CT14Ext"][0]
print("safe now:", bool(ext.БезопасныйРежим), "active:", bool(ext.Активно))
