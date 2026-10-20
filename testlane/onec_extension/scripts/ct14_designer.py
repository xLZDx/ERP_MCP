"""Run one Designer batch command against the clone. Credentials are injected inside ct14_common and never printed.

Usage: ct14_designer.py <outfile> <designer args...>
Example: ct14_designer.py out.txt /DumpConfigToFiles D:\\tmp\\dump -Extension CT14Ext
"""
import sys
from pathlib import Path
from ct14_common import run_designer

out = sys.argv[1]
args = sys.argv[2:]
rc = run_designer(args, out)
print("designer exit code:", rc)
p = Path(out)
if p.exists():
    print(p.read_text(encoding="utf-8-sig", errors="replace")[-3000:])
