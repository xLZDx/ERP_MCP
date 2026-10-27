"""Lazy Windows COMConnector composition for the private writer STA lane.

Importing this module is safe off Windows. pywin32 is loaded only inside the lane
callbacks, which execute on the dedicated worker thread after the caller starts it.
The injected connection-string provider runs in that same worker and its value is
never logged or retained by this module after Connect returns.
"""

from __future__ import annotations

import hmac
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .com_sta_lane import ComLaneError, ComStaLane

_MAX_CONNECTION_STRING_CHARS = 16_384
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(slots=True, repr=False)
class _ComSession:
    """Worker-confined references; never returned to an async caller."""

    connector: Any
    connection: Any


def windows_com_sta_lane(*, connection_string: Callable[[], str],
                         expected_base_fingerprint: str,
                         expected_user_name: str,
                         read_base_fingerprint: Callable[[Any], str]) -> ComStaLane:
    """Build an unstarted STA lane using the installed Windows ``V83.COMConnector``.

    The provider must return the approved private-lane connection string from an
    in-process secret source. It is called only on the worker thread and is not
    evaluated until ``ComStaLane.start``. The injected read-only fingerprint
    function must measure the connected base; the session is not exposed to
    operations unless its SHA-256 equals ``expected_base_fingerprint``. This
    function does not connect or read configuration by itself.
    """
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

    return ComStaLane(
        connect=connect,
        disconnect=disconnect,
        initialize_sta=initialize_sta,
        uninitialize_sta=uninitialize_sta,
    )
