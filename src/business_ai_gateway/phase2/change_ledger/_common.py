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
    """A ledger refusal. ``code`` is the fixed code raised by the SQL function (contract section 10);
    ``sqlstate`` is the PostgreSQL SQLSTATE it travelled with (``P0001`` for every RAISE EXCEPTION)."""

    def __init__(self, code: str, sqlstate: str | None = None):
        super().__init__(code)
        self.code = code
        self.sqlstate = sqlstate


def code_from_message(message: str, sqlstate: str | None = None) -> str:
    """The contract code of a SQL error: the RAISE EXCEPTION text when it is an UPPER_SNAKE code
    (``CODE`` or ``CODE: detail``); a privilege error (42501, a caller class that was not granted the
    function) is NOT_ENTITLED; other errors keep their SQLSTATE as ``SQL_<state>`` and never leak text.
    A raw 55P03 is not enough to identify the S13 fence timeout because PostgreSQL also uses it for
    other lock-not-available conditions. The dedicated fence helper must raise its explicit contract
    code instead."""
    head = (message.splitlines() or [""])[0].split(":")[0].strip()
    if _CODE.fullmatch(head):
        return head
    return "NOT_ENTITLED" if sqlstate == "42501" else "SQL_" + str(sqlstate)
