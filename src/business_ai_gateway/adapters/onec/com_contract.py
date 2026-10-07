"""Shared contract between the gateway and the local COM bridge (ADR-0008).

The bridge is a separate loopback process. The gateway only ever sends structured, validated parameters and never
query text, a path, a secret reference or a user name. Wire format of ``POST /v1/balance_by_analytics``:

request  {"binding_id": str, "binding_version": int, "source_id": str, "as_of": ISO-8601 with offset,
          "company_external_ref": str, "account_keys": [guid, ...] (1..16), "max_rows": int (1..5000)}
response {"binding_id": str, "binding_version": int, "source_id": str,
          "base_identity": {"clone_identity": str, "metadata_fingerprint": 64 hex},
          "rows": [{"account_key": guid,
                    "analytics": [{"ref": guid | null, "type": "Catalog.<Name>" | null}] * 3,
                    "debit": decimal string, "credit": decimal string, "currency_ref": guid | null}],
          "truncated": bool}
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

COM_MAX_ACCOUNTS = 16
COM_MAX_ROWS = 5000
ANALYTICS_SLOTS = 3


class ComBridgeError(RuntimeError):
    """Sanitized bridge failure; ``code`` is a stable machine code and never carries bridge or 1C text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ComBalanceRequest:
    binding_id: str
    binding_version: int
    source_id: str
    as_of: datetime
    company_external_ref: str
    account_keys: tuple[str, ...]
    max_rows: int


@dataclass(frozen=True, slots=True)
class ComBalanceResponse:
    binding_id: str
    binding_version: int
    source_id: str
    clone_identity: str
    metadata_fingerprint: str
    rows: tuple[dict, ...]
    truncated: bool


class ComBalanceClient(Protocol):
    async def balance_by_analytics(self, request: ComBalanceRequest) -> ComBalanceResponse: ...
