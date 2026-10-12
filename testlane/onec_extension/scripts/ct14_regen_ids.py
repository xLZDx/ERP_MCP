"""Regenerate every extension-owned GUID in the CT14Ext sources (used when a second extension must not share IDs).

Only GUIDs that are NOT references to base-configuration objects are replaced: the <ExtendedConfigurationObject>
values and the xr:ClassId values are preserved. Idempotent mapping inside one run (same old id -> same new id).
"""
import re
import uuid
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "CT14Ext"
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
mapping = {}


def fresh(m):
    g = m.group(0)
    if g not in mapping:
        mapping[g] = str(uuid.uuid4())
    return mapping[g]


for p in sorted(SRC.rglob("*.xml")):
    text = p.read_text(encoding="utf-8")
    out = []
    for line in text.splitlines(keepends=True):
        if "ExtendedConfigurationObject" in line or "<xr:ClassId>" in line or "xmlns" in line:
            out.append(line)
        else:
            out.append(GUID.sub(fresh, line))
    p.write_text("".join(out), encoding="utf-8", newline="")
    print(p.relative_to(SRC), "ok")
print("replaced", len(mapping), "ids")
