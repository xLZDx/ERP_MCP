"""Shared helpers for the CT14 extension spike.

Clone-only guard: every script refuses to run unless the resolved target base is the single
approved disposable clone. Credentials are read from DPAPI-protected files inside the process
and are never printed or written anywhere.
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
    if type(base) is not str or not base:
        raise ValueError("refusing: only the disposable clone " + CLONE_NAME)
    try:
        normalized = Path(base).resolve(strict=True)
        expected = Path(CLONE_PATH).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise ValueError("refusing: only the disposable clone " + CLONE_NAME) from None
    if normalized != expected or normalized.name.casefold() != CLONE_NAME.casefold():
        raise ValueError("refusing: only the disposable clone " + CLONE_NAME)
    return str(normalized)


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
    for image_name in ("1cv8.exe", "1cv8c.exe"):
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
                capture_output=True, text=True, check=False,
            )
        except OSError:
            return False
        if (result.returncode != 0 or type(result.stdout) is not str
                or type(result.stderr) is not str or result.stderr != ""):
            return False
        output = result.stdout.casefold()
        if any(line.lstrip().startswith(image_name) for line in output.splitlines()):
            return False
        if output.strip() != "info: no tasks are running which match the specified criteria.":
            # An unrecognized, mixed, or empty tasklist response does not prove absence.
            return False
    return True


def _validated_designer_args(args: object) -> tuple[str, ...]:
    """Snapshot arguments and reject switches that can replace the guarded clone binding."""
    if type(args) is not list:
        raise ValueError("refusing: Designer arguments cannot override the guarded clone binding")
    snapshot = tuple(args)
    if any(type(item) is not str or "\x00" in item for item in snapshot):
        raise ValueError("refusing: Designer arguments cannot override the guarded clone binding")
    protected_prefixes = (
        "/f", "/s", "/n", "/p", "/out", "/ib", "-s", "-n", "-p", "-out", "-ib",
    )
    for item in snapshot:
        folded = item.casefold()
        if folded in ("-files", "-partial"):
            # These documented partial-load selectors are not connection overrides.
            continue
        if (folded.startswith(protected_prefixes)
                or (folded.startswith("-f") and folded != "-files")):
            raise ValueError("refusing: Designer arguments cannot override the guarded clone binding")
    return snapshot


def run_designer(args: list, out_file: str, base: str = CLONE_PATH, timeout: int = 3600) -> int:
    """Run the platform Designer in batch mode against the clone. Credentials are injected here
    and never logged; only the argument list WITHOUT credentials is returned to the caller's log."""
    base = guard(base)
    args_snapshot = _validated_designer_args(args)
    if not no_1c_running():
        raise RuntimeError("refusing: 1C process state is active or could not be verified")
    u, p = admin_creds()
    cmd = [DESIGNER, "DESIGNER", "/F", base, "/N", u, "/P", p]
    cmd.extend(args_snapshot)
    cmd.extend(("/Out", out_file))
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
