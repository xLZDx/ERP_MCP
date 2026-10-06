import asyncio
import json
import logging
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from mcp.client.stdio import StdioServerParameters

from business_ai_gateway.adapters.onec.rsv_bridge import RSVBridgeUnavailable, RSVDataBridgeClient
from business_ai_gateway.adapters.onec.rsv_privacy import (
    private_rsv_diagnostics,
    quiet_stdio_client,
)
from business_ai_gateway.secret_files import SecretDirectoryUnavailable, protect_secret_directory
from tests.test_rsv_bridge import _source


def test_new_empty_task_directory_is_protected_with_actual_os_controls():
    with tempfile.TemporaryDirectory(prefix="erp-mcp-rsv-") as directory:
        path = Path(directory)
        protect_secret_directory(path)  # Windows verifies protected DACL/trustees via read-back.
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o700
        (path / "synthetic-config.json").write_text("{}")
        with pytest.raises(SecretDirectoryUnavailable):
            protect_secret_directory(path)  # never rewrites a populated directory's ACL


def test_existing_non_task_directory_is_never_modified(tmp_path):
    before = tmp_path.stat().st_mode
    with pytest.raises(SecretDirectoryUnavailable):
        protect_secret_directory(tmp_path)
    assert tmp_path.stat().st_mode == before


def test_sdk_payload_exception_and_file_paths_are_not_logged_and_context_resets(caplog):
    logger = logging.getLogger("mcp.client.stdio")
    with caplog.at_level(logging.WARNING):
        with private_rsv_diagnostics():
            try:
                raise ValueError("PRIVATE-FIXTURE-SECRET")
            except ValueError:
                logger.exception("malformed payload %s", "PRIVATE-FIXTURE-SECRET", stack_info=True)
            logger.warning("payload", extra={"raw_response": "PRIVATE-STRUCTURED-SECRET"})
        logger.warning("outside adapter public diagnostic")
    assert "PRIVATE-FIXTURE-SECRET" not in caplog.text
    assert all("PRIVATE-STRUCTURED-SECRET" not in str(vars(item)) for item in caplog.records)
    assert "RSV_ADAPTER_DIAGNOSTIC" in caplog.text
    assert "outside adapter public diagnostic" in caplog.text
    record = next(item for item in caplog.records if item.msg == "RSV_ADAPTER_DIAGNOSTIC")
    assert record.exc_info is record.exc_text is record.stack_info is None
    assert record.pathname == "<rsv-adapter>"


@pytest.mark.asyncio
async def test_actual_sdk_stdio_process_discards_raw_stderr(capfd):
    parameters = StdioServerParameters(command=sys.executable, args=["-c",
        "import sys; sys.stderr.write('PRIVATE-STDERR-SECRET\\n'); sys.stderr.flush(); print('{\"password\":\"PRIVATE-STDOUT-SECRET\"}',flush=True)"])
    with private_rsv_diagnostics():
        async with quiet_stdio_client(parameters) as (read, _write):
            async with asyncio.timeout(20):
                await read.receive()
    captured = capfd.readouterr()
    assert "PRIVATE-STDERR-SECRET" not in captured.out + captured.err
    assert "PRIVATE-STDOUT-SECRET" not in captured.out + captured.err


@pytest.mark.skipif(os.name != "nt", reason="actual NTFS ACL inheritance proof requires Windows")
def test_secret_file_inherits_only_the_three_trusted_directory_aces():
    with tempfile.TemporaryDirectory(prefix="erp-mcp-rsv-") as directory:
        parent = Path(directory)
        protect_secret_directory(parent)
        child = parent / "synthetic-config.json"
        child.write_text("{}")
        environment = {name: os.environ[name] for name in
                       ("PATH", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
                       if name in os.environ}
        environment["ERP_MCP_ACL_FIXTURE"] = str(child)
        # Windows PowerShell 5.1 must not inherit a PowerShell 7 module search path.
        environment["PSModulePath"] = str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "Modules")
        # Constant script; path is an environment value, never interpolated as executable text.
        script = """
        $ErrorActionPreference = 'Stop'
        try {
        $rsvAcl = Get-Acl -LiteralPath $env:ERP_MCP_ACL_FIXTURE
        $rsvIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $rsvAllowed = @($rsvIdentity, 'S-1-5-18', 'S-1-5-32-544')
        $rsvRules = $rsvAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
        $rsvUnexpected = @($rsvRules | Where-Object {
          $_.IdentityReference.Value -notin $rsvAllowed -or
          $_.AccessControlType -ne 'Allow'
        })
        @{unexpected=$rsvUnexpected.Count; total=$rsvRules.Count;
          inherited=@($rsvRules | Where-Object IsInherited).Count} | ConvertTo-Json -Compress
        } catch {
          @{error_id=$_.FullyQualifiedErrorId; category=$_.CategoryInfo.Category.ToString()} | ConvertTo-Json -Compress
          exit 1
        }
        """
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                env=environment, capture_output=True, text=True, timeout=45,
                                creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        assert result.returncode == 0, result.stdout
        assert json.loads(result.stdout) == {"unexpected": 0, "total": 3, "inherited": 3}


@pytest.mark.asyncio
async def test_secret_protection_failure_prevents_materialization_and_process_launch(monkeypatch, tmp_path):
    import business_ai_gateway.adapters.onec.rsv_bridge as bridge

    executable = tmp_path / "fixture.exe"
    executable.touch()
    paths = []

    def unprotectable(path):
        paths.append(path)
        assert not any(path.iterdir())
        raise SecretDirectoryUnavailable("PRIVATE-FIXTURE-SECRET")

    async def loader(_ref):
        return '{"password":"PRIVATE-FIXTURE-SECRET"}'

    monkeypatch.setattr(bridge, "protect_secret_directory", unprotectable)
    client = RSVDataBridgeClient(executable=str(executable), config_root=str(tmp_path),
                                config_secret_loader=loader, config_secret_ref="synthetic")
    with pytest.raises(RSVBridgeUnavailable, match="could not be protected") as failure:
        await client.health(_source())
    assert "PRIVATE-FIXTURE-SECRET" not in str(failure.value) and failure.value.__cause__ is None
    assert paths and all(not path.exists() for path in paths)


def test_cleanup_os_error_is_sanitized():
    class FailedCleanup:
        def cleanup(self):
            raise OSError("PRIVATE-FIXTURE-PATH")

    with pytest.raises(RSVBridgeUnavailable) as failure:
        RSVDataBridgeClient._cleanup_temporary(FailedCleanup())
    assert "PRIVATE-FIXTURE-PATH" not in str(failure.value) and failure.value.__cause__ is None


@pytest.mark.asyncio
async def test_parallel_non_rsv_context_diagnostics_are_not_suppressed(caplog):
    logger = logging.getLogger("mcp.client.session")
    private_started, public_finished = asyncio.Event(), asyncio.Event()

    async def private_task():
        with private_rsv_diagnostics():
            private_started.set()
            await public_finished.wait()
            logger.warning("PRIVATE-CONCURRENT-SECRET")

    async def public_task():
        await private_started.wait()
        logger.warning("public parallel event", extra={"public_extra": "retained"})
        public_finished.set()

    with caplog.at_level(logging.WARNING):
        await asyncio.gather(private_task(), public_task())
    assert "PRIVATE-CONCURRENT-SECRET" not in caplog.text
    assert "public parallel event" in caplog.text
    assert next(item for item in caplog.records if item.msg == "public parallel event").public_extra == "retained"
