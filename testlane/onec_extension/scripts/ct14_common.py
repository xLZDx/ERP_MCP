"""Shared helpers for the CT14 extension spike.

Clone-only guard: every script refuses to run unless the target base path ends with the
disposable clone folder name. Credentials are read from DPAPI-protected files inside the
process and are never printed or written anywhere.
"""
import subprocess
import time
from pathlib import Path

LAST_DIALOGS = []

import win32com.client
import win32crypt

CLONE_NAME = "818HA_p2diff"
CLONE_PATH = r"D:\ERP_MCP_Testbed\1c\reference\working\818HA_p2diff"
SECRETS = Path(r"D:\secrets\erp_mcp")
DESIGNER = r"C:\Users\koros\AppData\Local\Programs\1cv8_x64\8.3.27.2342\bin\1cv8.exe"
EXT_NAME = "CT14Cust"  # CT14Ext (purpose AddOn) was abandoned: AddOn extension objects were not visible to sessions
SRC_DIR_NAME = "CT14Ext"  # sources folder name
NARROW_USER = "CT14_NARROW"


def guard(base: str = CLONE_PATH) -> str:
    norm = base.rstrip("\\/")
    assert norm.lower().endswith(CLONE_NAME.lower()), "refusing: only the disposable clone " + CLONE_NAME
    assert Path(norm).name == CLONE_NAME
    return norm


def admin_creds():
    user = (SECRETS / "admin_1c_clone_user.txt").read_text(encoding="utf-8").strip()
    pw = win32crypt.CryptUnprotectData((SECRETS / "admin_1c_clone_password.dpapi").read_bytes(), None, None, None, 0)[1].decode("utf-8")
    return user, pw


def connect(user: str, pw: str, base: str = CLONE_PATH):
    base = guard(base)
    return win32com.client.Dispatch("V83.COMConnector").Connect(f'File="{base}";Usr="{user}";Pwd="{pw}";')


def connect_admin(base: str = CLONE_PATH):
    u, p = admin_creds()
    return connect(u, p, base)


def no_1c_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq 1cv8.exe"], capture_output=True, text=True).stdout
    out2 = subprocess.run(["tasklist", "/FI", "IMAGENAME eq 1cv8c.exe"], capture_output=True, text=True).stdout
    return "1cv8" not in (out + out2).lower().replace("no tasks", "")


def run_designer(args: list, out_file: str, base: str = CLONE_PATH, timeout: int = 3600) -> int:
    """Run the platform Designer in batch mode against the clone. Credentials are injected here
    and never logged; only the argument list WITHOUT credentials is returned to the caller's log."""
    base = guard(base)
    assert no_1c_running(), "a 1cv8 process is running; Designer needs exclusive access"
    u, p = admin_creds()
    cmd = [DESIGNER, "DESIGNER", "/F", base, "/N", u, "/P", p] + args + ["/Out", out_file]
    # Designer shows modal error dialogs even in batch mode and then waits for a click; watch our own child
    # process, record the dialog text (the only place the real error appears) and click OK.
    ps1 = str(Path(__file__).with_name("designer_dialog.ps1"))
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=r"D:\Temp\ct14work")
    t0 = time.time()
    while proc.poll() is None:
        time.sleep(8)
        if proc.poll() is not None:
            break
        res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-ProcId", str(proc.pid)],
                             capture_output=True, text=True)
        for line in res.stdout.splitlines():
            if line.startswith("DIALOG:"):
                LAST_DIALOGS.append(line)
                print("Designer dialog:", line[:600], flush=True)
        if time.time() - t0 > timeout:
            proc.kill()
            break
    return proc.wait()
