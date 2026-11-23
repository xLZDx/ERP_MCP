"""Lazy Windows COMConnector composition for the private writer STA lane.

Importing this module is safe off Windows. pywin32 is loaded only inside the lane
callbacks, which execute on the dedicated worker thread after the caller starts it.
The injected connection-string provider runs in that same worker and its value is
never logged or retained by this module after Connect returns.
"""

from __future__ import annotations

import hmac
import ntpath
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .com_sta_lane import ComLaneError, ComStaLane

_MAX_CONNECTION_STRING_CHARS = 16_384
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_FILE_TARGET = re.compile(r'(?:^|;)\s*File\s*=\s*(?:"([^"]*)"|([^;]*))\s*(?:;|$)', re.IGNORECASE)
_FILE_KEY = re.compile(r"(?:^|;)\s*File\s*=", re.IGNORECASE)
_SERVER_KEY = re.compile(r"(?:^|;)\s*Srvr\s*=", re.IGNORECASE)


def _absolute_local_drive_path(value: object) -> bool:
    if type(value) is not str or not value or "\x00" in value:
        return False
    drive, tail = ntpath.splitdrive(value)
    return (
        len(drive) == 2 and drive[1] == ":" and ntpath.isabs(value)
        and tail.startswith(("\\", "/"))
    )


@dataclass(slots=True, repr=False)
class _ComSession:
    """Worker-confined references; never returned to an async caller."""

    connector: Any
    connection: Any


_WINDOWS_LANE_FACTORY_TOKEN = object()


class WindowsComStaLane:
    """Factory-qualified wrapper for a local-file-pinned Windows COM STA lane."""

    __slots__ = ("_lane", "_target_fingerprint")

    def __init__(self, lane: ComStaLane, target_fingerprint: str, *, _factory_token: object) -> None:
        if (_factory_token is not _WINDOWS_LANE_FACTORY_TOKEN or type(lane) is not ComStaLane
                or type(target_fingerprint) is not str or _SHA256_HEX.fullmatch(target_fingerprint) is None):
            raise ValueError("COM_LANE_CONFIGURATION_INVALID")
        object.__setattr__(self, "_lane", lane)
        object.__setattr__(self, "_target_fingerprint", target_fingerprint)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("COM_LANE_CONFIGURATION_IMMUTABLE")

    def __delattr__(self, _name: str) -> None:
        raise AttributeError("COM_LANE_CONFIGURATION_IMMUTABLE")

    @property
    def target_fingerprint(self) -> str:
        return self._target_fingerprint

    @property
    def state(self):
        return self._lane.state

    async def start(self) -> None:
        await self._lane.start()

    async def invoke(self, operation):
        return await self._lane.invoke(operation)

    async def close_after_drain(self) -> None:
        await self._lane.close_after_drain()


