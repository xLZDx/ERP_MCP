"""Phase 2 sprint S9 E3 (R2-US-045, REQ25, TC133): typed migration classification, rehearsal, shadow compare.

Offline, unwired, in-memory, PLATFORM level (no tenant data in any type here). No I/O, no clock, no
randomness, no Release 1 import, no deletion code. Public functions never raise.

Public names
* ``Phase`` / ``StepKind`` / ``SchemaName`` / ``ObjectClass`` / ``MigrationStep`` / ``StepClass`` and
  ``classify_step`` - a step is classified from its TYPED description only (never by parsing SQL and never
  by a name list). Enum identity decides: a renamed or aliased destructive kind is still destructive.
  Result ``ADDITIVE`` / ``SWITCH_ONLY`` / ``CONTRACT`` / ``DESTRUCTIVE`` / ``UNCLASSIFIED``.
  Anything that is not an exact enum member, a forged ``object.__new__`` step, an unknown kind, a step on
  the R1 schema or on an R1 object class, or a kind in the wrong phase / on the wrong object class is
  ``UNCLASSIFIED`` and therefore denied. A destructive kind is ``DESTRUCTIVE`` in every phase.
* ``MigrationUnit`` / ``plan_rehearsal`` / ``RehearsalPlan`` / ``RehearsalAction`` - an ordered rehearsal
  plan validated against ``living.record_migration(version, requires)`` semantics: every ``requires``
  entry must be applied (or planned earlier in the same plan), a version whose numeric predecessor is
  neither applied nor planned is a gap (refused), re-applying an applied version is an idempotent no-op,
  and every step of a unit that would really run must classify ``ADDITIVE``. The real rehearsal on a
  disposable copy of the R1 database is NOT_RUN.
* ``ShadowObservation`` / ``compare_shadow`` / ``ShadowResult`` - digest comparison over a scripted R1
  corpus. Fixed priority ``R1_REGRESSION`` > ``SHADOW_INCOMPLETE`` > ``SHADOW_DIVERGENCE`` >
  ``R1_UNCHANGED``. Operation ids are typed fixture ids (pattern-checked), never free text. A result can
  never permit a promotion (``promotion_permitted`` is the constant ``False``).

Outputs are frozen, digest-bound (the digest is DERIVED in ``__post_init__``), ``EVALUATION_ONLY`` and
never echo caller text. Refusals use the shared ``OpsRefusal`` with an id from the injected source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .comparison_snapshot import canonical_digest
from .ops_types import AUTHORITY, OpsReason, OpsRefusal, is_digest, ops_refusal

__all__ = [
    "MAX_OPERATIONS",
    "MAX_STEPS_PER_UNIT",
    "MAX_UNITS",
    "R1_OBJECT_CLASSES",
    "MigrationStep",
    "MigrationUnit",
    "ObjectClass",
    "Phase",
    "RehearsalAction",
    "RehearsalPlan",
    "SchemaName",
    "ShadowObservation",
    "ShadowResult",
    "StepClass",
    "StepKind",
    "classify_step",
    "compare_shadow",
    "is_operation_id",
    "plan_rehearsal",
]

MAX_UNITS: Final = 64
MAX_STEPS_PER_UNIT: Final = 512
MAX_OPERATIONS: Final = 1000
_MAX_REQUIRES: Final = 16
_MAX_APPLIED: Final = 64
_VERSION: Final = re.compile(r"[0-9]{3}")
_OPERATION_ID: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")


class Phase(StrEnum):
    EXPAND = "EXPAND"
    SHADOW = "SHADOW"
    SWITCH = "SWITCH"
    CONTRACT = "CONTRACT"


class SchemaName(StrEnum):
    LIVING = "LIVING"
    R1 = "R1"


class ObjectClass(StrEnum):
    SCHEMA = "SCHEMA"
    TABLE = "TABLE"
    INDEX = "INDEX"
    COLUMN = "COLUMN"
    FUNCTION = "FUNCTION"
    TRIGGER = "TRIGGER"
    POLICY = "POLICY"
    ROLE = "ROLE"
    PRIVILEGE = "PRIVILEGE"
    ROW_DATA = "ROW_DATA"
    FEATURE_FLAG = "FEATURE_FLAG"
    ROUTE = "ROUTE"
    R1_TABLE = "R1_TABLE"
    R1_FUNCTION = "R1_FUNCTION"
    R1_ROLE = "R1_ROLE"
    R1_OTHER = "R1_OTHER"


R1_OBJECT_CLASSES: Final = frozenset(
    {ObjectClass.R1_TABLE, ObjectClass.R1_FUNCTION, ObjectClass.R1_ROLE, ObjectClass.R1_OTHER})


class StepKind(StrEnum):
    # additive (expand / shadow)
    CREATE_SCHEMA = "CREATE_SCHEMA"
    CREATE_TABLE = "CREATE_TABLE"
    CREATE_INDEX = "CREATE_INDEX"
    ADD_NULLABLE_COLUMN = "ADD_NULLABLE_COLUMN"
    ADD_DEFAULTED_COLUMN = "ADD_DEFAULTED_COLUMN"
    ADD_FUNCTION = "ADD_FUNCTION"
    REPLACE_FUNCTION = "REPLACE_FUNCTION"
    ADD_TRIGGER = "ADD_TRIGGER"
    REPLACE_TRIGGER = "REPLACE_TRIGGER"
    ADD_POLICY = "ADD_POLICY"
    REPLACE_POLICY = "REPLACE_POLICY"
    ENABLE_RLS = "ENABLE_RLS"
    ADD_ROLE = "ADD_ROLE"
    GRANT = "GRANT"
    HARDEN_PRIVILEGES = "HARDEN_PRIVILEGES"
    SET_OWNER = "SET_OWNER"
    HARDEN_FUNCTION = "HARDEN_FUNCTION"
    INSERT_ROWS = "INSERT_ROWS"
    # switch only
    FEATURE_FLAG = "FEATURE_FLAG"
    ROUTE_SWITCH = "ROUTE_SWITCH"
    # contract (cleanup after the rollback window)
    RETIRE_FEATURE_FLAG = "RETIRE_FEATURE_FLAG"
    RETIRE_ROUTE = "RETIRE_ROUTE"
    # destructive in every phase
    DROP_TABLE = "DROP_TABLE"
    DROP_RELATION = "DROP_TABLE"  # alias: the very same member, so a rename of the kind changes nothing
    DROP_COLUMN = "DROP_COLUMN"
    DROP_INDEX = "DROP_INDEX"
    DROP_FUNCTION = "DROP_FUNCTION"
    DROP_TRIGGER = "DROP_TRIGGER"
    DROP_POLICY = "DROP_POLICY"
    DROP_SCHEMA = "DROP_SCHEMA"
    DROP_ROLE = "DROP_ROLE"
    TRUNCATE = "TRUNCATE"
    ALTER_TYPE = "ALTER_TYPE"
    RENAME = "RENAME"
    REVOKE = "REVOKE"
    DELETE_ROWS = "DELETE_ROWS"
    UPDATE_ROWS = "UPDATE_ROWS"
    NARROW_CONSTRAINT = "NARROW_CONSTRAINT"


class StepClass(StrEnum):
    ADDITIVE = "ADDITIVE"
    SWITCH_ONLY = "SWITCH_ONLY"
    CONTRACT = "CONTRACT"
    DESTRUCTIVE = "DESTRUCTIVE"
    UNCLASSIFIED = "UNCLASSIFIED"

    def as_reason(self) -> OpsReason:
        return OpsReason(self.value)


@dataclass(frozen=True, slots=True)
class MigrationStep:
    """A typed step description. Deliberately NOT validated here: ``classify_step`` is the one judge."""

    phase: Phase
    kind: StepKind
    schema: SchemaName
    object_class: ObjectClass

    def __repr__(self) -> str:
        return "MigrationStep(<typed>)"


@dataclass(frozen=True, slots=True)
class _Rule:
    step_class: StepClass
    phases: frozenset[Phase]
    classes: frozenset[ObjectClass]


def _build_rules() -> dict[StepKind, _Rule]:
    rules: dict[StepKind, _Rule] = {}
    oc = ObjectClass
    non_r1 = frozenset(c for c in ObjectClass if c not in R1_OBJECT_CLASSES)
    add_phases = frozenset({Phase.EXPAND, Phase.SHADOW})

    def additive(kind: StepKind, *classes: ObjectClass) -> None:
        rules[kind] = _Rule(StepClass.ADDITIVE, add_phases, frozenset(classes))

    additive(StepKind.CREATE_SCHEMA, oc.SCHEMA)
    additive(StepKind.CREATE_TABLE, oc.TABLE)
    additive(StepKind.CREATE_INDEX, oc.INDEX)
    additive(StepKind.ADD_NULLABLE_COLUMN, oc.COLUMN)
    additive(StepKind.ADD_DEFAULTED_COLUMN, oc.COLUMN)
    additive(StepKind.ADD_FUNCTION, oc.FUNCTION)
    additive(StepKind.REPLACE_FUNCTION, oc.FUNCTION)
    additive(StepKind.ADD_TRIGGER, oc.TRIGGER)
    additive(StepKind.REPLACE_TRIGGER, oc.TRIGGER)
    additive(StepKind.ADD_POLICY, oc.POLICY)
    additive(StepKind.REPLACE_POLICY, oc.POLICY)
    additive(StepKind.ENABLE_RLS, oc.TABLE)
    additive(StepKind.ADD_ROLE, oc.ROLE)
    additive(StepKind.GRANT, oc.PRIVILEGE)
    additive(StepKind.HARDEN_PRIVILEGES, oc.PRIVILEGE)
    additive(StepKind.SET_OWNER, oc.TABLE, oc.FUNCTION)
    additive(StepKind.HARDEN_FUNCTION, oc.FUNCTION)
    additive(StepKind.INSERT_ROWS, oc.ROW_DATA)
    rules[StepKind.FEATURE_FLAG] = _Rule(
        StepClass.SWITCH_ONLY, frozenset({Phase.SWITCH}), frozenset({oc.FEATURE_FLAG}))
    rules[StepKind.ROUTE_SWITCH] = _Rule(
        StepClass.SWITCH_ONLY, frozenset({Phase.SWITCH}), frozenset({oc.ROUTE}))
    rules[StepKind.RETIRE_FEATURE_FLAG] = _Rule(
        StepClass.CONTRACT, frozenset({Phase.CONTRACT}), frozenset({oc.FEATURE_FLAG}))
    rules[StepKind.RETIRE_ROUTE] = _Rule(
        StepClass.CONTRACT, frozenset({Phase.CONTRACT}), frozenset({oc.ROUTE}))
    for kind in (StepKind.DROP_TABLE, StepKind.DROP_COLUMN, StepKind.DROP_INDEX,
                 StepKind.DROP_FUNCTION, StepKind.DROP_TRIGGER, StepKind.DROP_POLICY,
                 StepKind.DROP_SCHEMA, StepKind.DROP_ROLE, StepKind.TRUNCATE, StepKind.ALTER_TYPE,
                 StepKind.RENAME, StepKind.REVOKE, StepKind.DELETE_ROWS, StepKind.UPDATE_ROWS,
                 StepKind.NARROW_CONSTRAINT):
        rules[kind] = _Rule(StepClass.DESTRUCTIVE, frozenset(Phase), non_r1)
    return rules


_RULES: Final = MappingProxyType(_build_rules())
if set(_RULES) != set(StepKind):  # import-time guard: a kind without a rule would be a silent hole
    raise RuntimeError("STEP_KIND_RULES_INCOMPLETE")


def classify_step(step: object) -> StepClass:
    """Classify one typed step. Total: never raises, anything doubtful is ``UNCLASSIFIED`` (denied)."""
    try:
        if type(step) is not MigrationStep:
            return StepClass.UNCLASSIFIED
        phase, kind, schema, object_class = (
            step.phase, step.kind, step.schema, step.object_class)  # one read each
    except Exception:  # noqa: BLE001 - forged object.__new__ instance: slots never set
        return StepClass.UNCLASSIFIED
    if (type(phase) is not Phase or type(kind) is not StepKind or type(schema) is not SchemaName
            or type(object_class) is not ObjectClass):
        return StepClass.UNCLASSIFIED
    if schema is not SchemaName.LIVING or object_class in R1_OBJECT_CLASSES:
        return StepClass.UNCLASSIFIED
    rule = _RULES.get(kind)
    if rule is None:
        return StepClass.UNCLASSIFIED
    if rule.step_class is StepClass.DESTRUCTIVE:
        return StepClass.DESTRUCTIVE
    if phase not in rule.phases or object_class not in rule.classes:
        return StepClass.UNCLASSIFIED
    return rule.step_class


# --------------------------------------------------------------------------------------------------
# rehearsal planning

@dataclass(frozen=True, slots=True)
class MigrationUnit:
    """One migration file as ``living.record_migration(version, requires)`` sees it."""

    version: str
    requires: tuple[str, ...]
    steps: tuple[MigrationStep, ...]

    def __repr__(self) -> str:
        return "MigrationUnit(<typed>)"


@dataclass(frozen=True, slots=True)
class RehearsalAction:
    version: str
    apply: bool  # False = already recorded: an idempotent no-op, like record_migration returning false
    step_count: int

    def __post_init__(self) -> None:
        if (type(self.version) is not str or _VERSION.fullmatch(self.version) is None
                or type(self.apply) is not bool or type(self.step_count) is not int
                or not 0 <= self.step_count <= MAX_STEPS_PER_UNIT):
            raise ValueError("REHEARSAL_ACTION_INVALID")


@dataclass(frozen=True, slots=True)
class RehearsalPlan:
    actions: tuple[RehearsalAction, ...]
    digest: str = field(init=False)
    authority: str = field(init=False, default=AUTHORITY)

    def __post_init__(self) -> None:
        if (type(self.actions) is not tuple or not 1 <= len(self.actions) <= MAX_UNITS
                or any(type(a) is not RehearsalAction for a in self.actions)):
            raise ValueError("REHEARSAL_PLAN_INVALID")
        object.__setattr__(self, "digest", canonical_digest(
            {"kind": "rehearsal", "actions": [[a.version, a.apply, a.step_count]
                                              for a in self.actions]}))

    @property
    def executed(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "RehearsalPlan(<derived>)"


def _tuple_of(value: object, limit: int, allowed: tuple[type, ...]) -> tuple[object, ...] | None:
    """One-time copy of a container of an exactly allowed type, bounded; ``None`` on anything else."""
    if type(value) not in allowed:
        return None
    try:
        if len(value) > limit:  # type: ignore[arg-type]
            return None
        return tuple(value)  # type: ignore[call-overload]
    except Exception:  # noqa: BLE001 - hostile container
        return None


def _version_ok(value: object) -> bool:
    return type(value) is str and _VERSION.fullmatch(value) is not None


def _snapshot_unit(unit: object) -> tuple[str, tuple[str, ...], tuple[object, ...]] | None:
    if type(unit) is not MigrationUnit:
        return None
    try:
        version, requires_raw, steps_raw = unit.version, unit.requires, unit.steps  # one read each
    except Exception:  # noqa: BLE001 - forged instance
        return None
    requires = _tuple_of(requires_raw, _MAX_REQUIRES, (tuple, list))
    steps = _tuple_of(steps_raw, MAX_STEPS_PER_UNIT, (tuple, list))
    if (not _version_ok(version) or requires is None or steps is None or not steps
            or not all(_version_ok(r) for r in requires)):
        return None
    return version, requires, steps  # type: ignore[return-value]


def plan_rehearsal(units: object, applied_versions: object, ids: object) -> RehearsalPlan | OpsRefusal:
    """Order and validate a migration rehearsal; ``RehearsalPlan`` or an ``OpsRefusal``. Never raises.

    ``record_migration`` semantics: each unit is judged in the given order against ``applied_versions``
    plus the units planned before it. Refusals: ``INPUT_INVALID`` (structure, bounds, empty unit),
    ``REHEARSAL_REQUIRES_UNMET`` (a ``requires`` entry or the numeric predecessor of a version above 001
    is neither applied nor planned earlier), and the class code ``DESTRUCTIVE`` / ``UNCLASSIFIED`` /
    ``SWITCH_ONLY`` / ``CONTRACT`` when a unit that would really run holds a step that is not ADDITIVE.
    """
    snap_units = _tuple_of(units, MAX_UNITS, (tuple, list))
    applied_raw = _tuple_of(applied_versions, _MAX_APPLIED, (tuple, list, frozenset, set))
    if not snap_units or applied_raw is None or not all(_version_ok(v) for v in applied_raw):
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    parsed = [_snapshot_unit(u) for u in snap_units]
    if any(p is None for p in parsed):
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    applied = frozenset(applied_raw)  # type: ignore[arg-type]
    satisfied = set(applied)
    actions: list[RehearsalAction] = []
    for entry in parsed:
        version, requires, steps = entry  # type: ignore[misc]
        if any(req not in satisfied for req in requires):
            return ops_refusal(OpsReason.REHEARSAL_REQUIRES_UNMET, ids)
        if version != "001" and f"{int(version) - 1:03d}" not in satisfied:
            return ops_refusal(OpsReason.REHEARSAL_REQUIRES_UNMET, ids)  # a gap in the sequence
        if version in satisfied:  # idempotent re-apply: a no-op, so its steps never run
            actions.append(RehearsalAction(version, False, len(steps)))
            continue
        classes = {classify_step(s) for s in steps}
        for worst in (StepClass.DESTRUCTIVE, StepClass.UNCLASSIFIED, StepClass.SWITCH_ONLY,
                      StepClass.CONTRACT):
            if worst in classes:
                return ops_refusal(worst.as_reason(), ids)
        satisfied.add(version)
        actions.append(RehearsalAction(version, True, len(steps)))
    return RehearsalPlan(tuple(actions))


# --------------------------------------------------------------------------------------------------
# shadow comparison

def is_operation_id(value: object) -> bool:
    """A typed fixture operation id: exact ``str`` of a fixed small pattern (never free text)."""
    return type(value) is str and _OPERATION_ID.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class ShadowObservation:
    operation_id: str
    r1_digest_before: str
    r1_digest_after_expand: str
    r2_shadow_digest: str

    def __repr__(self) -> str:
        return "ShadowObservation(<typed>)"


@dataclass(frozen=True, slots=True)
class ShadowResult:
    regressed: tuple[str, ...]
    divergent: tuple[str, ...]
    missing: tuple[str, ...]
    reason: OpsReason = field(init=False)
    digest: str = field(init=False)
    authority: str = field(init=False, default=AUTHORITY)

    def __post_init__(self) -> None:
        groups = (self.regressed, self.divergent, self.missing)
        if any(type(g) is not tuple or len(g) > MAX_OPERATIONS
               or not all(is_operation_id(i) for i in g) for g in groups):
            raise ValueError("SHADOW_RESULT_INVALID")
        if self.regressed:
            reason = OpsReason.R1_REGRESSION
        elif self.missing:
            reason = OpsReason.SHADOW_INCOMPLETE
        elif self.divergent:
            reason = OpsReason.SHADOW_DIVERGENCE
        else:
            reason = OpsReason.R1_UNCHANGED
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "digest", canonical_digest(
            {"kind": "shadow", "reason": reason.value, "regressed": list(self.regressed),
             "divergent": list(self.divergent), "missing": list(self.missing)}))

    @property
    def promotion_permitted(self) -> bool:
        """A shadow result is a finding; it can never promote anything by itself."""
        return False

    def __repr__(self) -> str:
        return "ShadowResult(<derived>)"


def _snapshot_observation(obs: object) -> tuple[str, str, str, str] | None:
    if type(obs) is not ShadowObservation:
        return None
    try:
        row = (obs.operation_id, obs.r1_digest_before, obs.r1_digest_after_expand,
               obs.r2_shadow_digest)  # one read each
    except Exception:  # noqa: BLE001 - forged instance
        return None
    if not is_operation_id(row[0]) or not all(is_digest(d) for d in row[1:]):
        return None
    return row


def compare_shadow(expected_operations: object, observations: object,
                   ids: object) -> ShadowResult | OpsRefusal:
    """Digest comparison of R1 before/after the expand step and of R2's observed-only shadow output.

    ``R1_REGRESSION`` when any R1 digest changed (the typed operation ids are listed), else
    ``SHADOW_INCOMPLETE`` when an expected operation has no observation (absence is not a pass), else
    ``SHADOW_DIVERGENCE`` when an R2 shadow digest differs from the R1 digest after expand, else
    ``R1_UNCHANGED``. Hostile / duplicate / oversized input is an ``INPUT_INVALID`` refusal.
    """
    expected_raw = _tuple_of(expected_operations, MAX_OPERATIONS, (tuple, list, frozenset, set))
    obs_raw = _tuple_of(observations, MAX_OPERATIONS, (tuple, list))
    if (expected_raw is None or obs_raw is None or not expected_raw
            or not all(is_operation_id(o) for o in expected_raw)
            or len(set(expected_raw)) != len(expected_raw)):
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    rows = [_snapshot_observation(o) for o in obs_raw]
    if any(r is None for r in rows) or len({r[0] for r in rows if r is not None}) != len(rows):
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    seen = {r[0]: r for r in rows if r is not None}
    regressed = sorted(op for op, r in seen.items() if r[1] != r[2])
    divergent = sorted(op for op, r in seen.items() if r[3] != r[2])
    missing = sorted(op for op in expected_raw if op not in seen)  # type: ignore[operator]
    return ShadowResult(tuple(regressed), tuple(divergent), tuple(missing))  # type: ignore[arg-type]
