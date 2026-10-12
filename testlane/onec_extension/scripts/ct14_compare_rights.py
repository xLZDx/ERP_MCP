"""Static comparison of the committed role rights against the reviewed allowlist. No COM, no Designer, no credentials.

Usage: ct14_compare_rights.py [Rights.xml] [allowlist.json]
Prints every right granted (value true) in Rights.xml that is not in the allowlist, every allowlisted right that is
missing, every object that is not allowlisted, and any forbidden right (Delete, Interactive*, administration-like).
Exit code 0 only when the committed file equals the allowlist and no forbidden right is present.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
rights_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "CT14Ext" / "Roles" / "CT14Писатель" / "Ext" / "Rights.xml"
allow_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "ct14_rights_allowlist.json"
FORBIDDEN = re.compile(r"Delete|Interactive|Administration|DataAdministration|UpdateDataBaseConfiguration|ConfigurationExtensionsAdministration|ExclusiveMode|Output|SaveUserData|ThinClient|WebClient|ThickClient|MobileClient|Automation|ExternalConnection", re.I)

raw = rights_path.read_bytes()
text = raw.decode("utf-8-sig")
granted = {}
for om in re.finditer(r"<object>(.*?)</object>", text, re.S):
    body = om.group(1)
    name = re.search(r"<name>([^<]+)</name>", body).group(1)
    granted[name] = {m.group(1) for m in re.finditer(r"<right>\s*<name>([^<]+)</name>\s*<value>true</value>", body)}
allow = {k: set(v) for k, v in json.loads(allow_path.read_text(encoding="utf-8")).items()}

problems = 0
print("Rights.xml sha256:", hashlib.sha256(raw).hexdigest())
print("objects in Rights.xml:", len(granted), "| objects in allowlist:", len(allow))
for obj in sorted(set(granted) | set(allow)):
    g, a = granted.get(obj, set()), allow.get(obj, set())
    if obj not in allow:
        print("NOT ALLOWLISTED object:", obj, sorted(g)); problems += 1
        continue
    for r in sorted(g - a):
        print("RIGHT NOT IN ALLOWLIST:", obj, r); problems += 1
    for r in sorted(a - g):
        print("ALLOWLISTED RIGHT MISSING:", obj, r); problems += 1
    for r in sorted(g):
        if FORBIDDEN.search(r):
            print("FORBIDDEN RIGHT:", obj, r); problems += 1
print("result:", "OK, committed rights equal the allowlist" if not problems else "%d problem(s)" % problems)
sys.exit(1 if problems else 0)
