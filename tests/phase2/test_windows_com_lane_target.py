from __future__ import annotations

import asyncio
import struct
import sys
import types
from pathlib import Path
import ntpath

import pytest

from erp_mcp_private_writer.com_sta_lane import ComLaneError
import erp_mcp_private_writer.windows_com_lane as windows_com_lane_module
from erp_mcp_private_writer.windows_com_lane import windows_com_sta_lane


_FINGERPRINT = "a" * 64


class _Connector:
    def __init__(self):
        self.connect_calls = []

    def Connect(self, value):
        self.connect_calls.append(value)
        return types.SimpleNamespace(
            InfoBaseUsers=types.SimpleNamespace(
                CurrentUser=lambda: types.SimpleNamespace(Name="clone-writer")
            )
        )


def _install_fake_com(monkeypatch, connector):
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda prog_id: connector if prog_id == "V83.COMConnector" else None
    win32com = types.ModuleType("win32com")
    win32com.client = client
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.COINIT_APARTMENTTHREADED = 2
    pythoncom.CoInitializeEx = lambda _mode: None
    pythoncom.CoUninitialize = lambda: None
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)


def _make_lane(base: Path, connection_value: str):
    return windows_com_sta_lane(
        connection_string=lambda: connection_value,
        expected_base_fingerprint=_FINGERPRINT,
        expected_user_name="clone-writer",
        expected_file_database_path=str(base),
        read_base_fingerprint=lambda _connection: _FINGERPRINT,
    )


def test_windows_com_lane_connects_to_exact_pinned_file_database(tmp_path, monkeypatch):
    if struct.calcsize("P") != 8:
        pytest.skip("the Windows COM lane intentionally requires a 64-bit process")
    base = tmp_path / "approved-clone"
    base.mkdir()
    connector = _Connector()
    _install_fake_com(monkeypatch, connector)
    connection = f'File="{base}";Usr="clone-writer";Pwd="fixture"'
    lane = _make_lane(base, connection)

    asyncio.run(lane.start())
    assert connector.connect_calls == [connection]
    asyncio.run(lane.close_after_drain())


@pytest.mark.parametrize(
    "target_kind", ["different_file", "server", "missing_file", "duplicate_file", "relative_file"]
)
def test_windows_com_lane_refuses_unpinned_targets_before_connector_connect(
        tmp_path, monkeypatch, target_kind):
    if struct.calcsize("P") != 8:
        pytest.skip("the Windows COM lane intentionally requires a 64-bit process")
    approved = tmp_path / "approved-clone"
    approved.mkdir()
    different = tmp_path / "other-clone"
    different.mkdir()
    if target_kind == "different_file":
        connection = f'File="{different}";Usr="clone-writer";Pwd="fixture"'
    elif target_kind == "server":
        connection = 'Srvr="public.example";Ref="accounting";Usr="clone-writer";Pwd="fixture"'
    elif target_kind == "missing_file":
        connection = 'Usr="clone-writer";Pwd="fixture"'
    elif target_kind == "duplicate_file":
        connection = (f'File="{approved}";File="{different}";'
                      'Usr="clone-writer";Pwd="fixture"')
    else:
        connection = 'File=".";Usr="clone-writer";Pwd="fixture"'

    connector = _Connector()
    _install_fake_com(monkeypatch, connector)
    lane = _make_lane(approved, connection)

    with pytest.raises(ComLaneError) as exc_info:
        asyncio.run(lane.start())
    assert exc_info.value.code == "COM_CONNECTION_TARGET_NOT_ALLOWED"
    asyncio.run(lane.close_after_drain())
    assert connector.connect_calls == []


def test_windows_com_lane_rejects_nonexistent_expected_base_at_construction(tmp_path):
    nonexistent = tmp_path / "not-created"
    with pytest.raises(ValueError, match="COM_LANE_FILE_TARGET_INVALID"):
        _make_lane(nonexistent, f'File="{nonexistent}";Usr="clone-writer"')


def test_windows_com_lane_rejects_relative_expected_base_at_construction():
    with pytest.raises(ValueError, match="COM_LANE_FILE_TARGET_INVALID"):
        windows_com_sta_lane(
            connection_string=lambda: 'File=".";Usr="clone-writer"',
            expected_base_fingerprint=_FINGERPRINT,
            expected_user_name="clone-writer",
            expected_file_database_path=".",
            read_base_fingerprint=lambda _connection: _FINGERPRINT,
        )


def test_windows_com_lane_rejects_unc_expected_and_supplied_paths_without_network_access(
        tmp_path, monkeypatch):
    if struct.calcsize("P") != 8:
        pytest.skip("the Windows COM lane intentionally requires a 64-bit process")

    resolved_paths = []

    class _PathProbe:
        def __init__(self, value):
            self.value = str(value)

        def resolve(self, *, strict):
            assert strict is True
            resolved_paths.append(self.value)
            return self

        def is_dir(self):
            return True

        def is_absolute(self):
            return ntpath.isabs(self.value)

        def __str__(self):
            return self.value

    monkeypatch.setattr(windows_com_lane_module, "Path", _PathProbe)
    with pytest.raises(ValueError, match="COM_LANE_FILE_TARGET_INVALID"):
        windows_com_sta_lane(
            connection_string=lambda: 'File="D:\\approved";Usr="clone-writer"',
            expected_base_fingerprint=_FINGERPRINT,
            expected_user_name="clone-writer",
            expected_file_database_path=r"\\fileserver\share\base",
            read_base_fingerprint=lambda _connection: _FINGERPRINT,
        )
    assert resolved_paths == []

    approved = r"D:\approved"
    connector = _Connector()
    _install_fake_com(monkeypatch, connector)
    lane = windows_com_sta_lane(
        connection_string=lambda: r'File="\\fileserver\share\base";Usr="clone-writer"',
        expected_base_fingerprint=_FINGERPRINT,
        expected_user_name="clone-writer",
        expected_file_database_path=approved,
        read_base_fingerprint=lambda _connection: _FINGERPRINT,
    )
    with pytest.raises(ComLaneError) as refusal:
        asyncio.run(lane.start())
    asyncio.run(lane.close_after_drain())
    assert refusal.value.code == "COM_CONNECTION_TARGET_NOT_ALLOWED"
    assert resolved_paths == [approved]
    assert connector.connect_calls == []
