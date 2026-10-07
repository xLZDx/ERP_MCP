"""Opt-in real bridge crash/reconnect, restricted to the established disposable metadata base.

Reuses audited official v1.3.0 executable + MCP SDK; never implements COM/protocol code.
Pinned source 76fed8e6e16833fee1514969841b8d9a61c7c152 inspected; binary parity is not assumed.
"""
import asyncio
import json
import os
from pathlib import Path

import mcp.client.stdio as sdk_stdio
import pytest
from mcp import ClientSession

from business_ai_gateway.adapters.onec.rsv_bridge import RSVBridgeUnavailable, RSVDataBridgeClient
from business_ai_gateway.models import Source

BASE = Path('D:/ERP_MCP_Testbed/1c/bases/RSVDataAudit')
EXECUTABLE = Path('D:/Temp/ERP_MCP/vendor/rsvdata/v1.3.0/unpacked/MCP-RSV-Data/rsvdata-bridge.exe')
DIGEST = '5c14b7db16e5dbf8cd20e2619255fe849edc75ac514bd6a21dedb1599710d728'
pytestmark = pytest.mark.skipif(
    os.name != 'nt' or os.getenv('BAG_RSV_NATIVE_LIFECYCLE') != '1',
    reason='requires explicit disposable native metadata lifecycle opt-in')


async def test_owned_native_bridge_crash_then_fresh_com_reconnect(monkeypatch, tmp_path):
    # No arbitrary target, connect string, customer config, process name/PID selection or 1C kill.
    assert BASE.is_dir() and (BASE / '1Cv8.1CD').is_file()
    assert not BASE.is_symlink() and not EXECUTABLE.is_symlink()
    source = Source(id='native-lifecycle-synthetic', project='onec', kind='onec_auto',
                    display_name='Disposable metadata lifecycle', base_url='https://synthetic.invalid',
                    username_secret_ref=None, password_secret_ref=None, read_only=True, enabled=True,
                    tags=(), entity_allow_patterns=(), entity_deny_patterns=())
    processes = []
    ephemeral_configs = []
    native_ping_confirmed = []
    spawn = sdk_stdio._create_platform_compatible_process

    async def record_owned_process(**kwargs):
        assert Path(kwargs['command']).resolve() == EXECUTABLE.resolve()
        assert kwargs['args'][0:2] == ['serve', '--config']
        assert '--connect' not in kwargs['args']
        config_path = Path(kwargs['args'][2])
        assert config_path.parent.name.startswith('erp-mcp-rsv-')
        ephemeral_configs.append(config_path)
        process = await spawn(**kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(sdk_stdio, '_create_platform_compatible_process', record_owned_process)

    class CrashAfterNativePing(ClientSession):
        async def call_tool(self, name, arguments=None, **kwargs):
            assert name == 'ping' and arguments == {}
            result = await super().call_tool(name, arguments, **kwargs)
            assert result.is_error is False and result.content
            native_ping_confirmed.append(True)
            assert len(processes) == 1
            owned = processes[0]
            assert owned.returncode is None
            # Only the precise handle returned by this test's SDK spawn is terminated.
            owned.kill()
            async with asyncio.timeout(5):
                await owned.wait()
            # Demonstrate the dead connection cannot return a fabricated healthy response.
            async with asyncio.timeout(5):
                return await super().call_tool('ping', {})

    async def secret_loader(_reference):
        return json.dumps({'kind': 'file', 'file': str(BASE)})

    def client(session_factory=ClientSession):
        return RSVDataBridgeClient(executable=str(EXECUTABLE), config_root=str(tmp_path),
                                   expected_executable_sha256=DIGEST, timeout_seconds=45,
                                   session_factory=session_factory,
                                   config_secret_loader=secret_loader,
                                   config_secret_ref='synthetic-native-metadata-config')

    with pytest.raises(RSVBridgeUnavailable) as failure:
        await client(CrashAfterNativePing).health(source)
    assert native_ping_confirmed == [True]
    assert processes[0].returncode not in (None, 0)
    assert str(BASE) not in str(failure.value) and 'File=' not in str(failure.value)
    assert (await client().health(source))['status'] == 'healthy'
    metadata = await client().metadata(source, operation='config')
    assert metadata['adapter']['executable_sha256'] == DIGEST
    assert len(processes) == 3 and len({process.pid for process in processes}) == 3
    assert all(process.returncode is not None for process in processes)
    assert all(not path.exists() and not path.parent.exists() for path in ephemeral_configs)
    # No business query, no production base, no native engine process kill or raw artifact saved.
