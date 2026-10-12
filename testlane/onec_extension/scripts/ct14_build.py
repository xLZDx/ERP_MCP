"""Load the CT14Ext sources into the clone as extension CT14Ext and update the database configuration.

Usage: ct14_build.py [--partial <relative file path under CT14Ext> ...]
Without --partial the whole source tree is loaded; with --partial only the listed files are loaded
(faster iteration on role rights). The clone-only guard lives in ct14_common.guard().
"""
import sys
import time
from pathlib import Path
from ct14_common import run_designer, EXT_NAME

SRC = Path(__file__).resolve().parent.parent / "CT14Ext"
LOG = Path(r"D:\Temp\ct14work\build.log")

args = sys.argv[1:]
if LOG.exists():
    LOG.unlink()
if args and args[0] == "--partial":
    files = args[1:]
    cmd = ["/LoadConfigFromFiles", str(SRC), "-Extension", EXT_NAME, "-Files", ",".join(files), "-partial", "-updateConfigDumpInfo", "/UpdateDBCfg"]
else:
    cmd = ["/LoadConfigFromFiles", str(SRC), "-Extension", EXT_NAME, "/UpdateDBCfg"]
if "--noupdate" in sys.argv:
    cmd = [c for c in cmd if c != "/UpdateDBCfg"]
t = time.time()
rc = run_designer(cmd, str(LOG))
print("designer exit code:", rc, "seconds:", round(time.time() - t))
if LOG.exists():
    print(LOG.read_text(encoding="utf-8-sig", errors="replace")[-3000:])
else:
    print("no designer log written")
