"""Windows host-wide serving-authority mutex for the private 1C writer lane."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import os
import queue
import re
import threading
from ctypes import wintypes
from dataclasses import dataclass, field
from uuid import uuid4

from business_ai_gateway.phase2.change_ledger.write_port import (
    ServingAuthorityLease,
    ServingAuthorityMutex,
)

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED_0 = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_MUTEX_ACCESS = 0x00120001  # SYNCHRONIZE | MUTEX_MODIFY_STATE | READ_CONTROL
_AUTHORITY_COMMAND_TIMEOUT_SECONDS = 5.0
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_KERNEL_OBJECT = 6
_SDDL_REVISION_1 = 1
_SERVICE_SID_PATTERN = re.compile(
    r"S-1-5-80-(?:0|[1-9][0-9]{0,9})(?:-(?:0|[1-9][0-9]{0,9})){4}\Z"
)
_BASE_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_LOCAL_OWNERS_LOCK = threading.Lock()
_LOCAL_OWNERS: set[str] = set()


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    )


@dataclass(slots=True)
class _AuthorityRequest:
    action: str
    lease_id: str | None = None
    completed: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error_code: str | None = None


class _WindowsLease(ServingAuthorityLease):
    __slots__ = ("_lease_id", "_mutex", "_release_started", "_released")

    def __setattr__(self, name: str, value: object) -> None:
        if (name in ("_mutex", "_lease_id") and hasattr(self, name)):
            raise AttributeError("SERVING_AUTHORITY_LEASE_CONFIGURATION_IMMUTABLE")
        if name in ("_released", "_release_started") and hasattr(self, name):
            if getattr(self, name) is not False or value is not True:
                raise AttributeError("SERVING_AUTHORITY_LEASE_RELEASED_STATE_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SERVING_AUTHORITY_LEASE_CONFIGURATION_IMMUTABLE")

    def __init__(self, mutex: WindowsServingAuthorityMutex, lease_id: str) -> None:
        self._mutex = mutex
        self._lease_id = lease_id
        self._released = False
        self._release_started = False

    def assert_held(self) -> None:
        if self._released or self._release_started:
            raise RuntimeError("SERVING_AUTHORITY_LEASE_NOT_HELD")
        self._mutex._assert_held(self)

    async def release(self) -> None:
        self.assert_held()
        self._release_started = True
        await self._mutex._release(self)
        self._released = True


class WindowsServingAuthorityMutex(ServingAuthorityMutex):
    """A named Windows mutex restricted to SYSTEM and one service SID.

    A dedicated non-daemon owner thread acquires and releases the kernel mutex. Logical
    leases may be used by asyncio tasks on other threads without tying kernel ownership to
    an event-loop thread: if that loop exits unexpectedly, the authority thread still holds
    the mutex until an explicit release or process exit. Async ``try_acquire`` performs a
    zero-timeout OS wait and awaits its bounded owner-thread response without blocking the event
    loop. The name is deterministic per physical 1C base and requires its
    canonical lower-case SHA-256 fingerprint. A process-local registry prevents recursive
    acquisition when two Python objects in this process refer to that same named mutex.
    """

    __slots__ = (
        "_active_lease_id",
        "_advapi32",
        "_close_task",
        "_closed",
        "_closing",
        "_commands",
        "_configuration_frozen",
        "_handle",
        "_kernel32",
        "_name",
        "_registry_key",
        "_state_lock",
        "_worker",
        "_worker_failed",
    )
    _CONFIGURATION_FIELDS = frozenset({
        "_name", "_registry_key", "_kernel32", "_advapi32", "_handle", "_commands",
        "_state_lock", "_worker",
    })
    _LIFECYCLE_FIELDS = frozenset({
        "_closed", "_closing", "_active_lease_id", "_worker_failed", "_close_task",
    })

    def __setattr__(self, name: str, value: object) -> None:
        if name == "_configuration_frozen" or (
            name in type(self)._CONFIGURATION_FIELDS
            and getattr(self, "_configuration_frozen", False)
        ):
            raise AttributeError("SERVING_AUTHORITY_CONFIGURATION_IMMUTABLE")
        if (name in type(self)._LIFECYCLE_FIELDS
                and getattr(self, "_configuration_frozen", False)):
            raise AttributeError("SERVING_AUTHORITY_LIFECYCLE_STATE_INTERNAL")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SERVING_AUTHORITY_CONFIGURATION_IMMUTABLE")

    def __init__(self, base_fingerprint: str, service_sid: str) -> None:
        if os.name != "nt":
            raise OSError("WINDOWS_SERVING_AUTHORITY_MUTEX_REQUIRES_WINDOWS")
        if (type(base_fingerprint) is not str
                or _BASE_FINGERPRINT_PATTERN.fullmatch(base_fingerprint) is None):
            raise ValueError("INVALID_BASE_FINGERPRINT")
        if type(service_sid) is str and service_sid.casefold() == "s-1-5-18":
            raise ValueError("SERVICE_SID_MUST_NOT_BE_SYSTEM")
        if (type(service_sid) is not str
                or _SERVICE_SID_PATTERN.fullmatch(service_sid) is None
                or any(int(part) > 0xFFFFFFFF for part in service_sid.split("-")[4:])):
            raise ValueError("INVALID_SERVICE_SID")
        WindowsServingAuthorityMutex._assert_process_has_service_sid(service_sid)

        object.__setattr__(self, "_configuration_frozen", False)
        self._name = (
            "Global\\ERP_MCP.S13.ServingAuthority."
            + hashlib.sha256(base_fingerprint.encode("utf-8")).hexdigest()
        )
        self._registry_key = self._name.casefold()
        self._closed = False
        self._closing = False
        self._active_lease_id: str | None = None
        self._worker_failed = False
        self._close_task: asyncio.Task[None] | None = None
        self._commands: queue.Queue[_AuthorityRequest] = queue.Queue()
        self._state_lock = threading.Lock()
        self._kernel32, self._advapi32 = self._load_apis()
        # CreateMutexExW's third argument is flags and fourth is desired access.
        self._kernel32.CreateMutexExW.argtypes = (
            ctypes.POINTER(_SecurityAttributes), wintypes.LPCWSTR,
            wintypes.DWORD, wintypes.DWORD,
        )
        self._kernel32.CreateMutexExW.restype = wintypes.HANDLE
        self._kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        self._kernel32.ReleaseMutex.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            wintypes.BOOL
        )
        self._advapi32.GetSecurityInfo.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        )
        self._advapi32.GetSecurityInfo.restype = wintypes.DWORD
        self._advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = (
            wintypes.BOOL
        )
        self._kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        self._kernel32.LocalFree.restype = ctypes.c_void_p

        # Pin the owner as well as a protected DACL. Otherwise a malicious process
        # could pre-create the name, own the object, and later broaden its DACL.
        sddl = (
            f"O:{service_sid}D:P(A;;0x00120001;;;SY)"
            f"(A;;0x00120001;;;{service_sid})"
        )
        descriptor = ctypes.c_void_p()
        descriptor_size = wintypes.DWORD()
        converted = self._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, _SDDL_REVISION_1, ctypes.byref(descriptor), ctypes.byref(descriptor_size),
        )
        if not converted:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            attributes = _SecurityAttributes(
                ctypes.sizeof(_SecurityAttributes), descriptor, False,
            )
            self._handle = self._kernel32.CreateMutexExW(
                ctypes.byref(attributes), self._name, 0, _MUTEX_ACCESS,
            )
            if not self._handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                self._verify_security_descriptor(sddl)
            except BaseException as verification_error:
                handle = self._handle
                if not self._kernel32.CloseHandle(handle):
                    close_error = ctypes.WinError(ctypes.get_last_error())
                    raise close_error from verification_error
                self._handle = None
                raise
        finally:
            self._kernel32.LocalFree(descriptor)
        self._worker = threading.Thread(
            target=self._serve_authority_commands,
            name="erp-mcp-serving-authority-owner",
            daemon=False,
        )
        try:
            self._worker.start()
        except Exception:
            if not self._kernel32.CloseHandle(self._handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = None
            raise RuntimeError("SERVING_AUTHORITY_THREAD_START_FAILED") from None
        object.__setattr__(self, "_configuration_frozen", True)

    def _serve_authority_commands(self) -> None:
        """Keep kernel-mutex ownership on a stable thread, independent of the event loop."""
        while True:
            request = self._commands.get()
            should_exit = False
            try:
                if request.action == "acquire":
                    with self._state_lock:
                        if self._worker_failed or self._closing or self._closed:
                            request.error_code = "SERVING_AUTHORITY_UNAVAILABLE"
                        elif self._active_lease_id is not None:
                            request.result = None
                        else:
                            result = self._kernel32.WaitForSingleObject(self._handle, 0)
                            if result == _WAIT_TIMEOUT:
                                request.result = None
                            elif result in (_WAIT_OBJECT_0, _WAIT_ABANDONED_0):
                                object.__setattr__(self, "_active_lease_id", request.lease_id)
                                request.result = request.lease_id
                            else:
                                object.__setattr__(self, "_worker_failed", True)
                                request.error_code = "SERVING_AUTHORITY_WAIT_FAILED"
                elif request.action == "release":
                    with self._state_lock:
                        if request.lease_id is None or self._active_lease_id != request.lease_id:
                            request.error_code = "SERVING_AUTHORITY_LEASE_MISMATCH"
                        elif not self._kernel32.ReleaseMutex(self._handle):
                            # Keep this thread alive and retain logical ownership. Letting the
                            # owner thread exit could abandon the kernel mutex while this process
                            # still has other live components.
                            object.__setattr__(self, "_worker_failed", True)
                            request.error_code = "SERVING_AUTHORITY_RELEASE_FAILED"
                        else:
                            object.__setattr__(self, "_active_lease_id", None)
                            request.result = True
                    if request.error_code is None:
                        with _LOCAL_OWNERS_LOCK:
                            _LOCAL_OWNERS.discard(self._registry_key)
                elif request.action == "close":
                    with self._state_lock:
                        if self._active_lease_id is not None:
                            request.error_code = "SERVING_AUTHORITY_MUTEX_STILL_HELD"
                        elif not self._kernel32.CloseHandle(self._handle):
                            object.__setattr__(self, "_worker_failed", True)
                            request.error_code = "SERVING_AUTHORITY_HANDLE_CLOSE_FAILED"
                        else:
                            object.__setattr__(self, "_closed", True)
                            request.result = True
                            should_exit = True
                else:
                    object.__setattr__(self, "_worker_failed", True)
                    request.error_code = "SERVING_AUTHORITY_COMMAND_INVALID"
            except BaseException:
                # The owner thread must not silently exit after an API failure. A lease that
                # cannot be released remains fail-closed until process termination.
                with self._state_lock:
                    object.__setattr__(self, "_worker_failed", True)
                request.error_code = "SERVING_AUTHORITY_COMMAND_FAILED"
            finally:
                request.completed.set()
            if should_exit:
                return

    def _request(self, action: str, lease_id: str | None = None) -> object:
        request = _AuthorityRequest(action=action, lease_id=lease_id)
        self._commands.put(request)
        if not request.completed.wait(_AUTHORITY_COMMAND_TIMEOUT_SECONDS):
            raise RuntimeError("SERVING_AUTHORITY_COMMAND_TIMEOUT")
        if request.error_code is not None:
            raise RuntimeError(request.error_code)
        return request.result

    def _assert_held(self, lease: _WindowsLease) -> None:
        with self._state_lock:
            if (lease._mutex is not self or lease._released or self._worker_failed
                    or self._active_lease_id != lease._lease_id):
                raise RuntimeError("SERVING_AUTHORITY_LEASE_NOT_HELD")

    @staticmethod
    def _assert_process_has_service_sid(service_sid: str) -> None:
        """Require the configured ACL principal to belong to this process token.

        A caller-supplied SID alone does not bind the mutex ACL to the process that owns the
        serving lease. Accept the service SID as the token user (virtual service account) or as an
        enabled group (service SID on a dedicated Windows service); reject absent/disabled groups
        before creating or opening the named kernel object.
        """
        token = None
        try:
            import win32api
            import win32security

            token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), 0x0008)
            user_sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
            if win32security.ConvertSidToStringSid(user_sid).casefold() == service_sid.casefold():
                return
            groups = win32security.GetTokenInformation(token, win32security.TokenGroups)
            enabled = 0x00000004
            deny_only = 0x00000010
            if any(
                    attributes & enabled and not attributes & deny_only
                    and win32security.ConvertSidToStringSid(sid).casefold()
                    == service_sid.casefold()
                    for sid, attributes in groups):
                return
        except Exception:
            raise PermissionError("SERVICE_SID_IDENTITY_UNAVAILABLE") from None
        finally:
            if token is not None:
                try:
                    token.Close()
                except Exception:
                    raise PermissionError("SERVICE_SID_IDENTITY_UNAVAILABLE") from None
        raise PermissionError("SERVICE_SID_NOT_IN_PROCESS_TOKEN")

    def _verify_security_descriptor(self, expected_sddl: str) -> None:
        """Reject a pre-created same-name object with a different owner or DACL."""
        security_descriptor = ctypes.c_void_p()
        owner = ctypes.c_void_p()
        status = self._advapi32.GetSecurityInfo(
            self._handle, _SE_KERNEL_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner), None, None, None, ctypes.byref(security_descriptor),
        )
        if status != 0:
            raise ctypes.WinError(status)
        try:
            actual_sddl = wintypes.LPWSTR()
            actual_length = wintypes.DWORD()
            converted = self._advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                security_descriptor, _SDDL_REVISION_1,
                _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
                ctypes.byref(actual_sddl), ctypes.byref(actual_length),
            )
            if not converted:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if actual_sddl.value.casefold() != expected_sddl.casefold():
                    raise PermissionError("SERVING_AUTHORITY_MUTEX_DACL_MISMATCH")
            finally:
                self._kernel32.LocalFree(ctypes.cast(actual_sddl, ctypes.c_void_p))
        finally:
            self._kernel32.LocalFree(security_descriptor)

    @staticmethod
    def _load_apis() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
        if os.name != "nt":
            raise OSError("WINDOWS_SERVING_AUTHORITY_MUTEX_REQUIRES_WINDOWS")
        return (
            ctypes.WinDLL("kernel32", use_last_error=True),
            ctypes.WinDLL("advapi32", use_last_error=True),
        )

    async def try_acquire(self) -> ServingAuthorityLease | None:
        """Acquire without blocking the event loop or registering an OS waiter."""
        with _LOCAL_OWNERS_LOCK, self._state_lock:
            if self._closed or self._closing:
                raise RuntimeError("SERVING_AUTHORITY_MUTEX_CLOSED")
            if self._worker_failed or not self._worker.is_alive():
                raise RuntimeError("SERVING_AUTHORITY_UNAVAILABLE")
            if self._registry_key in _LOCAL_OWNERS:
                return None
            _LOCAL_OWNERS.add(self._registry_key)

        lease_id = str(uuid4())
        try:
            # The OS wait itself is zero-timeout, but the owner thread may be descheduled.
            # Keep its bounded response wait off the request/event-loop thread.
            result = await asyncio.to_thread(self._request, "acquire", lease_id)
        except BaseException:
            # Cancellation or any request failure can hide an acquire that the owner thread is
            # still processing. Keep the process-local reservation to prevent recursion.
            raise
        if result is None:
            with _LOCAL_OWNERS_LOCK, self._state_lock:
                _LOCAL_OWNERS.discard(self._registry_key)
            return None
        if result != lease_id:
            raise RuntimeError("SERVING_AUTHORITY_RESPONSE_INVALID")
        try:
            return _WindowsLease(self, lease_id)
        except Exception:
            # If local lease construction fails, ask the stable owner thread to release.
            try:
                await asyncio.to_thread(self._request, "release", lease_id)
            except Exception:
                with self._state_lock:
                    object.__setattr__(self, "_worker_failed", True)
            raise

    async def _release(self, lease: _WindowsLease) -> None:
        if lease._mutex is not self:
            raise RuntimeError("SERVING_AUTHORITY_LEASE_OWNER_MISMATCH")
        result = await asyncio.to_thread(self._request, "release", lease._lease_id)
        if result is not True:
            raise RuntimeError("SERVING_AUTHORITY_RELEASE_FAILED")

    async def close_async(self) -> None:
        """Close the owner thread without blocking the service event loop."""
        close_task = self._close_task
        if close_task is None:
            close_task = asyncio.create_task(asyncio.to_thread(self.close))
            object.__setattr__(self, "_close_task", close_task)
        # Retain one task even across caller cancellation. A retry joins the same command and
        # cannot enqueue a duplicate close that races the owner thread's exit.
        await asyncio.shield(close_task)

    def close(self) -> None:
        """Stop the owner thread and close its handle after all logical leases are released."""
        already_closed = False
        with _LOCAL_OWNERS_LOCK, self._state_lock:
            if self._closed:
                already_closed = True
            elif self._registry_key in _LOCAL_OWNERS:
                raise RuntimeError("SERVING_AUTHORITY_MUTEX_STILL_HELD")
            else:
                object.__setattr__(self, "_closing", True)
        if not already_closed:
            result = self._request("close")
            if result is not True:
                raise RuntimeError("SERVING_AUTHORITY_HANDLE_CLOSE_FAILED")
        self._worker.join(timeout=_AUTHORITY_COMMAND_TIMEOUT_SECONDS)
        if self._worker.is_alive():
            raise RuntimeError("SERVING_AUTHORITY_THREAD_STOP_TIMEOUT")
