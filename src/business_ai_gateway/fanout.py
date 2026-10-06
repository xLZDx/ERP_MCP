from __future__ import annotations

import asyncio
import json
import time
import weakref
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar
from uuid import UUID

TAuthorized = TypeVar("TAuthorized")


class FanoutPolicyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class FanoutExecutor:
    """Bounded company-scoped fan-out. Callers provide registry-backed authorization."""

    def __init__(
        self,
        *,
        max_sources: int = 16,
        global_concurrency: int = 20,
        per_source_concurrency: int = 2,
        deadline_seconds: float = 15.0,
        per_source_timeout_seconds: float = 10.0,
        max_rows_per_source: int = 200,
        max_bytes_per_source: int = 5_000_000,
    ):
        if min(max_sources, global_concurrency, per_source_concurrency, max_rows_per_source) < 1:
            raise ValueError("fan-out counts must be positive")
        if min(deadline_seconds, per_source_timeout_seconds, max_bytes_per_source) <= 0:
            raise ValueError("fan-out deadlines and byte limits must be positive")
        self.max_sources = max_sources
        self.global_concurrency = asyncio.Semaphore(global_concurrency)
        self._global_limit = global_concurrency
        self.per_source_concurrency = per_source_concurrency
        self.deadline_seconds = deadline_seconds
        self.per_source_timeout_seconds = per_source_timeout_seconds
        self.max_rows_per_source = max_rows_per_source
        self.max_bytes_per_source = max_bytes_per_source
        self._source_limits: weakref.WeakValueDictionary[str, asyncio.Semaphore] = (
            weakref.WeakValueDictionary()
        )

    def _source_limit(self, source_id: str) -> asyncio.Semaphore:
        semaphore = self._source_limits.get(source_id)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.per_source_concurrency)
            self._source_limits[source_id] = semaphore
        return semaphore

    async def run(
        self,
        targets: Sequence[tuple[str, UUID]],
        *,
        authorize: Callable[[str, UUID], Awaitable[TAuthorized]],
        fetch: Callable[[TAuthorized], Awaitable[Any]],
    ) -> dict[str, Any]:
        """Authorize every target before dispatch; return stable, explicit partial outcomes."""
        if len(targets) > self.max_sources:
            raise FanoutPolicyError(
                "FANOUT_LIMIT_EXCEEDED", f"at most {self.max_sources} sources may be queried"
            )
        source_ids = [source_id for source_id, _ in targets]
        if len(set(source_ids)) != len(source_ids):
            raise FanoutPolicyError("DUPLICATE_SOURCE", "fan-out source IDs must be unique")

        started = time.monotonic()
        outcomes: dict[str, dict[str, Any]] = {}
        authorized: dict[str, TAuthorized] = {}

        async def resolve(source_id: str, company_id: UUID):
            async with self.global_concurrency:
                try:
                    authorized[source_id] = await authorize(source_id, company_id)
                except PermissionError:
                    outcomes[source_id] = self._failure(source_id, company_id, "ACCESS_DENIED")
                except Exception:  # noqa: BLE001 - no auth/provider details enter the envelope
                    outcomes[source_id] = self._failure(
                        source_id, company_id, "AUTHORIZATION_UNAVAILABLE"
                    )

        try:
            async with asyncio.timeout(self.deadline_seconds):
                # No data adapter is invoked until authorization has resolved for every target.
                await asyncio.gather(*(resolve(source, company) for source, company in targets))

                async def dispatch(source_id: str, company_id: UUID):
                    authorized_source = authorized.get(source_id)
                    if authorized_source is None:
                        return
                    try:
                        async with (
                            self.global_concurrency,
                            self._source_limit(source_id),
                            asyncio.timeout(self.per_source_timeout_seconds),
                        ):
                            payload = await fetch(authorized_source)
                        outcomes[source_id] = self._success(source_id, company_id, payload)
                    except TimeoutError:
                        outcomes[source_id] = self._failure(source_id, company_id, "SOURCE_TIMEOUT")
                    except Exception:  # noqa: BLE001 - stable generic source error; never echo details
                        outcomes[source_id] = self._failure(source_id, company_id, "SOURCE_ERROR")

                await asyncio.gather(*(dispatch(source, company) for source, company in targets))
        except TimeoutError:
            # gather cancellation propagates to active adapter calls; every omitted result is explicit.
            for source_id, company_id in targets:
                outcomes.setdefault(
                    source_id, self._failure(source_id, company_id, "DEADLINE_EXCEEDED")
                )

        ordered = [outcomes[source_id] for source_id in source_ids]
        successes = [item for item in ordered if item["outcome"] == "SUCCESS"]
        failures = [item for item in ordered if item["outcome"] != "SUCCESS"]
        return {
            "complete": not failures and len(successes) == len(targets),
            "requested_sources": len(targets),
            "successful_sources": len(successes),
            "failed_sources": len(failures),
            "rows_returned": sum(item["rows_returned"] for item in successes),
            "bytes_returned": sum(item["bytes_returned"] for item in successes),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "results": ordered,
            "failures": [
                {"source_id": item["source_id"], "error_code": item["error_code"]}
                for item in failures
            ],
            "limits": {
                "max_sources": self.max_sources,
                "global_concurrency": self._global_limit,
                "per_source_concurrency": self.per_source_concurrency,
                "max_rows_per_source": self.max_rows_per_source,
                "max_bytes_per_source": self.max_bytes_per_source,
            },
        }

    def _failure(self, source_id: str, company_id: UUID, code: str) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "company_id": str(company_id),
            "outcome": "ERROR",
            "error_code": code,
            "rows_returned": 0,
            "bytes_returned": 0,
            "truncated": False,
        }

    def _success(self, source_id: str, company_id: UUID, payload: Any) -> dict[str, Any]:
        rows_key = None
        rows = None
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict) and isinstance(payload.get("value"), list):
            rows_key = "value"
            rows = payload[rows_key]

        truncated = rows is not None and len(rows) > self.max_rows_per_source
        rows_returned = min(len(rows), self.max_rows_per_source) if rows is not None else 0
        if truncated:
            bounded_rows = rows[: self.max_rows_per_source]
            payload = bounded_rows if rows_key is None else {**payload, rows_key: bounded_rows}
        try:
            encoded = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError):
            return self._failure(source_id, company_id, "MALFORMED_RESPONSE")
        if len(encoded) > self.max_bytes_per_source:
            return self._failure(source_id, company_id, "SOURCE_RESPONSE_TOO_LARGE")
        return {
            "source_id": source_id,
            "company_id": str(company_id),
            "outcome": "SUCCESS",
            "data": payload,
            "rows_returned": rows_returned,
            "bytes_returned": len(encoded),
            "truncated": truncated,
        }