def windows_com_sta_lane(*, connection_string: Callable[[], str],
                         expected_base_fingerprint: str,
                         expected_user_name: str,
                         expected_file_database_path: str,
                         read_base_fingerprint: Callable[[Any], str]) -> WindowsComStaLane:
    """Build an unstarted STA lane using the installed Windows ``V83.COMConnector``.

    The provider must return the approved private-lane connection string from an
    in-process secret source. It is called only on the worker thread and is not
    evaluated until ``ComStaLane.start``. The injected read-only fingerprint
    function must measure the connected base; the session is not exposed to
    operations unless its SHA-256 equals ``expected_base_fingerprint``. This
    function does not connect or read configuration by itself.
    """
    if not _absolute_local_drive_path(expected_file_database_path):
        raise ValueError("COM_LANE_FILE_TARGET_INVALID")
    try:
        supplied_path = Path(expected_file_database_path)
        expected_path = supplied_path.resolve(strict=True)
        expected_drive, _ = ntpath.splitdrive(str(expected_path))
        if not expected_path.is_dir():
            raise ValueError
        if not supplied_path.is_absolute() or len(expected_drive) != 2 or expected_drive[1] != ":":
            raise ValueError
        expected_path_key = ntpath.normcase(ntpath.normpath(str(expected_path)))
    except (OSError, TypeError, ValueError):
        raise ValueError("COM_LANE_FILE_TARGET_INVALID") from None
    if (not callable(connection_string) or not callable(read_base_fingerprint)
            or type(expected_base_fingerprint) is not str
            or _SHA256_HEX.fullmatch(expected_base_fingerprint) is None
            or type(expected_user_name) is not str or not expected_user_name
            or expected_user_name != expected_user_name.strip()
            or len(expected_user_name) > 256
            or any(not character.isprintable() for character in expected_user_name)):
        raise ValueError("COM_LANE_CONFIGURATION_INVALID")

    def initialize_sta() -> None:
        import pythoncom

        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)

    def uninitialize_sta() -> None:
        import pythoncom

        pythoncom.CoUninitialize()

    def connect() -> _ComSession:
        # The authorized Ivan lane currently registers the COMConnector from an x64 1C install.
        # Reject a 32-bit Python process before COM activation rather than surfacing an opaque
        # registration error or trying another registry view.
        if struct.calcsize("P") != 8:
            raise ComLaneError("COM_LANE_ARCHITECTURE_UNSUPPORTED")
        try:
            import win32com.client

            connector = win32com.client.Dispatch("V83.COMConnector")
        except Exception:
            raise ComLaneError("COM_ACTIVATION_FAILED") from None
        connection = None
        value = None
        try:
            try:
                value = connection_string()
            except Exception:
                raise ComLaneError("COM_CONNECTION_CONFIGURATION_FAILED") from None
            if (type(value) is not str or not value or len(value) > _MAX_CONNECTION_STRING_CHARS
                    or "\x00" in value):
                raise ComLaneError("COM_CONNECTION_CONFIGURATION_FAILED")
            # This lane is pinned to one local disposable file database. Reject server-mode
            # COM targets and ambiguous duplicate File parameters before COM sees any credentials.
            file_matches = list(_FILE_TARGET.finditer(value))
            if (len(file_matches) != 1 or len(list(_FILE_KEY.finditer(value))) != 1
                    or _SERVER_KEY.search(value) is not None):
                raise ComLaneError("COM_CONNECTION_TARGET_NOT_ALLOWED")
            configured_path = file_matches[0].group(1) or file_matches[0].group(2)
            if (type(configured_path) is not str
                    or not _absolute_local_drive_path(configured_path.strip())):
                raise ComLaneError("COM_CONNECTION_TARGET_NOT_ALLOWED")
            try:
                supplied_actual_path = Path(configured_path.strip())
                actual_path = supplied_actual_path.resolve(strict=True)
                actual_drive, _ = ntpath.splitdrive(str(actual_path))
                actual_path_key = ntpath.normcase(ntpath.normpath(str(actual_path)))
            except (OSError, TypeError, ValueError):
                raise ComLaneError("COM_CONNECTION_TARGET_NOT_ALLOWED") from None
            if (not supplied_actual_path.is_absolute() or not actual_path.is_dir()
                    or len(actual_drive) != 2 or actual_drive[1] != ":"
                    or not hmac.compare_digest(actual_path_key, expected_path_key)):
                raise ComLaneError("COM_CONNECTION_TARGET_NOT_ALLOWED")
            try:
                connection = connector.Connect(value)
            except Exception:
                raise ComLaneError("COM_CONNECT_FAILED") from None
            value = None
            if connection is None:
                raise ComLaneError("COM_CONNECT_FAILED")
            try:
                actual_user_name = connection.InfoBaseUsers.CurrentUser().Name
            except Exception:
                raise ComLaneError("COM_BASE_USER_UNAVAILABLE") from None
            if (type(actual_user_name) is not str
                    or len(actual_user_name) > 256
                    or not actual_user_name.isprintable()
                    or not hmac.compare_digest(
                        actual_user_name.encode("utf-8"), expected_user_name.encode("utf-8"))):
                raise ComLaneError("COM_BASE_USER_MISMATCH")
            try:
                actual_fingerprint = read_base_fingerprint(connection)
            except Exception:
                raise ComLaneError("COM_BASE_FINGERPRINT_UNAVAILABLE") from None
            if (type(actual_fingerprint) is not str
                    or _SHA256_HEX.fullmatch(actual_fingerprint) is None
                    or not hmac.compare_digest(actual_fingerprint, expected_base_fingerprint)):
                raise ComLaneError("COM_BASE_FINGERPRINT_MISMATCH")
            return _ComSession(connector=connector, connection=connection)
        except Exception as exc:
            # Drop references on the STA worker; do not surface connector details.
            value = None
            connection = None
            connector = None
            if type(exc) is ComLaneError and exc.code in {
                "COM_CONNECTION_CONFIGURATION_FAILED",
                "COM_CONNECTION_TARGET_NOT_ALLOWED",
                "COM_CONNECT_FAILED",
                "COM_BASE_USER_UNAVAILABLE",
                "COM_BASE_USER_MISMATCH",
                "COM_BASE_FINGERPRINT_UNAVAILABLE",
                "COM_BASE_FINGERPRINT_MISMATCH",
            }:
                raise
            raise ComLaneError("COM_CONNECT_FAILED") from None

    def disconnect(session: Any) -> None:
        if type(session) is not _ComSession:
            raise RuntimeError
        session.connection = None
        session.connector = None

    lane = ComStaLane(
        connect=connect,
        disconnect=disconnect,
        initialize_sta=initialize_sta,
        uninitialize_sta=uninitialize_sta,
    )
    return WindowsComStaLane(lane, expected_base_fingerprint,
                             _factory_token=_WINDOWS_LANE_FACTORY_TOKEN)
