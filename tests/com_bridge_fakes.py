"""Fake COM layer for the bridge tests. Nothing here touches COM, pywin32 or a real 1C."""
from __future__ import annotations

import json
import threading
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from onec_com_bridge.config import BridgeConfig

TOKEN = "t" * 40
COMPANY = "11111111-1111-1111-1111-111111111111"
OTHER_COMPANY = "22222222-2222-2222-2222-222222222222"
ACCOUNT_A = "aaaaaaaa-0000-0000-0000-000000000001"
ACCOUNT_B = "aaaaaaaa-0000-0000-0000-000000000002"
CP_REF = "cccccccc-0000-0000-0000-000000000001"
CONTRACT_REF = "cccccccc-0000-0000-0000-000000000002"
CURRENCY = "dddddddd-0000-0000-0000-000000000001"
FINGERPRINT = "ab" * 32
EMPTY = object()


class FakeRef:
    def __init__(self, guid: str, full_name: str = "Справочник.Контрагенты", filled: bool = True):
        self.guid = guid
        self.full_name = full_name
        self.filled = filled

    def Metadata(self) -> Any:
        return SimpleNamespace(FullName=lambda: self.full_name)


class FakeSelection:
    def __init__(self, rows: list[SimpleNamespace]):
        self._rows = rows
        self._index = -1

    def Next(self) -> bool:
        self._index += 1
        return self._index < len(self._rows)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._rows[self._index], name)


def make_row(account: str = ACCOUNT_A, subs=None, debit: Any = Decimal("10.50"), credit: Any = 0,
             currency: str | None = None, kinds=None) -> SimpleNamespace:
    subs = subs if subs is not None else [CP_REF, None, None]
    kinds = kinds or ["Справочник.Контрагенты", None, None]
    refs = [FakeRef(g, k) if g is not None else None for g, k in zip(subs, kinds, strict=True)]
    return SimpleNamespace(Счет=FakeRef(account, "ПланСчетов.Хозрасчетный"), Субконто1=refs[0], Субконто2=refs[1], Субконто3=refs[2], Валюта=FakeRef(currency, "Справочник.Валюты") if currency else FakeRef(CURRENCY, "Справочник.Валюты", False), Дт=debit, Кт=credit)


class FakeQuery:
    def __init__(self, conn: FakeConn):
        self._conn = conn
        self.Text = ""
        self.params: dict[str, Any] = {}

    def SetParameter(self, name: str, value: Any) -> None:
        self.params[name] = value

    def Execute(self) -> Any:
        self._conn.executed.append((self.Text, dict(self.params)))
        if self._conn.block is not None:
            self._conn.block.wait(10)
        rows = list(self._conn.rows)
        return SimpleNamespace(Select=lambda: FakeSelection(rows))


class FakeConn:
    def __init__(self, rows: list[SimpleNamespace], user: str, block: threading.Event | None = None):
        self.rows = rows
        self.user = user
        self.block = block
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.new_objects: list[str] = []

    def UserName(self) -> str:
        return self.user

    def NewObject(self, name: str, *args: Any) -> Any:
        self.new_objects.append(name)
        if name == "Query":
            return FakeQuery(self)
        if name == "Array":
            return _Array()
        if name == "TypeDescription":  # the live connector has no Type(); this is the route that works
            type_name = args[0]
            return SimpleNamespace(Types=lambda: SimpleNamespace(Get=lambda _index: type_name))
        raise AssertionError(f"unexpected NewObject {name}")

    def XMLValue(self, type_name: str, text: str) -> FakeRef:
        return FakeRef(text, type_name)

    def XMLString(self, ref: FakeRef) -> str:
        return ref.guid

    def ValueIsFilled(self, ref: FakeRef) -> bool:
        return ref.filled


class _Array(list):
    def Add(self, item: Any) -> None:
        self.append(item)


class FakeRuntime:
    def __init__(self, rows=None, fail_connect: bool = False, block: threading.Event | None = None,
                 user: str = "reader_user"):
        self.rows = rows if rows is not None else [make_row()]
        self.fail_connect = fail_connect
        self.block = block
        self.user = user
        self.connects: list[dict[str, str]] = []
        self.conns: list[FakeConn] = []

    def thread_init(self) -> None:
        pass

    def connect(self, *, base_path: str, user: str, password: str) -> FakeConn:
        self.connects.append({"base_path": base_path, "user": user})
        if self.fail_connect:
            raise OSError(f"cannot open {base_path} with password {password}")
        conn = FakeConn(self.rows, self.user, self.block)
        self.conns.append(conn)
        return conn


def binding_dict(**over: Any) -> dict[str, Any]:
    base = {
        "binding_id": "bind-1", "version": 3, "source_id": "src-1",
        "base_path": "C:\\clones\\clone_a", "reader_user": "reader_user",
        "reader_secret_file": "C:\\secrets\\reader.dpapi", "allowed_company_refs": [COMPANY],
        "clone_identity": "clone-a", "metadata_fingerprint": FINGERPRINT,
    }
    base.update(over)
    return base


def config_dict(**over: Any) -> dict[str, Any]:
    base = {"listen_host": "127.0.0.1", "listen_port": 8765, "token_file": "C:\\secrets\\token.txt",
            "call_timeout_seconds": 5, "bindings": [binding_dict()]}
    base.update(over)
    return base


def make_config(**over: Any) -> BridgeConfig:
    return BridgeConfig.model_validate(json.loads(json.dumps(config_dict(**over))))


def good_request(**over: Any) -> dict[str, Any]:
    body = {
        "binding_id": "bind-1", "binding_version": 3, "source_id": "src-1",
        "as_of": "2026-08-31T23:59:59+03:00", "company_external_ref": COMPANY,
        "account_keys": [ACCOUNT_A, ACCOUNT_B], "max_rows": 100,
    }
    body.update(over)
    return body
