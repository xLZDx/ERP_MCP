"""Phase 2 evaluation runner (R2-US-029, TC085-087). Unwired from Release 1.

Runs the numeric native-vs-gateway comparison ONLY behind three checks, in this order, each with one
fixed code and no caller input echoed:

1. input shape (``INVALID_INPUT``; wrong types never raise),
2. the runner id is registered for the (tenant, source) scope (``RUNNER_NOT_REGISTERED``; the default
   registry is empty, so everything is denied),
3. both statements carry the request scope (``SCOPE_MISMATCH``). This runs BEFORE the permit check so a
   malformed request can never burn a permit use,
4. the capture permit admits the request (``PERMIT_DENIED``: one code for every permit denial, so a
   caller learns nothing about why).

Only after all four does the comparator run. The permit mode used is ``CaptureMode.READ_SNAPSHOT``.
DECISION: READ_SNAPSHOT is the accepted permit mode for evaluation, because ``capture_permit`` has no
EVALUATION_ONLY member and is deliberately not extended. A permit use is consumed only by a successful admit, i.e. only after the
runner and scope checks passed.

The result is always ``mode == "EVALUATION_ONLY"`` and ``promotable`` is always False (a read-only
property): nothing here can produce an acceptance or attestation. There is no public function that
compares without the checks; a custom comparator is trusted wiring supplied ONLY as the constructor
argument ``compare``. ``run`` takes no comparator, so a caller of ``run`` cannot inject a result
(``__all__`` is audited by the tests). The ``promotable`` flag only means: runner output is labelled
non-promotable; it is not an enforcement of anything downstream.

``result_digest`` is sha256 over canonical JSON of the scope, params digest, both statements and the
comparison. Decimals are normalised (``1.0`` == ``1.00``), rows are sorted by their analytic key (the
statement model forbids duplicate keys and the comparator treats rows as a keyed set, so row order is
not significant) and datetimes are rendered in UTC.

KNOWN GAPS: ``params_digest`` is caller-asserted: it is matched against the permit but never verified
against the data actually evaluated, so the permit does not constrain WHICH data (statements) are
evaluated, only who may run which scope with which asserted params. The evaluation ``result_digest`` is
not bound to any attestation (``evidence_attestation`` binds a revision digest, not this digest); that
binding is a wiring item for a later gate. The runner registry and permit store are process-local; ``runner_id`` is asserted by the
caller, not authenticated.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Context, Decimal, Inexact
from enum import StrEnum

from ._identity import clean_identity
from .capture_permit import CaptureMode, PermitStore
from .reconciliation import (
    BalanceSix,
    Comparison,
    LedgerStatement,
    TolerancePolicy,
    compare_statements,
)

__all__ = ["EvaluationRequest", "EvaluationResult", "EvaluationRunner", "EvaluationStatus"]

EVALUATION_MODE = "EVALUATION_ONLY"
_PERMIT_MODE = CaptureMode.READ_SNAPSHOT
_NORM = Context(prec=60, Emin=-999_999, Emax=999_999)
_NORM.traps[Inexact] = True
_DEFAULT_POLICY = TolerancePolicy("EXACT_ZERO", Decimal(0))


class EvaluationStatus(StrEnum):
    COMPUTED = "COMPUTED"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    permit_id: str
    tenant_id: str
    source_id: str
    runner_id: str
    params_digest: str
    requester: str
    native: LedgerStatement
    gateway: LedgerStatement


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    status: EvaluationStatus
    code: str
    comparison: Comparison | None = None
    mode: str = EVALUATION_MODE
    result_digest: str | None = None

    @property
    def promotable(self) -> bool:
        return False


def _denied(code: str) -> EvaluationResult:
    return EvaluationResult(EvaluationStatus.DENIED, code)


def _dec(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    # scientific str() of the normalised value: 1.0 == 1.00 == "1" and no huge "f" expansion for 1E+999999
    try:
        return str(value.normalize(_NORM))
    except ArithmeticError:
        return str(value)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _six(balance: BalanceSix) -> list[list[str | None]]:
    return [[name, _dec(val)] for name, val in balance.items()]


def _statement(st: LedgerStatement) -> dict[str, object]:
    sc = st.scope
    rows = sorted(st.rows, key=lambda r: (r.counterparty_ref, r.contract_ref))
    return {
        "scope": [sc.tenant_id, sc.source_id, sc.company_id, sc.account, _utc(sc.start_inclusive),
                  _utc(sc.end_exclusive), sc.currency_code, sc.timezone_name, list(sc.grouping)],
        "snapshot_ref": st.snapshot_ref,
        "report_revision": st.report_revision,
        "complete": st.complete,
        "totals": _six(st.totals),
        "rows": [[r.counterparty_ref, r.contract_ref, _six(r.balance)] for r in rows],
    }


def _digest(tenant: str, source: str, params_digest: str, request: EvaluationRequest,
            comparison: Comparison) -> str:
    diffs = sorted(
        ([list(d.row_key) if d.row_key is not None else None, d.measure, _dec(d.expected),
          _dec(d.actual)] for d in comparison.differences),
        key=lambda item: json.dumps(item, ensure_ascii=True),
    )
    payload = {
        "scope": [tenant, source],
        "params_digest": params_digest,
        "native": _statement(request.native),
        "gateway": _statement(request.gateway),
        "comparison": [str(comparison.state), comparison.reason_code, comparison.policy_id, diffs],
    }
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _shape_ok(request: object) -> bool:
    if type(request) is not EvaluationRequest:
        return False
    try:
        texts = (request.permit_id, request.tenant_id, request.source_id, request.runner_id,
                 request.params_digest, request.requester)
        return (all(type(t) is str for t in texts)
                and type(request.native) is LedgerStatement
                and type(request.gateway) is LedgerStatement)
    except Exception:  # noqa: BLE001 - e.g. an instance built without __init__: unset slots
        return False


def _in_scope(st: LedgerStatement, tenant: str, source: str) -> bool:
    return (clean_identity(st.scope.tenant_id) == tenant
            and clean_identity(st.scope.source_id) == source)


class EvaluationRunner:
    def __init__(
        self,
        permits: PermitStore,
        runners: Mapping[tuple[str, str], frozenset[str]] | None = None,
        *,
        policy: TolerancePolicy = _DEFAULT_POLICY,
        compare: Callable[[LedgerStatement, LedgerStatement], Comparison] | None = None,
    ) -> None:
        if type(permits) is not PermitStore:
            raise TypeError("permits must be a PermitStore")
        if type(policy) is not TolerancePolicy:
            raise TypeError("policy must be a TolerancePolicy")
        if compare is not None and not callable(compare):
            raise TypeError("compare must be callable")
        registry: dict[tuple[str, str], frozenset[str]] = {}
        for scope, ids in (runners or {}).items():
            if type(ids) not in (set, frozenset, list, tuple) or any(type(x) is not str for x in ids):
                raise ValueError("runners values must be a set/frozenset/list/tuple of str ids")
            if type(scope) is not tuple or len(scope) != 2:
                raise ValueError("runners keys must be valid (tenant, source) pairs")
            tenant, source = (clean_identity(part) for part in scope)
            if not tenant or not source:
                raise ValueError("runners keys must be valid (tenant, source) pairs")
            clean = frozenset(i for i in (clean_identity(x) for x in ids) if i)
            registry[(tenant, source)] = registry.get((tenant, source), frozenset()) | clean
        self._permits = permits
        self._runners = registry
        self._policy = policy
        self._compare = compare if compare is not None else self._default_compare

    def _default_compare(self, native: LedgerStatement, gateway: LedgerStatement) -> Comparison:
        return compare_statements(native, gateway, policy=self._policy)

    def run(self, request: EvaluationRequest) -> EvaluationResult:
        """Checks first, compute last; never raises, never echoes input, never promotable."""
        if not _shape_ok(request):
            return _denied("INVALID_INPUT")
        tenant = clean_identity(request.tenant_id)
        source = clean_identity(request.source_id)
        runner = clean_identity(request.runner_id)
        if not tenant or not source or not runner:
            return _denied("INVALID_INPUT")
        if runner not in self._runners.get((tenant, source), frozenset()):
            return _denied("RUNNER_NOT_REGISTERED")
        try:
            scoped = (_in_scope(request.native, tenant, source)
                      and _in_scope(request.gateway, tenant, source))
        except Exception:  # noqa: BLE001 - hostile statement subclass/attrs: fail closed
            scoped = False
        if not scoped:
            return _denied("SCOPE_MISMATCH")
        try:
            admitted = self._permits.admit(request.permit_id, tenant, source, _PERMIT_MODE,
                                           request.params_digest, request.requester)
            permitted = admitted.allowed is True
        except Exception:  # noqa: BLE001 - fail closed
            permitted = False
        if not permitted:
            return _denied("PERMIT_DENIED")
        try:
            comparison = self._compare(request.native, request.gateway)
            if type(comparison) is not Comparison or comparison.authority != EVALUATION_MODE:
                return _denied("COMPUTE_FAILED")
            digest = _digest(tenant, source, request.params_digest, request, comparison)
        except Exception:  # noqa: BLE001 - never leak exception text
            return _denied("COMPUTE_FAILED")
        return EvaluationResult(EvaluationStatus.COMPUTED, "COMPUTED", comparison,
                                EVALUATION_MODE, digest)
