from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol

from .settings import Settings


class SecretProvider(Protocol):
    async def get(self, ref: str) -> str: ...


class EnvSecrets:
    async def get(self, ref: str) -> str:
        value = os.getenv(ref)
        if value is None:
            raise RuntimeError(f"missing environment secret: {ref}")
        return value


class FileSecrets:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    async def get(self, ref: str) -> str:
        if "/" in ref or "\\" in ref or ref in {"", ".", ".."}:
            raise ValueError("secret file ref must be a basename")
        path = (self.root / ref).resolve()
        if path.parent != self.root:
            raise ValueError("secret ref escaped secret root")
        return (await asyncio.to_thread(path.read_text, encoding="utf-8")).strip()


class GCPSecrets:
    def __init__(self, project_id: str):
        try:
            from google.cloud import secretmanager
        except ImportError as exc:
            raise RuntimeError('GCP provider requires pip install -e ".[gcp]"') from exc
        self.project_id = project_id
        self.client = secretmanager.SecretManagerServiceAsyncClient()

    async def get(self, ref: str) -> str:
        name = ref if "/" in ref else f"projects/{self.project_id}/secrets/{ref}/versions/latest"
        response = await self.client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")


def build_secret_provider(settings: Settings) -> SecretProvider:
    if settings.secret_provider == "env":
        return EnvSecrets()
    if settings.secret_provider == "file":
        return FileSecrets(settings.secret_file_root)
    if settings.secret_provider == "gcp":
        assert settings.gcp_project_id
        return GCPSecrets(settings.gcp_project_id)
    raise ValueError(f"unsupported secret provider: {settings.secret_provider}")
