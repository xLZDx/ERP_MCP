"""Synthetic E2E contract for the offline S5 native-capture executor.

These scenarios exercise injected authority, UI-port and baseline-intake boundaries only.
They do not launch a desktop, connect to 1C, or qualify a native capture adapter.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2.artifact_vault import ArtifactScope, ArtifactVault, Principal
from business_ai_gateway.phase2.native_baseline_intake import (
    BaselineIntake,
    TrustedCaptureContext,
)
from business_ai_gateway.phase2.native_capture_executor import (
    CapturePermit,
    CaptureRecipe,
    CaptureScope,
    DispatchOperation,
    ExecutorState,
    OperationKind,
    ObservedScreen,
    PermitCheck,
    RecipeRegistry,
    SyntheticArtifact,
    SyntheticCaptureExecutor,
    _canonical_digest,
)


NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
SCOPE = CaptureScope("tenant-s5", "source-s5", "db-copy-1", "cfg-8.3", "company-a", "TrialBalance")
CONTEXT = TrustedCaptureContext(
    SCOPE.tenant_id, SCOPE.source_id, SCOPE.database_id, SCOPE.company_id,
    "workflow-s5", SCOPE.report_object, "standard",
)
PRINCIPAL = Principal("capture-owner")
ADMIN = Principal("vault-admin")
VAULT_PRINCIPAL = Principal("offline-vault")
ARTIFACT = b"account,total\n1000,42.00\n"


def recipe() -> CaptureRecipe:
    operations = (
        DispatchOperation("open", "OPEN_REPORT", "report.open", "IDLE", "REPORT_OPEN"),
        DispatchOperation("variant", "SELECT_VARIANT", "variant.select", "REPORT_OPEN", "VARIANT_SELECTED"),
        DispatchOperation("period", "SET_PARAMETER", "parameter.set", "VARIANT_SELECTED", "PARAMETERS_SET", "period"),
        DispatchOperation("run", "RUN_REPORT", "report.run", "PARAMETERS_SET", "RESULTS_READY"),
        DispatchOperation("export", "EXPORT", "export.csv", "RESULTS_READY", "RESULTS_READY"),
    )
    operations = tuple(replace(item, kind=OperationKind(item.kind)) for item in operations)
    return CaptureRecipe(
        "trial-balance", 1, SCOPE, "standard", (("period", "2026-10"),), "2026-10",
        ("account", "total"), (("total", "42.00"),), operations, "IDLE", "RESULTS_READY",
    )


class Authority:
    def __init__(self) -> None:
        self.permits: dict[str, CapturePermit] = {}
        self.reads = 0

    def current(self, permit_id: str) -> PermitCheck:
        self.reads += 1
        return PermitCheck(self.permits.get(permit_id))

    def issue(self, value: CapturePermit) -> None:
        self.permits[value.permit_id] = value

    def revoke(self, permit_id: str) -> None:
        self.permits[permit_id] = replace(self.permits[permit_id], revoked=True)


class SyntheticPort:
    environment = "synthetic"

    def __init__(self, *, state: str = "IDLE", selectors: tuple[str, ...] | None = None,
                 database_id: str = SCOPE.database_id, company_id: str = SCOPE.company_id,
                 configuration_id: str = SCOPE.configuration_id, modal_id: str | None = None,
                 stale_export: bool = False, fail_operation: str | None = None,
                 session_id: str = "synthetic-session-1", output_id: str = "synthetic-output-1") -> None:
        self.session_id = session_id
        self.output_id = output_id
        self.state = state
        self.selectors = selectors or ("report.open", "variant.select", "parameter.set", "report.run", "export.csv")
        self.database_id = database_id
        self.company_id = company_id
        self.configuration_id = configuration_id
        self.modal_id = modal_id
        self.generation = 4
        self.idle = state == "IDLE"
        self.stale_export = stale_export
        self.fail_operation = fail_operation
        self.observe_calls = 0
        self.dispatch_calls: list[str] = []
        self.export_calls: list[str] = []
        self.reconcile_calls: list[tuple[str, str]] = []
        self.exported: list[SyntheticArtifact] = []

    def observe(self) -> ObservedScreen:
        self.observe_calls += 1
        return self._screen()

    def dispatch(self, attempt_id: str, recipe: CaptureRecipe,
                 operation: DispatchOperation) -> ObservedScreen:
        assert attempt_id.startswith("attempt-")
        assert recipe.scope == SCOPE
        self.dispatch_calls.append(operation.operation_id)
        if operation.operation_id == self.fail_operation:
            raise TimeoutError("synthetic dispatch outcome unknown")
        self.state = operation.resulting_state
        self.idle = False
        return self._screen()

    def export(self, attempt_id: str) -> SyntheticArtifact:
        self.export_calls.append(attempt_id)
        generation = self.generation if self.stale_export else self.generation + 1
        self.generation = generation
        artifact = SyntheticArtifact(
            attempt_id, self.session_id, self.output_id, generation, "text/csv", ARTIFACT,
        )
        self.exported.append(artifact)
        return artifact

    def reconcile(self, attempt_id: str, session_id: str) -> ObservedScreen:
        self.reconcile_calls.append((attempt_id, session_id))
        return self._screen()

    def _screen(self) -> ObservedScreen:
        return ObservedScreen(
            self.session_id, self.database_id, self.configuration_id, self.company_id,
            self.state, self.selectors, self.modal_id, self.generation, self.idle,
        )


def setup(*, port: SyntheticPort | None = None, authority: Authority | None = None,
          intake_id_source=None, clock=lambda: NOW):
    current_recipe = recipe()
    registry = RecipeRegistry((current_recipe,))
    authority = authority or Authority()
    port = port or SyntheticPort()
    scope = ArtifactScope(SCOPE.tenant_id, SCOPE.source_id)
    vault = ArtifactVault(lambda: NOW, admins=(ADMIN.principal_id,))
    assert vault.grant(scope, VAULT_PRINCIPAL, ADMIN) == "OK"
    authorize = lambda context, principal: context == CONTEXT and principal == PRINCIPAL
    authorize_request = lambda context, principal, request_id: (
        context == CONTEXT and principal == PRINCIPAL and request_id.startswith("request-")
    )
    intake = BaselineIntake(
        vault, VAULT_PRINCIPAL, authorize, authorize_request=authorize_request,
        id_source=intake_id_source or (lambda: "baseline-s5-1"),
    )
    executor = SyntheticCaptureExecutor(
        registry=registry, authority=authority, port=port, intake=intake,
        context=CONTEXT, principal=PRINCIPAL, clock=clock,
    )
    return current_recipe, authority, port, vault, intake, executor


def permit_for(current_recipe: CaptureRecipe, *, permit_id: str = "permit-1",
               attempt_id: str = "attempt-1", request_id: str = "request-1", **changes) -> CapturePermit:
    value = CapturePermit(
        permit_id, attempt_id, request_id, "offline-synthetic-test-authority",
        PRINCIPAL.principal_id, CONTEXT.caller_namespace,
        SCOPE.tenant_id, SCOPE.source_id, SCOPE.database_id, SCOPE.configuration_id,
        SCOPE.company_id, SCOPE.report_object, current_recipe.recipe_id, current_recipe.version,
        _canonical_digest(current_recipe), tuple(item.operation_id for item in current_recipe.operations),
        NOW - timedelta(minutes=1), NOW + timedelta(minutes=5), False, True, "synthetic",
    )
    return replace(value, **changes)


def execute(executor: SyntheticCaptureExecutor, permit_id: str = "permit-1"):
    return executor.capture(permit_id=permit_id, recipe_id="trial-balance", recipe_version=1)


@pytest.mark.parametrize("permit_change", [
    {"tenant_id": "wrong-tenant"},
    {"database_id": "wrong-database"},
    {"company_id": "wrong-company"},
    {"principal_id": "wrong-principal"},
    {"caller_namespace": "wrong-workflow"},
    {"binding_digest": "0" * 64},
    {"authority_id": "untrusted-issuer"},
])
def test_tc065_wrong_scope_or_forged_permit_is_denied_before_any_dispatch(permit_change):
    current_recipe, authority, port, _, intake, executor = setup()
    authority.issue(permit_for(current_recipe, **permit_change))

    result = execute(executor)

    assert result.state is ExecutorState.REFUSED
    assert port.dispatch_calls == []
    assert port.export_calls == []
    assert intake.recover(context=CONTEXT, principal=PRINCIPAL, request_id="request-1") == (None, "INTAKE_REFUSED")


@pytest.mark.parametrize("clock_value,permit_change", [
    (NOW + timedelta(minutes=5), {}),
    (NOW, {"revoked": True}),
])
def test_tc065_expired_or_revoked_permit_is_denied_before_dispatch(clock_value, permit_change):
    current_recipe, authority, port, _, _, executor = setup(clock=lambda: clock_value)
    authority.issue(permit_for(current_recipe, **permit_change))

    result = execute(executor)

    assert result.state is ExecutorState.REFUSED
    assert port.observe_calls == 0
    assert port.dispatch_calls == []
    assert port.export_calls == []


@pytest.mark.parametrize("port_change", [
    {"database_id": "unverified-copy"},
    {"company_id": "unverified-company"},
    {"state": "UNKNOWN_DIALOG"},
    {"modal_id": "unexpected-modal"},
    {"selectors": ("variant.select", "parameter.set", "report.run", "export.csv")},
])
def test_tc065_unknown_identity_state_modal_or_selector_has_no_action_or_receipt(port_change):
    port = SyntheticPort(**port_change)
    current_recipe, authority, _, _, intake, executor = setup(port=port)
    authority.issue(permit_for(current_recipe))

    result = execute(executor)

    assert result.state is ExecutorState.REFUSED
    assert port.dispatch_calls == []
    assert port.export_calls == []
    assert intake.recover(context=CONTEXT, principal=PRINCIPAL, request_id="request-1")[0] is None


def test_tc066_stale_export_is_not_published_and_attempt_remains_owned_until_idle_reconciliation():
    port = SyntheticPort(stale_export=True)
    current_recipe, authority, _, _, intake, executor = setup(port=port)
    authority.issue(permit_for(current_recipe))

    first = execute(executor)
    second_permit = permit_for(current_recipe, permit_id="permit-2", attempt_id="attempt-2", request_id="request-2")
    authority.issue(second_permit)
    blocked_reuse = execute(executor, "permit-2")

    assert first.state is ExecutorState.UNKNOWN
    assert blocked_reuse.state is ExecutorState.REFUSED
    assert len(port.dispatch_calls) == len(current_recipe.operations)
    assert port.export_calls == ["attempt-1"]
    assert intake.recover(context=CONTEXT, principal=PRINCIPAL, request_id="request-1")[0] is None

    not_idle = executor.reconcile_idle(attempt_id="attempt-1")
    assert not_idle.state is ExecutorState.UNKNOWN
    port.state, port.idle = "IDLE", True
    reconciled = executor.reconcile_idle(attempt_id="attempt-1")
    assert reconciled.code == "IDLE_RECONCILED_NEW_ATTEMPT_REQUIRED"
    assert port.reconcile_calls == [
        ("attempt-1", "synthetic-session-1"), ("attempt-1", "synthetic-session-1")
    ]


def test_tc066_second_executor_cannot_claim_a_session_owned_by_unknown_attempt():
    port = SyntheticPort(fail_operation="run")
    recipe_one, authority_one, _, _, _, executor_one = setup(port=port)
    authority_one.issue(permit_for(recipe_one))
    first = execute(executor_one)

    recipe_two, authority_two, _, _, _, executor_two = setup(port=port)
    authority_two.issue(permit_for(
        recipe_two, permit_id="permit-2", attempt_id="attempt-2", request_id="request-2",
    ))
    observes_before_second_executor = port.observe_calls
    refused = execute(executor_two, "permit-2")

    assert first.state is ExecutorState.UNKNOWN
    assert refused.state is ExecutorState.REFUSED
    assert port.observe_calls == observes_before_second_executor
    assert port.dispatch_calls == ["open", "variant", "period", "run"]
    port.state, port.idle = "IDLE", True
    assert executor_one.reconcile_idle(attempt_id="attempt-1").code == "IDLE_RECONCILED_NEW_ATTEMPT_REQUIRED"


@pytest.mark.parametrize("shared_resource", ["session", "output"])
def test_tc066_distinct_ports_cannot_claim_the_same_session_or_output(shared_resource):
    first_port = SyntheticPort(fail_operation="run")
    recipe_one, authority_one, _, _, _, executor_one = setup(port=first_port)
    authority_one.issue(permit_for(recipe_one))
    assert execute(executor_one).state is ExecutorState.UNKNOWN

    second_port = SyntheticPort(
        session_id=first_port.session_id if shared_resource == "session" else "synthetic-session-2",
        output_id=first_port.output_id if shared_resource == "output" else "synthetic-output-2",
    )
    recipe_two, authority_two, _, _, _, executor_two = setup(port=second_port)
    authority_two.issue(permit_for(
        recipe_two, permit_id="permit-2", attempt_id="attempt-2", request_id="request-2",
    ))
    refused = execute(executor_two, "permit-2")

    assert refused.state is ExecutorState.REFUSED
    assert second_port.observe_calls == 0
    assert second_port.dispatch_calls == []
    first_port.state, first_port.idle = "IDLE", True
    assert executor_one.reconcile_idle(attempt_id="attempt-1").code == "IDLE_RECONCILED_NEW_ATTEMPT_REQUIRED"


def test_tc066_unknown_dispatch_outcome_cannot_be_retried_until_idle_reconciliation():
    port = SyntheticPort(fail_operation="run")
    current_recipe, authority, _, _, intake, executor = setup(port=port)
    authority.issue(permit_for(current_recipe))

    unknown = execute(executor)
    retry_permit = permit_for(current_recipe, permit_id="permit-2", attempt_id="attempt-2", request_id="request-2")
    authority.issue(retry_permit)
    refused_retry = execute(executor, "permit-2")

    assert unknown.state is ExecutorState.UNKNOWN
    assert refused_retry.state is ExecutorState.REFUSED
    assert port.dispatch_calls == ["open", "variant", "period", "run"]
    assert port.export_calls == []
    assert intake.recover(context=CONTEXT, principal=PRINCIPAL, request_id="request-1")[0] is None
    port.state, port.idle = "IDLE", True
    assert executor.reconcile_idle(attempt_id="attempt-1").code == "IDLE_RECONCILED_NEW_ATTEMPT_REQUIRED"


def test_tc066_exact_completed_replay_reads_same_receipt_without_second_dispatch():
    current_recipe, authority, port, _, intake, executor = setup()
    authority.issue(permit_for(current_recipe))

    captured = execute(executor)
    calls_after_first_capture = tuple(port.dispatch_calls)
    replay = execute(executor)
    recovered, code = intake.recover(context=CONTEXT, principal=PRINCIPAL, request_id="request-1")

    assert captured.state is ExecutorState.COMPLETE and captured.code == "CAPTURED"
    assert replay.state is ExecutorState.COMPLETE and replay.code == "REPLAYED"
    assert replay.baseline == captured.baseline == recovered
    assert captured.attempt_id == "attempt-1"
    assert captured.baseline is not None
    assert (
        captured.baseline.request_id,
        captured.baseline.tenant_id,
        captured.baseline.source_id,
        captured.baseline.database_id,
        captured.baseline.company_id,
        captured.baseline.report_object,
        captured.baseline.variant,
    ) == (
        "request-1", SCOPE.tenant_id, SCOPE.source_id, SCOPE.database_id,
        SCOPE.company_id, SCOPE.report_object, "standard",
    )
    assert code == "OK"
    assert tuple(port.dispatch_calls) == calls_after_first_capture
    assert len(port.export_calls) == 1


def test_tc066_revocation_at_intake_publication_boundary_prevents_receipt_visibility():
    authority_holder: dict[str, Authority] = {}
    permit_holder: dict[str, str] = {}

    def revoke_when_baseline_id_is_requested() -> str:
        authority_holder["authority"].revoke(permit_holder["permit"])
        return "baseline-never-published"

    current_recipe, authority, port, _, intake, executor = setup(
        intake_id_source=revoke_when_baseline_id_is_requested,
    )
    authority_holder["authority"] = authority
    permit_holder["permit"] = "permit-1"
    authority.issue(permit_for(current_recipe))

    result = execute(executor)

    assert result.state is ExecutorState.UNKNOWN
    assert port.dispatch_calls == [item.operation_id for item in current_recipe.operations]
    assert port.export_calls == ["attempt-1"]
    assert intake.recover(context=CONTEXT, principal=PRINCIPAL, request_id="request-1") == (None, "INTAKE_REFUSED")
    assert intake.read(context=CONTEXT, principal=PRINCIPAL, baseline_id="baseline-never-published").result is None
    port.state, port.idle = "IDLE", True
    assert executor.reconcile_idle(attempt_id="attempt-1").code == "IDLE_RECONCILED_NEW_ATTEMPT_REQUIRED"

