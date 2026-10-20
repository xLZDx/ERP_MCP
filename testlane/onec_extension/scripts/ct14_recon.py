"""Read-only recon of the clone: configuration name/version/compat mode, existing extensions, UUIDs of needed objects."""
import json
from ct14_common import connect_admin

c = connect_admin()
md = c.Метаданные
R = {}
R["name"] = str(md.Имя)
R["version"] = str(md.Версия)
try:
    R["compat"] = str(md.РежимСовместимости)
except Exception as e:
    R["compat"] = "ERR " + str(e)[:100]
try:
    R["ext_mode_compat"] = str(md.РежимСовместимостиРасширения)
except Exception as e:
    R["ext_mode_compat"] = "ERR " + str(e)[:100]
try:
    exts = c.РасширенияКонфигурации.Получить()
    R["extensions"] = [{"name": str(x.Имя), "active": bool(x.Активно), "safe": bool(x.БезопасныйРежим), "prot": bool(x.ЗащитаОтОпасныхДействий)} for x in exts]
except Exception as e:
    R["extensions"] = "ERR " + str(e)[:200]
R["has_roles"] = [r.Имя for r in md.Роли if r.Имя.startswith("CT14")]
print(json.dumps(R, ensure_ascii=False, indent=1))
