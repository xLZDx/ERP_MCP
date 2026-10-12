"""Check effective access rights of CT14_NARROW with ПравоДоступа. Usage: ct14_rightcheck.py Kind.Name:Right [...]
Right names are Russian API names, e.g. РегистрСведений.КурсыВалют:Чтение"""
import gc
import sys
import ct14_narrow_ops as ops
from ct14_common import connect, NARROW_USER

c, pw = ops.prepare_user()
del c
gc.collect()
n = connect(NARROW_USER, pw)
md = n.Метаданные
for arg in sys.argv[1:]:
    obj, right = arg.split(":")
    kind, name = obj.split(".", 1)
    coll = {"РегистрСведений": md.РегистрыСведений, "Справочник": md.Справочники, "Документ": md.Документы,
            "РегистрНакопления": md.РегистрыНакопления, "РегистрБухгалтерии": md.РегистрыБухгалтерии,
            "Константа": md.Константы, "ПланСчетов": md.ПланыСчетов}[kind]
    try:
        print(arg, "=", bool(n.ПравоДоступа(right, getattr(coll, name))))
    except Exception as e:
        print(arg, "ERR", str(e)[:150])
