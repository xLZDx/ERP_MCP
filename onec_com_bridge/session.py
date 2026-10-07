"""One connection per binding: lazy, reader-only, serialised by a lock, executed in a dedicated worker thread with a
per-call timeout. A timeout or connection fault marks the connection unhealthy and abandons the worker.

A call that timed out may still be running inside 1C: while it is, the binding is poisoned and answers
``COM_UNAVAILABLE`` at once, so a retry loop can never open a second 1C session (one licence) for the same binding. At
most ``MAX_INFLIGHT`` requests per binding are admitted (one running, one waiting), so a slow binding cannot occupy the
shared thread pool and starve the others."""
from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any

from .config import BindingConfig
from .errors import COM_INTERNAL, COM_TIMEOUT, COM_UNAVAILABLE, BridgeFault
from .query import AnalyticsBalanceQuery
from .runtime import ComRuntime

log = logging.getLogger("onec_com_bridge")

MAX_INFLIGHT = 2
MAX_LOCK_WAIT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class BalanceJob:
    as_of: dt.datetime
    company_ref: str
    account_keys: tuple[str, ...]
    max_rows: int


class _Worker:
    """A single COM thread and the connection that belongs to it."""

    def __init__(self, runtime: ComRuntime):
        self.conn: Any = None
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="com-bridge", initializer=runtime.thread_init
        )

    def abandon(self) -> None:
        self.conn = None
        self.executor.shutdown(wait=False, cancel_futures=True)


class BindingSession:
    def __init__(
        self,
        binding: BindingConfig,
        runtime: ComRuntime,
        secret_loader: Callable[[str], str],
        timeout_seconds: float,
        query: AnalyticsBalanceQuery | None = None,
    ):
        self._binding = binding
        self._runtime = runtime
        self._secret_loader = secret_loader
        self._timeout = timeout_seconds
        self._query = query or AnalyticsBalanceQuery()
        self._lock = threading.Lock()
        self._admission = threading.Semaphore(MAX_INFLIGHT)
        self._worker: _Worker | None = None
        self._abandoned: Future | None = None

    def fetch(self, job: BalanceJob) -> tuple[list[dict[str, Any]], bool]:
        if not self._admission.acquire(blocking=False):
            raise BridgeFault(COM_UNAVAILABLE)  # fail fast: never queue behind a slow binding
        try:
            return self._fetch_admitted(job)
        finally:
            self._admission.release()

    def _fetch_admitted(self, job: BalanceJob) -> tuple[list[dict[str, Any]], bool]:
        if not self._lock.acquire(timeout=min(self._timeout, MAX_LOCK_WAIT_SECONDS)):
            raise BridgeFault(COM_TIMEOUT)
        try:
            if self._abandoned is not None:
                if not self._abandoned.done():
                    raise BridgeFault(COM_UNAVAILABLE)  # the timed-out query still holds the old 1C session
                self._abandoned = None
            if self._worker is None:
                self._worker = _Worker(self._runtime)
            worker = self._worker
            future = worker.executor.submit(self._work, worker, job)
            try:
                return future.result(timeout=self._timeout)
            except FutureTimeout:
                self._abandoned = future
                self._drop(worker)
                raise BridgeFault(COM_TIMEOUT) from None
            except BridgeFault as fault:
                if fault.code == COM_UNAVAILABLE:
                    self._drop(worker)
                raise
            except Exception as exc:  # noqa: BLE001 - never expose COM/1C text; log the type only
                log.error("binding=%s com call failed (%s)", self._binding.binding_id, type(exc).__name__)
                self._drop(worker)
                raise BridgeFault(COM_INTERNAL) from None
        finally:
            self._lock.release()

    def _drop(self, worker: _Worker) -> None:
        worker.abandon()
        if self._worker is worker:
            self._worker = None

    def _work(self, worker: _Worker, job: BalanceJob) -> tuple[list[dict[str, Any]], bool]:
        if worker.conn is None:
            worker.conn = self._connect()
        return self._query.run(
            worker.conn,
            as_of=job.as_of,
            company_ref=job.company_ref,
            account_keys=job.account_keys,
            max_rows=job.max_rows,
        )

    def _connect(self) -> Any:
        binding = self._binding
        try:
            password = self._secret_loader(binding.reader_secret_file)
            conn = self._runtime.connect(
                base_path=binding.base_path, user=binding.reader_user, password=password
            )
            # the connection must be the reader and nobody else
            if str(conn.UserName()) != binding.reader_user:
                raise PermissionError
        except Exception as exc:  # noqa: BLE001 - connect errors can echo the connection string
            log.error("binding=%s cannot open the base (%s)", binding.binding_id, type(exc).__name__)
            raise BridgeFault(COM_UNAVAILABLE) from None
        return conn
