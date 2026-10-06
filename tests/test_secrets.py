import pytest

from business_ai_gateway.secrets import FileSecrets


@pytest.mark.asyncio
async def test_file_secret_provider_blocks_path_escape(tmp_path):
    provider = FileSecrets(str(tmp_path))
    (tmp_path / "user").write_text("alice", encoding="utf-8")
    assert await provider.get("user") == "alice"
    with pytest.raises(ValueError):
        await provider.get("../etc/passwd")


@pytest.mark.asyncio
async def test_file_secret_provider_observes_rotation_and_revocation_without_restart(tmp_path):
    provider = FileSecrets(str(tmp_path))
    secret_path = tmp_path / "onec-password"
    secret_path.write_text("synthetic-old-value", encoding="utf-8")

    assert await provider.get("onec-password") == "synthetic-old-value"

    replacement = tmp_path / "onec-password.next"
    replacement.write_text("synthetic-new-value", encoding="utf-8")
    replacement.replace(secret_path)
    assert await provider.get("onec-password") == "synthetic-new-value"

    secret_path.unlink()
    with pytest.raises(FileNotFoundError):
        await provider.get("onec-password")
