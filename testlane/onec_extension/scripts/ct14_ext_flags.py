"""Set flags of one of OUR extensions (name must start with CT14) through the COM extension manager.

Usage: ct14_ext_flags.py <name> [active=0|1] [safe=0|1] [protect=0|1]
protect=0 disables the dangerous-action warning that otherwise makes the Designer batch /UpdateDBCfg fail
(event log: DBConfigExtensionUpdateError "Security warning ... Attempting to open <ext>").
"""
import sys
from ct14_common import connect_admin

name = sys.argv[1]
assert name.startswith("CT14"), "refusing: only CT14* extensions"
opts = dict(a.split("=") for a in sys.argv[2:])
c = connect_admin()
ext = [x for x in c.РасширенияКонфигурации.Получить() if str(x.Имя) == name][0]
if "protect" in opts:
    ext.ЗащитаОтОпасныхДействий.ПредупреждатьОбОпасныхДействиях = opts["protect"] == "1"
if "safe" in opts:
    ext.БезопасныйРежим = opts["safe"] == "1"
if "active" in opts:
    ext.Активно = opts["active"] == "1"
ext.Записать()
ext = [x for x in c.РасширенияКонфигурации.Получить() if str(x.Имя) == name][0]
print(name, "active", bool(ext.Активно), "safe", bool(ext.БезопасныйРежим))
