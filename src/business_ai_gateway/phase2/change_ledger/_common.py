"""Shared small types for the change ledger package (no dependencies)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_CODE = re.compile(r"[A-Z][A-Z0-9_]+")


@dataclass(frozen=True)
class Scope:
    """The (tenant, company) pair every ledger call is scoped to."""

    tenant_id: str
    company_id: str

    def __post_init__(self) -> None:
        for v in (self.tenant_id, self.company_id):
            if not isinstance(v, str) or not v:
                raise ValueError("SCOPE_INVALID")


class LedgerError(Exception):
    """A ledger refusal. ``code`` is the fixed code raised by the SQL function (contract section 10)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def code_from_message(message: str, sqlstate: str | None = None) -> str:
    head = (message.splitlines() or [""])[0].split(":")[0].strip()
    if _CODE.fullmatch(head):
        return head
    return "PERMISSION_DENIED" if sqlstate == "42501" else "SQL_" + str(sqlstate)
