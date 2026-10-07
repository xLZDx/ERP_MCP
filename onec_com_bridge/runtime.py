"""Windows-only runtime pieces: DPAPI secret decryption and the COM connector. All imports are lazy so the package
imports (and is tested with fakes) on machines without pywin32."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any, Protocol


class ComRuntime(Protocol):
    def thread_init(self) -> None:
        """Called once in each worker thread before any COM use."""

    def connect(self, *, base_path: str, user: str, password: str) -> Any:
        """Open the file infobase as the given (reader) user and return the connection object."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_decrypt_file(path: str) -> str:
    """Decrypt a DPAPI (CurrentUser) blob written by the operator. Windows only."""
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows")
    blob = Path(path).read_bytes()
    buffer = ctypes.create_string_buffer(blob, len(blob))
    source = _DataBlob(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = _DataBlob()
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)
    ):
        raise OSError("DPAPI decryption failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(target.pbData)


class Win32ComRuntime:
    """V83.COMConnector through pywin32 (imported lazily)."""

    def thread_init(self) -> None:
        import pythoncom

        pythoncom.CoInitialize()

    def connect(self, *, base_path: str, user: str, password: str) -> Any:
        import win32com.client

        connector = win32com.client.Dispatch("V83.COMConnector")
        escaped = password.replace('"', '""')
        return connector.Connect(f'File="{base_path}";Usr="{user}";Pwd="{escaped}";')
