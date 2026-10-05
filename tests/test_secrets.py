import pytest

from business_ai_gateway.secrets import FileSecrets


@pytest.mark.asyncio
async def test_file_secret_provider_blocks_path_escape(tmp_path):
    provider = FileSecrets(str(tmp_path))
    (tmp_path / "user").write_text("alice", encoding="utf-8")
    assert await provider.get("user") == "alice"
    with pytest.raises(ValueError):
        await provider.get("../etc/passwd")
