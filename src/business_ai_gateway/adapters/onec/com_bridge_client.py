"""Gateway-side client for the local COM bridge (ADR-0008). Loopback only, bearer token, bounded and strictly
validated responses, no redirects, no environment proxies. Failures surface as ``ComBridgeError`` stable codes."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from .com_contract import (
    ANALYTICS_SLOTS,
    ComBalanceRequest,
    ComBalanceResponse,
    ComBridgeError,
)

COM_UNAVAILABLE = "COM_UNAVAILABLE"
COM_TIMEOUT = "COM_TIMEOUT"
COM_BINDING_MISMATCH = "COM_BINDING_MISMATCH"
COM_COMPANY_DENIED = "COM_COMPANY_DENIED"
COM_BAD_REQUEST = "COM_BAD_REQUEST"
COM_UNAUTHORIZED = "COM_UNAUTHORIZED"
COM_INTERNAL = "COM_INTERNAL"
COM_CODES = frozenset(
    {
        COM_UNAVAILABLE,
        COM_TIMEOUT,
        COM_BINDING_MISMATCH,
        COM_COMPANY_DENIED,
        COM_BAD_REQUEST,
        COM_UNAUTHORIZED,
        COM_INTERNAL,
    }
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_TYPE = re.compile(r"^(Catalog|Document|ChartOfAccounts|ChartOfCharacteristicTypes|Enum)\.\w+$")


def _invalid() -> ComBridgeError:
    return ComBridgeError(COM_INTERNAL)


class ComBridgeClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: float,
        max_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("COM bridge URL must be a loopback http(s) URL")
        self.max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            transport=transport,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def balance_by_analytics(self, request: ComBalanceRequest) -> ComBalanceResponse:
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise ComBridgeError(COM_BAD_REQUEST)
        payload = {
            "binding_id": request.binding_id,
            "binding_version": request.binding_version,
            "source_id": request.source_id,
            "as_of": request.as_of.isoformat(),
            "company_external_ref": request.company_external_ref,
            "account_keys": list(request.account_keys),
            "max_rows": request.max_rows,
        }
        envelope = await self._post("v1/balance_by_analytics", payload)
        return self._parse(request, envelope)

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        body = bytearray()
        try:
            async with self._client.stream("POST", endpoint, json=payload) as response:
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self.max_response_bytes:
                    raise _invalid()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        raise _invalid()
                status = response.status_code
        except httpx.TimeoutException:
            raise ComBridgeError(COM_TIMEOUT) from None
        except httpx.HTTPError:
            raise ComBridgeError(COM_UNAVAILABLE) from None
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if status != 200:
            code = None
            if isinstance(data, dict) and isinstance(data.get("error"), dict):
                code = data["error"].get("code")
            if status == 401:
                raise ComBridgeError(COM_UNAUTHORIZED)
            if isinstance(code, str) and code in COM_CODES:
                raise ComBridgeError(code)
            raise ComBridgeError(COM_UNAVAILABLE if status >= 500 else COM_INTERNAL)
        if data is None:
            raise _invalid()
        return data

    @staticmethod
    def _parse(request: ComBalanceRequest, envelope: Any) -> ComBalanceResponse:
        if not isinstance(envelope, dict):
            raise _invalid()
        version = envelope.get("binding_version")
        if (
            envelope.get("binding_id") != request.binding_id
            or isinstance(version, bool)
            or version != request.binding_version
            or envelope.get("source_id") != request.source_id
        ):
            raise ComBridgeError(COM_BINDING_MISMATCH)
        identity = envelope.get("base_identity")
        if not isinstance(identity, dict):
            raise _invalid()
        clone = identity.get("clone_identity")
        fingerprint = identity.get("metadata_fingerprint")
        if (
            not isinstance(clone, str)
            or not clone
            or not isinstance(fingerprint, str)
            or not _FINGERPRINT.match(fingerprint)
        ):
            raise _invalid()
        rows = envelope.get("rows")
        truncated = envelope.get("truncated")
        if not isinstance(rows, list) or not isinstance(truncated, bool) or len(rows) > request.max_rows:
            raise _invalid()
        requested = set(request.account_keys)
        clean = tuple(ComBridgeClient._row(row, requested, request.company_external_ref) for row in rows)
        return ComBalanceResponse(
            binding_id=request.binding_id,
            binding_version=request.binding_version,
            source_id=request.source_id,
            clone_identity=clone,
            metadata_fingerprint=fingerprint,
            rows=clean,
            truncated=truncated,
        )

    @staticmethod
    def _row(row: Any, requested: set[str], company: str) -> dict[str, Any]:
        if not isinstance(row, dict) or set(row) != {
            "account_key",
            "company_ref",
            "analytics",
            "debit",
            "credit",
            "currency_ref",
        }:
            raise _invalid()
        account = row["account_key"]
        analytics = row["analytics"]
        currency = row["currency_ref"]
        if (
            not isinstance(account, str)
            or account not in requested
            or not isinstance(row["company_ref"], str)
            or row["company_ref"].lower() != company.lower()
            or not isinstance(analytics, list)
            or len(analytics) != ANALYTICS_SLOTS
            or not all(isinstance(row[k], str) and _DECIMAL.match(row[k]) for k in ("debit", "credit"))
            or not (currency is None or (isinstance(currency, str) and _GUID.match(currency)))
        ):
            raise _invalid()
        slots = []
        for slot in analytics:
            if not isinstance(slot, dict) or set(slot) != {"ref", "type"}:
                raise _invalid()
            ref, kind = slot["ref"], slot["type"]
            if ref is None and kind is None:
                slots.append({"ref": None, "type": None})
            elif (
                isinstance(ref, str)
                and _GUID.match(ref)
                and isinstance(kind, str)
                and _TYPE.match(kind)
            ):
                slots.append({"ref": ref, "type": kind})
            else:
                raise _invalid()
        return {
            "account_key": account,
            "company_ref": row["company_ref"].lower(),
            "analytics": slots,
            "debit": row["debit"],
            "credit": row["credit"],
            "currency_ref": currency,
        }
