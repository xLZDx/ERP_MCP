"""Bounded, process-local executor for synthetic native-capture recipes (S5 R2-US-022).

This module is an offline contract. It contains no desktop automation, 1C client,
network route, credential handling, or production adapter. A port supplied by a
caller must itself be qualified as a synthetic disposable-copy adapter.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from .artifact_vault import Principal
from .native_baseline_intake import (
    BaselineIntake,
    BaselineManifestClaims,
    BaselineResult,
    TrustedCaptureContext,
)

__all__ = [
    "AttemptClaim", "CapturePermit", "CapturePermitAuthority", "CaptureRecipe", "CaptureScope",
    "DispatchOperation", "ExecutorResult", "ExecutorState", "ObservedScreen", "OperationKind",
    "OfflineCapturePort", "PermitCheck", "RecipeRegistry", "SyntheticArtifact",
    "SyntheticCaptureExecutor",
]

_MAX_ID = 256
_MAX_TEXT = 4096
_MAX_OPERATIONS = 32
_MAX_PARAMETERS = 128
_MAX_ATTEMPTS = 10_000
_MAX_PORT_LEASES = 1024
_MAX_ARTIFACT_BYTES = 5_000_000
_SYNTHETIC_AUTHORITY = "offline-synthetic-test-authority"
_KNOWN_STATES = frozenset({
    "IDLE", "REPORT_OPEN", "VARIANT_SELECTED", "PARAMETERS_SET", "RESULTS_READY",
})


class ExecutorState(StrEnum):
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    COMPLETE = "COMPLETE"
    REFUSED = "REFUSED"


class OperationKind(StrEnum):
    OPEN_REPORT = "OPEN_REPORT"
    SELECT_VARIANT = "SELECT_VARIANT"
    SET_PARAMETER = "SET_PARAMETER"
    RUN_REPORT = "RUN_REPORT"
    EXPORT = "EXPORT"


_KNOWN_SELECTORS = {
    OperationKind.OPEN_REPORT: "report.open",
    OperationKind.SELECT_VARIANT: "variant.select",
    OperationKind.SET_PARAMETER: "parameter.set",
    OperationKind.RUN_REPORT: "report.run",
    OperationKind.EXPORT: "export.csv",
}
_PORT_LEASE_LOCK = threading.Lock()
_PORT_LEASES: dict[tuple[str, str], tuple[object, str]] = {}


@dataclass(frozen=True, slots=True)
class CaptureScope:
    """Trusted adapter scope and exact observed 1C-copy identity."""

    tenant_id: str
    source_id: str
    database_id: str
    configuration_id: str
    company_id: str
    report_object: str


@dataclass(frozen=True, slots=True)
class DispatchOperation:
    """One catalogued action, bound to a selector and known before/after states."""

    operation_id: str
    kind: OperationKind
    selector: str
    allowed_state: str
    resulting_state: str
    parameter_name: str = ""


@dataclass(frozen=True, slots=True)
class CaptureRecipe:
    """Immutable trusted recipe. Parameter pairs must be normalized and sorted."""

    recipe_id: str
    version: int
    scope: CaptureScope
    variant: str
    normalized_parameters: tuple[tuple[str, str], ...]
    period: str
    columns: tuple[str, ...]
    totals: tuple[tuple[str, str], ...]
    operations: tuple[DispatchOperation, ...]
    initial_state: str
    final_state: str


@dataclass(frozen=True, slots=True)
class CapturePermit:
    """Opaque permit record returned by an injected synthetic authority."""

    permit_id: str
    attempt_id: str
    intake_request_id: str
    authority_id: str
    principal_id: str
    caller_namespace: str
    tenant_id: str
    source_id: str
    database_id: str
    configuration_id: str
    company_id: str
    report_object: str
    recipe_id: str
    recipe_version: int
    binding_digest: str
    allowed_operations: tuple[str, ...]
    not_before: datetime
    expires_at: datetime
    revoked: bool
    approved: bool
    environment: str


@dataclass(frozen=True, slots=True)
class PermitCheck:
    """Fresh permit view; authority failure must be represented by ``None``."""

    permit: CapturePermit | None


class AttemptClaim(StrEnum):
    CLAIMED = "CLAIMED"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    REFUSED = "REFUSED"


class CapturePermitAuthority(Protocol):
    """Independent authority read; implementations must observe current revocation."""

    def current(self, permit_id: str) -> PermitCheck: ...

    def claim_attempt(self, permit: CapturePermit) -> AttemptClaim:
        """Atomically consume the exact issued binding, shared by all executors.

        ALREADY_CLAIMED is reserved for the same binding. A changed permit, attempted
        reuse of either identifier, revoked permit or unavailable authority must refuse.
        """
        ...


@dataclass(frozen=True, slots=True)
class ObservedScreen:
    """Exact offline observation; unknown states, selectors and modals are denied."""

    session_id: str
    database_id: str
    configuration_id: str
    company_id: str
    state: str
    available_selectors: tuple[str, ...]
    modal_id: str | None
    export_generation: int
    idle: bool


@dataclass(frozen=True, slots=True)
class SyntheticArtifact:
    """Export bytes emitted by a synthetic port and tied to one attempt/session."""

    attempt_id: str
    session_id: str
    output_id: str
    generation: int
    media_type: str
    content: bytes


class OfflineCapturePort(Protocol):
    """Minimal injectable synthetic interface; never performs identity or permit checks."""

    environment: str
    session_id: str
    output_id: str

    def observe(self) -> ObservedScreen: ...

    def dispatch(self, attempt_id: str, recipe: CaptureRecipe,
                 operation: DispatchOperation) -> ObservedScreen: ...

    def export(self, attempt_id: str) -> SyntheticArtifact: ...

    def reconcile(self, attempt_id: str, session_id: str) -> ObservedScreen: ...


@dataclass(frozen=True, slots=True)
class ExecutorResult:
    state: ExecutorState
    code: str
    attempt_id: str
    binding_digest: str = ""
    baseline: BaselineResult | None = None


@dataclass(frozen=True, slots=True)
class _Attempt:
    attempt_id: str
    permit_id: str
    principal_id: str
    recipe: CaptureRecipe
    scope: CaptureScope
    digest: str
    session_id: str
    state: ExecutorState
    baseline: BaselineResult | None = None


def _valid_text(value: object, limit: int = _MAX_TEXT, *, empty: bool = False) -> bool:
    return (type(value) is str and (empty or bool(value)) and len(value) <= limit
            and value == value.strip() and "\x00" not in value)


def _pairs_valid(value: object) -> bool:
    if type(value) is not tuple or len(value) > _MAX_PARAMETERS:
        return False
    previous = ""
    for pair in value:
        if (type(pair) is not tuple or len(pair) != 2
                or not _valid_text(pair[0]) or not _valid_text(pair[1], empty=True)
                or pair[0] <= previous):
            return False
        previous = pair[0]
    return True


def _valid_scope(scope: object) -> bool:
    return type(scope) is CaptureScope and all(
        _valid_text(getattr(scope, name), _MAX_ID)
        for name in ("tenant_id", "source_id", "database_id", "configuration_id",
                     "company_id", "report_object")
    )


def _valid_recipe(recipe: object) -> bool:
    if type(recipe) is not CaptureRecipe or not _valid_scope(recipe.scope):
        return False
    if (not _valid_text(recipe.recipe_id, _MAX_ID) or type(recipe.version) is not int
            or recipe.version <= 0 or not _valid_text(recipe.variant)
            or not _valid_text(recipe.period) or not _valid_text(recipe.initial_state)
            or not _valid_text(recipe.final_state) or not _pairs_valid(recipe.normalized_parameters)):
        return False
    if (type(recipe.columns) is not tuple or not 1 <= len(recipe.columns) <= 256
            or any(not _valid_text(item) for item in recipe.columns)
            or len(set(recipe.columns)) != len(recipe.columns)
            or type(recipe.totals) is not tuple or not recipe.totals
            or not _pairs_valid(recipe.totals)):
        return False
    if type(recipe.operations) is not tuple or not 1 <= len(recipe.operations) <= _MAX_OPERATIONS:
        return False
    ids: set[str] = set()
    kinds = tuple(operation.kind for operation in recipe.operations)
    expected_kinds = (
        OperationKind.OPEN_REPORT,
        OperationKind.SELECT_VARIANT,
        *((OperationKind.SET_PARAMETER,) * sum(
            operation.kind is OperationKind.SET_PARAMETER for operation in recipe.operations
        )),
        OperationKind.RUN_REPORT,
        OperationKind.EXPORT,
    )
    if kinds != expected_kinds:
        return False
    for operation in recipe.operations:
        if (type(operation) is not DispatchOperation or type(operation.kind) is not OperationKind
                or not _valid_text(operation.operation_id, _MAX_ID)
                or operation.operation_id in ids or not _valid_text(operation.selector, _MAX_ID)
                or not _valid_text(operation.allowed_state, _MAX_ID)
                or operation.allowed_state not in _KNOWN_STATES
                or not _valid_text(operation.resulting_state, _MAX_ID)
                or operation.resulting_state not in _KNOWN_STATES
                or operation.selector != _KNOWN_SELECTORS[operation.kind]
                or not _valid_text(operation.parameter_name, _MAX_ID, empty=True)):
            return False
        ids.add(operation.operation_id)
        if operation.kind is OperationKind.SET_PARAMETER:
            if operation.parameter_name not in {key for key, _ in recipe.normalized_parameters}:
                return False
        elif operation.parameter_name:
            return False
        transitions = {
            OperationKind.OPEN_REPORT: ("IDLE", "REPORT_OPEN"),
            OperationKind.SELECT_VARIANT: ("REPORT_OPEN", "VARIANT_SELECTED"),
            OperationKind.RUN_REPORT: (
                "PARAMETERS_SET" if recipe.normalized_parameters else "VARIANT_SELECTED",
                "RESULTS_READY",
            ),
            OperationKind.EXPORT: ("RESULTS_READY", "RESULTS_READY"),
        }
        if operation.kind is OperationKind.SET_PARAMETER:
            if operation.allowed_state not in {"VARIANT_SELECTED", "PARAMETERS_SET"} \
                    or operation.resulting_state != "PARAMETERS_SET":
                return False
        elif (operation.allowed_state, operation.resulting_state) != transitions[operation.kind]:
            return False
    configured_parameters = tuple(
        operation.parameter_name for operation in recipe.operations
        if operation.kind is OperationKind.SET_PARAMETER
    )
    if configured_parameters != tuple(key for key, _ in recipe.normalized_parameters):
        return False
    text_size = sum(map(len, (
        recipe.recipe_id, recipe.scope.tenant_id, recipe.scope.source_id,
        recipe.scope.database_id, recipe.scope.configuration_id, recipe.scope.company_id,
        recipe.scope.report_object, recipe.variant, recipe.period,
    )))
    text_size += sum(len(key) + len(value) for key, value in recipe.normalized_parameters)
    text_size += sum(map(len, recipe.columns))
    text_size += sum(len(key) + len(value) for key, value in recipe.totals)
    text_size += sum(len(operation.operation_id) + len(operation.selector)
                     + len(operation.allowed_state) + len(operation.resulting_state)
                     + len(operation.parameter_name) for operation in recipe.operations)
    if text_size > 100_000:
        return False
    return (recipe.initial_state == "IDLE" and recipe.final_state == "RESULTS_READY"
            and recipe.operations[0].allowed_state == recipe.initial_state
            and recipe.operations[-1].resulting_state == recipe.final_state
            and all(a.resulting_state == b.allowed_state
                    for a, b in zip(recipe.operations, recipe.operations[1:])))


def _canonical_digest(recipe: CaptureRecipe) -> str:
    scope = recipe.scope
    value = {
        "tenant": scope.tenant_id,
        "source": scope.source_id,
        "database": scope.database_id,
        "configuration": scope.configuration_id,
        "company": scope.company_id,
        "report": scope.report_object,
        "variant": recipe.variant,
        "parameters": recipe.normalized_parameters,
        "period": recipe.period,
        "columns": recipe.columns,
        "totals": recipe.totals,
        "operations": tuple((item.operation_id, item.kind.value, item.selector,
                              item.allowed_state, item.resulting_state, item.parameter_name)
                             for item in recipe.operations),
        "recipe_id": recipe.recipe_id,
        "recipe_version": recipe.version,
    }
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RecipeRegistry:
    """Small immutable-at-use map populated by trusted composition, not request input."""

    def __init__(self, recipes: tuple[CaptureRecipe, ...], *, max_recipes: int = 128) -> None:
        if type(recipes) is not tuple or not 1 <= len(recipes) <= min(max_recipes, 128):
            raise ValueError("RECIPE_REGISTRY_INVALID")
        by_key: dict[tuple[str, int], CaptureRecipe] = {}
        for recipe in recipes:
            if not _valid_recipe(recipe) or (recipe.recipe_id, recipe.version) in by_key:
                raise ValueError("RECIPE_REGISTRY_INVALID")
            by_key[(recipe.recipe_id, recipe.version)] = recipe
        self._recipes = MappingProxyType(by_key)

    def get(self, recipe_id: str, version: int) -> CaptureRecipe | None:
        if not _valid_text(recipe_id, _MAX_ID) or type(version) is not int:
            return None
        return self._recipes.get((recipe_id, version))


class SyntheticCaptureExecutor:
    """Fail-closed recipe executor with exclusive in-process attempt/output ownership.

    All dependencies and the capture context are supplied by trusted composition.
    This adapter intentionally refuses anything except an explicitly synthetic permit.
    One port object represents one synthetic session/output lane; a process-wide
    lease prevents two executor instances from dispatching through the same object.
    """

    def __init__(self, *, registry: RecipeRegistry, authority: CapturePermitAuthority,
                 port: OfflineCapturePort, intake: BaselineIntake,
                 context: TrustedCaptureContext, principal: Principal,
                 clock=lambda: datetime.now(timezone.utc), max_attempts: int = _MAX_ATTEMPTS) -> None:
        session_id = getattr(port, "session_id", None)
        output_id = getattr(port, "output_id", None)
        if (type(registry) is not RecipeRegistry or not callable(getattr(authority, "current", None))
                or not callable(getattr(authority, "claim_attempt", None))
                 or not all(callable(getattr(port, method, None))
                           for method in ("observe", "dispatch", "export", "reconcile"))
                or getattr(port, "environment", None) != "synthetic"
                or not _valid_text(session_id, _MAX_ID) or not _valid_text(output_id, _MAX_ID)
                or type(intake) is not BaselineIntake or type(context) is not TrustedCaptureContext
                or type(principal) is not Principal or not callable(clock)
                or type(max_attempts) is not int or max_attempts <= 0):
            raise TypeError("NATIVE_CAPTURE_DEPENDENCY_INVALID")
        self._registry = registry
        self._authority = authority
        self._port = port
        self._session_id = session_id
        self._output_id = output_id
        self._lease_keys = (("session", session_id), ("output", output_id))
        self._intake = intake
        self._context = context
        self._principal = principal
        self._clock = clock
        self._max_attempts = min(max_attempts, _MAX_ATTEMPTS)
        self._lock = threading.RLock()
        self._attempts: dict[str, _Attempt] = {}
        self._active_attempt: str | None = None

    @staticmethod
    def _utc(value: object) -> datetime | None:
        try:
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                return None
            return value.astimezone(timezone.utc)
        except Exception:
            return None

    def _now(self) -> datetime | None:
        try:
            return self._utc(self._clock())
        except Exception:
            return None

    def _current_permit(self, permit_id: str, recipe: CaptureRecipe,
                        digest: str) -> CapturePermit | None:
        try:
            response = self._authority.current(permit_id)
        except Exception:
            return None
        if type(response) is not PermitCheck or type(response.permit) is not CapturePermit:
            return None
        permit = response.permit
        now = self._now()
        scope = recipe.scope
        text_fields = (
            permit.permit_id, permit.attempt_id, permit.intake_request_id,
            permit.authority_id, permit.principal_id, permit.caller_namespace,
            permit.environment, permit.tenant_id, permit.source_id, permit.database_id,
            permit.configuration_id, permit.company_id, permit.report_object,
            permit.recipe_id, permit.binding_digest,
        )
        if (not all(_valid_text(item, _MAX_ID) for item in text_fields)
                or type(permit.recipe_version) is not int
                or type(permit.allowed_operations) is not tuple
                or any(not _valid_text(item, _MAX_ID) for item in permit.allowed_operations)
                or type(permit.revoked) is not bool or type(permit.approved) is not bool):
            return None
        if now is None or (permit.permit_id, permit.authority_id, permit.environment,
                           permit.tenant_id, permit.source_id, permit.database_id,
                           permit.configuration_id, permit.company_id, permit.report_object,
                           permit.recipe_id, permit.recipe_version, permit.binding_digest,
                           permit.principal_id, permit.caller_namespace) != (
                permit_id, _SYNTHETIC_AUTHORITY, "synthetic", scope.tenant_id,
                scope.source_id, scope.database_id, scope.configuration_id,
                scope.company_id, scope.report_object, recipe.recipe_id,
                recipe.version, digest, self._principal.principal_id, self._context.caller_namespace):
            return None
        not_before = self._utc(permit.not_before)
        expires_at = self._utc(permit.expires_at)
        if (permit.revoked or permit.approved is not True
                or permit.allowed_operations != tuple(item.operation_id for item in recipe.operations)
                or not_before is None or expires_at is None or not not_before <= now < expires_at):
            return None
        return permit

    @staticmethod
    def _observed(screen: object, scope: CaptureScope, *, session_id: str | None = None) -> bool:
        if type(screen) is not ObservedScreen:
            return False
        return (all(_valid_text(getattr(screen, name), _MAX_ID) for name in
                    ("session_id", "database_id", "configuration_id", "company_id", "state"))
                and (screen.session_id == session_id if session_id is not None else True)
                and (screen.database_id, screen.configuration_id, screen.company_id) ==
                    (scope.database_id, scope.configuration_id, scope.company_id)
                and type(screen.available_selectors) is tuple
                and all(_valid_text(item, _MAX_ID) for item in screen.available_selectors)
                and len(set(screen.available_selectors)) == len(screen.available_selectors)
                and screen.modal_id is None
                and type(screen.export_generation) is int and screen.export_generation >= 0
                and type(screen.idle) is bool)

    def capture(self, *, permit_id: str, recipe_id: str, recipe_version: int) -> ExecutorResult:
        """Execute once; all uncertain exits retain ownership and cannot be retried."""
        if not _valid_text(permit_id, _MAX_ID):
            return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", "")
        recipe = self._registry.get(recipe_id, recipe_version)
        if recipe is None or not _valid_recipe(recipe):
            return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", "")
        scope = recipe.scope
        if (scope.tenant_id, scope.source_id, scope.database_id, scope.company_id,
                scope.report_object) != (self._context.tenant_id, self._context.source_id,
                                         self._context.database_id, self._context.company_id,
                                         self._context.report_object):
            return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", "")
        if recipe.variant != self._context.variant:
            return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", "")
        digest = _canonical_digest(recipe)
        with self._lock:
            # A completed exact replay reads the existing baseline only after current authorization.
            existing = next((attempt for attempt in self._attempts.values()
                             if attempt.permit_id == permit_id and attempt.recipe == recipe
                             and attempt.principal_id == self._principal.principal_id
                             and attempt.state is ExecutorState.COMPLETE), None)
            if existing is not None:
                permit = self._current_permit(permit_id, recipe, digest)
                if (permit is None or permit.attempt_id != existing.attempt_id
                        or existing.baseline is None
                        or permit.intake_request_id != existing.baseline.request_id):
                    return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", existing.attempt_id)
                read = self._intake.read(context=self._context, principal=self._principal,
                                         baseline_id=existing.baseline.baseline_id if existing.baseline else "")
                if read.result is None or read.content is None:
                    return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", existing.attempt_id)
                return ExecutorResult(ExecutorState.COMPLETE, "REPLAYED", existing.attempt_id,
                                      digest, read.result)
            if self._active_attempt is not None or len(self._attempts) >= self._max_attempts:
                return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", "")
            permit = self._current_permit(permit_id, recipe, digest)
            if permit is None or permit.attempt_id in self._attempts:
                return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", "")
            attempt_id = permit.attempt_id
            if not self._claim_port(attempt_id):
                return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", attempt_id)
            try:
                claim = self._authority.claim_attempt(permit)
            except Exception:
                claim = AttemptClaim.REFUSED
            if claim is not AttemptClaim.CLAIMED:
                self._release_port(attempt_id)
                if claim is AttemptClaim.ALREADY_CLAIMED:
                    baseline, code = self._intake.recover(
                        context=self._context, principal=self._principal,
                        request_id=permit.intake_request_id,
                    )
                    if (baseline is not None and code == "OK"
                            and self._publication_authorized(permit, recipe, digest)):
                        return ExecutorResult(ExecutorState.COMPLETE, "REPLAYED", attempt_id,
                                              digest, baseline)
                return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", attempt_id)
            try:
                initial = self._port.observe()
            except Exception:
                self._release_port(attempt_id)
                return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", attempt_id)
            if (not self._observed(initial, scope, session_id=self._session_id)
                    or initial.state != recipe.initial_state
                    or not initial.idle):
                self._release_port(attempt_id)
                return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", attempt_id)
            attempt = _Attempt(attempt_id, permit_id, self._principal.principal_id,
                               recipe, scope, digest, initial.session_id, ExecutorState.PENDING)
            # Claim session/output before the first action; any unexpected failure retains the lease.
            self._attempts[attempt_id] = attempt
            self._active_attempt = attempt_id
            observed = initial
            dispatch_started = False
            try:
                for operation in recipe.operations:
                    if (not self._publication_authorized(permit, recipe, digest)
                            or not self._observed(observed, scope, session_id=initial.session_id)
                            or observed.state != operation.allowed_state
                            or operation.selector not in observed.available_selectors):
                        if not dispatch_started:
                            self._attempts[attempt_id] = replace(attempt, state=ExecutorState.REFUSED)
                            self._active_attempt = None
                            self._release_port(attempt_id)
                            return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", attempt_id, digest)
                        return self._refuse_locked(attempt, "CAPTURE_REFUSED")
                    dispatch_started = True
                    observed = self._port.dispatch(attempt_id, recipe, operation)
                    if (not self._observed(observed, scope, session_id=initial.session_id)
                            or observed.state != operation.resulting_state):
                        return self._unknown_locked(attempt)
                if (observed.state != recipe.final_state
                        or not self._publication_authorized(permit, recipe, digest)):
                    return self._refuse_locked(attempt, "CAPTURE_REFUSED")
                artifact = self._port.export(attempt_id)
                if (type(artifact) is not SyntheticArtifact
                        or artifact.attempt_id != attempt_id or artifact.session_id != initial.session_id
                        or type(artifact.output_id) is not str or artifact.output_id != self._output_id
                        or type(artifact.generation) is not int
                        or artifact.generation <= initial.export_generation
                        or type(artifact.content) is not bytes or not artifact.content
                        or len(artifact.content) > _MAX_ARTIFACT_BYTES
                        or artifact.media_type != "text/csv"):
                    return self._unknown_locked(attempt)
                # Re-read state and permit at publication boundary; stale output is never attached.
                final = self._port.observe()
                if (not self._observed(final, scope, session_id=initial.session_id)
                        or final.state != recipe.final_state
                        or final.export_generation != artifact.generation
                        or not self._publication_authorized(permit, recipe, digest)):
                    return self._refuse_locked(attempt, "CAPTURE_REFUSED")
                filters = recipe.normalized_parameters
                claims = BaselineManifestClaims(
                    scope.tenant_id, scope.source_id, scope.database_id, scope.company_id,
                    scope.report_object, recipe.variant, recipe.period, filters,
                    recipe.columns, recipe.totals, False, False, False,
                )
                result, code = self._intake.intake(
                    context=self._context, principal=self._principal,
                    request_id=permit.intake_request_id,
                    claims=claims, content=artifact.content, media_type=artifact.media_type,
                    publication_authorized=lambda: self._publication_authorized(
                        permit, recipe, digest),
                )
                if result is None or code != "OK":
                    return self._refuse_locked(attempt, "CAPTURE_REFUSED")
                complete = _Attempt(attempt.attempt_id, attempt.permit_id, attempt.principal_id,
                                    attempt.recipe, attempt.scope, attempt.digest,
                                    attempt.session_id, ExecutorState.COMPLETE, result)
                self._attempts[attempt_id] = complete
                self._active_attempt = None
                self._release_port(attempt_id)
                return ExecutorResult(ExecutorState.COMPLETE, "CAPTURED", attempt_id, digest, result)
            except Exception:
                return self._unknown_locked(attempt)

    def reconcile_idle(self, *, attempt_id: str) -> ExecutorResult:
        """Release an unresolved lease only after adapter confirms this exact session is idle."""
        if not _valid_text(attempt_id, _MAX_ID):
            return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", "")
        with self._lock:
            attempt = self._attempts.get(attempt_id)
            if (attempt is None or attempt.state not in (ExecutorState.PENDING, ExecutorState.UNKNOWN)
                    or self._active_attempt != attempt_id):
                return ExecutorResult(ExecutorState.REFUSED, "CAPTURE_REFUSED", attempt_id)
            try:
                observed = self._port.reconcile(attempt_id, attempt.session_id)
            except Exception:
                return ExecutorResult(ExecutorState.UNKNOWN, "RECONCILIATION_UNKNOWN", attempt_id,
                                      attempt.digest)
            if not self._observed(observed, attempt.scope, session_id=attempt.session_id):
                return ExecutorResult(ExecutorState.UNKNOWN, "RECONCILIATION_UNKNOWN", attempt_id,
                                      attempt.digest)
            if observed.state != attempt.recipe.initial_state or not observed.idle:
                return ExecutorResult(ExecutorState.UNKNOWN, "RECONCILIATION_UNKNOWN", attempt_id,
                                      attempt.digest)
            self._attempts[attempt_id] = _Attempt(
                attempt.attempt_id, attempt.permit_id, attempt.principal_id, attempt.recipe,
                attempt.scope, attempt.digest, attempt.session_id, ExecutorState.REFUSED)
            self._active_attempt = None
            self._release_port(attempt_id)
            return ExecutorResult(ExecutorState.REFUSED, "IDLE_RECONCILED_NEW_ATTEMPT_REQUIRED",
                                  attempt_id, attempt.digest)

    def _refuse_locked(self, attempt: _Attempt, code: str) -> ExecutorResult:
        # Keep attempt/session ownership unless the port later explicitly reconciles idle.
        self._attempts[attempt.attempt_id] = _Attempt(
            attempt.attempt_id, attempt.permit_id, attempt.principal_id, attempt.recipe,
            attempt.scope, attempt.digest, attempt.session_id, ExecutorState.UNKNOWN)
        return ExecutorResult(ExecutorState.UNKNOWN, code, attempt.attempt_id, attempt.digest)

    def _unknown_locked(self, attempt: _Attempt) -> ExecutorResult:
        return self._refuse_locked(attempt, "CAPTURE_OUTCOME_UNKNOWN")

    def _claim_port(self, attempt_id: str) -> bool:
        with _PORT_LEASE_LOCK:
            if (any(key in _PORT_LEASES for key in self._lease_keys)
                    or len(_PORT_LEASES) + len(self._lease_keys) > _MAX_PORT_LEASES):
                return False
            for key in self._lease_keys:
                _PORT_LEASES[key] = (self, attempt_id)
            return True

    def _release_port(self, attempt_id: str) -> None:
        with _PORT_LEASE_LOCK:
            for key in self._lease_keys:
                lease = _PORT_LEASES.get(key)
                if lease is not None and lease[0] is self and lease[1] == attempt_id:
                    _PORT_LEASES.pop(key, None)

    def _publication_authorized(self, expected: CapturePermit, recipe: CaptureRecipe,
                                digest: str) -> bool:
        """Recheck the permit at intake's locked publication boundary."""
        current = self._current_permit(expected.permit_id, recipe, digest)
        return (current is not None and current.attempt_id == expected.attempt_id
                and current.intake_request_id == expected.intake_request_id
                and current.principal_id == expected.principal_id
                and current.caller_namespace == expected.caller_namespace)
