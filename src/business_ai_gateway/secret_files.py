"""Private permissions for newly created temporary secret directories; no 1C/COM code."""
from __future__ import annotations

import ctypes
import os
import re
import stat
from pathlib import Path


class SecretDirectoryUnavailable(RuntimeError):
    pass


def _windows_libraries():
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    pointer = ctypes.c_void_p
    signatures = {
        "OpenProcessToken": ([wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL),
        "GetTokenInformation": ([wintypes.HANDLE, ctypes.c_int, pointer, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "ConvertSidToStringSidW": ([pointer, ctypes.POINTER(pointer)], wintypes.BOOL),
        "ConvertStringSecurityDescriptorToSecurityDescriptorW": ([wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(pointer), pointer], wintypes.BOOL),
        "GetSecurityDescriptorDacl": ([pointer, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(pointer), ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
        "SetNamedSecurityInfoW": ([wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, pointer, pointer, pointer, pointer], wintypes.DWORD),
        "GetNamedSecurityInfoW": ([wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, pointer, pointer, ctypes.POINTER(pointer), pointer, ctypes.POINTER(pointer)], wintypes.DWORD),
        "GetSecurityDescriptorControl": ([pointer, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "GetAclInformation": ([pointer, pointer, wintypes.DWORD, ctypes.c_int], wintypes.BOOL),
        "GetAce": ([pointer, wintypes.DWORD, ctypes.POINTER(pointer)], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(advapi, name)
        function.argtypes, function.restype = arguments, result
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], wintypes.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [pointer], pointer
    return advapi, kernel


def _current_sid(advapi, kernel) -> str:
    from ctypes import wintypes

    token = wintypes.HANDLE()
    text = ctypes.c_void_p()
    try:
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))  # TOKEN_USER
        if not 0 < needed.value <= 4096:
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, 1, buffer, needed.value, ctypes.byref(needed)):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first field is a pointer.
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents
        if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        sid = ctypes.wstring_at(text.value)
        if not re.fullmatch(r"S-[0-9]+(?:-[0-9]+)+", sid):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        return sid
    finally:
        if text.value:
            kernel.LocalFree(text)
        if token.value:
            kernel.CloseHandle(token)


def _protect_windows(path: Path) -> None:
    # Microsoft API: SetNamedSecurityInfoW; DACL_SECURITY_INFORMATION |
    # PROTECTED_DACL_SECURITY_INFORMATION. Current identity + SYSTEM + Administrators only.
    # https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfow
    from ctypes import wintypes

    advapi, kernel = _windows_libraries()
    sid = _current_sid(advapi, kernel)
    descriptor = ctypes.c_void_p()
    observed = ctypes.c_void_p()
    try:
        sddl = f"D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        dacl = ctypes.c_void_p()
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        if (not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
                or not present.value or not dacl.value):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        if advapi.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        if advapi.GetNamedSecurityInfoW(str(path), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(observed)):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if (not advapi.GetSecurityDescriptorControl(observed, ctypes.byref(control), ctypes.byref(revision))
                or not control.value & 0x1000 or not dacl.value):
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        class ACLSize(ctypes.Structure):
            _fields_ = [("count", wintypes.DWORD), ("used", wintypes.DWORD), ("free", wintypes.DWORD)]

        class AllowedACE(ctypes.Structure):
            _fields_ = [("kind", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                        ("size", wintypes.WORD), ("mask", wintypes.DWORD)]

        info = ACLSize()
        if not advapi.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2) or info.count != 3:
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
        allowed = {sid, "S-1-5-18", "S-1-5-32-544"}
        trustees = set()
        # Compare actual binary SID values, not SDDL aliases (e.g. hosted administrator LA).
        for index in range(info.count):
            address = ctypes.c_void_p()
            if not advapi.GetAce(dacl, index, ctypes.byref(address)) or not address.value:
                raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
            ace = ctypes.cast(address, ctypes.POINTER(AllowedACE)).contents
            if ace.kind != 0 or ace.flags != 3 or ace.mask != 0x1F01FF or ace.size < 16:
                raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
            text = ctypes.c_void_p()
            try:
                if not advapi.ConvertSidToStringSidW(address.value + ctypes.sizeof(AllowedACE), ctypes.byref(text)):
                    raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
                trustee = ctypes.wstring_at(text.value)
                if trustee not in allowed:
                    raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
                trustees.add(trustee)
            finally:
                if text.value:
                    kernel.LocalFree(text)
        if trustees != allowed:
            raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
    finally:
        for pointer in (descriptor, observed):
            if pointer.value:
                kernel.LocalFree(pointer)


def protect_secret_directory(path: Path) -> None:
    """Accept only a new empty task-specific directory, never change an existing config root."""
    if path.is_symlink() or not path.is_dir() or not path.name.startswith("erp-mcp-rsv-") or any(path.iterdir()):
        raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
    try:
        if os.name == "nt":
            _protect_windows(path)
        else:
            path.chmod(0o700)
            info = path.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE")
    except (OSError, TypeError, ValueError):
        raise SecretDirectoryUnavailable("PRIVATE_SECRET_DIRECTORY_UNAVAILABLE") from None
