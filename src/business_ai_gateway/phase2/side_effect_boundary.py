"""Phase 2 side-effect boundary for capture plans (R2-US-025, TC073-TC075).

Pure, in-memory, unwired from Release 1. Decides whether a capture plan is provably read-only.

Rules (fail closed, ALLOW-LIST only; nothing is ever classified by a deny-list):
* An operation name is canonicalised (NFKC + casefold + strip, see ``_identity``) and must then be
  plain ``[a-z0-9_.:-]``. Control/format/zero-width/blank glyphs or any other character (mixed-script
  homoglyphs included) make the name INVALID -> ``OPERATION_NAME_INVALID``. Names are never repaired.
* The registry maps canonical names to READ/WRITE/POST/DELETE/RESET/ADMIN. A name absent from the
  registry is UNCLASSIFIED and denies the plan. Only READ operations are allowed.
* An empty operation list proves nothing -> ``EMPTY_PLAN``.
* ``required_rights``: any right in the built-in admin/posting set disqualifies, and any right NOT in
  the explicit ``allowed_read_rights`` allow-list (default read/view/list) disqualifies too.
* Probes are classified like operations. A probe that is not READ is denied: ``PROBE_DENIED_IN_PROD``
  in PROD, ``PROBE_DENIED`` in NON_PROD.
* Coverage lists EVERY declared operation exactly once in input order (duplicates collapse and are
  reported in ``duplicate_ops``; invalid names appear as the fixed placeholder ``<invalid>``).
* Result codes are fixed strings and never echo caller input; wrong input types give
  ``INVALID_INPUT`` instead of an exception. The registry is immutable after build and construction
  rejects a name mapped to two classes.

``default_registry()`` is ILLUSTRATIVE only; the real operation inventory is an S5b / operator item.

KNOWN GAPS: the names are asserted by the caller. Nothing here proves that a registered name really
performs only the action its class claims (no connector introspection), and rights are strings, not
an authenticated principal's entitlements.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ._identity import clean_identity

__all__ = [
    "DEFAULT_ALLOWED_READ_RIGHTS",
    "DISQUALIFYING_RIGHTS",
    "BoundaryCode",
    "BoundaryDecision",
    "CapturePlan",
    "Environment",
    "OperationClass",
    "OperationRegistry",
    "RegistryError",
    "canonical_operation",
    "default_registry",
    "evaluate",
]

_NAME_RE = re.compile(r"[a-z0-9_.:-]+")
INVALID_PLACEHOLDER = "<invalid>"

DISQUALIFYING_RIGHTS = frozenset(
    {"admin", "administrator", "posting", "post", "full_access", "write", "supervisor"}
)
DEFAULT_ALLOWED_READ_RIGHTS = frozenset({"read", "view", "list"})


class OperationClass(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    POST = "POST"
    DELETE = "DELETE"
    RESET = "RESET"
    ADMIN = "ADMIN"
    UNCLASSIFIED = "UNCLASSIFIED"


class Environment(StrEnum):
    NON_PROD = "NON_PROD"
    PROD = "PROD"


class BoundaryCode(StrEnum):
    ALLOWED = "ALLOWED"
    INVALID_INPUT = "INVALID_INPUT"
    EMPTY_PLAN = "EMPTY_PLAN"
    OPERATION_NAME_INVALID = "OPERATION_NAME_INVALID"
    OPERATION_UNCLASSIFIED = "OPERATION_UNCLASSIFIED"
    WRITE_OPERATION = "WRITE_OPERATION"
    POST_OPERATION = "POST_OPERATION"
    DELETE_OPERATION = "DELETE_OPERATION"
    RESET_OPERATION = "RESET_OPERATION"
    ADMIN_OPERATION = "ADMIN_OPERATION"
    RIGHTS_DISQUALIFY = "RIGHTS_DISQUALIFY"
    PROBE_DENIED_IN_PROD = "PROBE_DENIED_IN_PROD"
    PROBE_DENIED = "PROBE_DENIED"


_CLASS_CODE = {
    OperationClass.WRITE: BoundaryCode.WRITE_OPERATION,
    OperationClass.POST: BoundaryCode.POST_OPERATION,
    OperationClass.DELETE: BoundaryCode.DELETE_OPERATION,
    OperationClass.RESET: BoundaryCode.RESET_OPERATION,
    OperationClass.ADMIN: BoundaryCode.ADMIN_OPERATION,
    OperationClass.UNCLASSIFIED: BoundaryCode.OPERATION_UNCLASSIFIED,
}


class RegistryError(ValueError):
    """Registry construction failed; the message is a fixed code and never echoes input."""


def canonical_operation(value: object) -> str:
    """Canonical operation name, or '' when not a str, forbidden chars, or not plain [a-z0-9_.:-]."""
    name = clean_identity(value)
    return name if name and _NAME_RE.fullmatch(name) else ""


@dataclass(frozen=True, slots=True)
class OperationRegistry:
    """Immutable allow-list ``canonical name -> OperationClass``. Build with ``from_entries``."""

    entries: Mapping[str, OperationClass]

    @classmethod
    def from_entries(cls, entries: object) -> OperationRegistry:
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
            raise RegistryError("REGISTRY_INVALID")
        built: dict[str, OperationClass] = {}
        for item in entries:
            if type(item) is not tuple or len(item) != 2:
                raise RegistryError("REGISTRY_INVALID")
            raw, klass = item
            name = canonical_operation(raw)
            if not name:
                raise RegistryError("REGISTRY_NAME_INVALID")
            if type(klass) is not OperationClass or klass is OperationClass.UNCLASSIFIED:
                raise RegistryError("REGISTRY_CLASS_INVALID")
            if name in built and built[name] is not klass:
                raise RegistryError("REGISTRY_CONFLICT")
            built[name] = klass
        return cls(MappingProxyType(built))

    def classify(self, name: str) -> OperationClass:
        return self.entries.get(name, OperationClass.UNCLASSIFIED)


def default_registry() -> OperationRegistry:
    """ILLUSTRATIVE registry; the real inventory is an S5b / operator item."""
    return OperationRegistry.from_entries((
        ("list_catalogs", OperationClass.READ),
        ("read_document", OperationClass.READ),
        ("export_report", OperationClass.READ),
        ("create_document", OperationClass.WRITE),
        ("update_document", OperationClass.WRITE),
        ("post_document", OperationClass.POST),
        ("delete_document", OperationClass.DELETE),
        ("reset_database", OperationClass.RESET),
        ("grant_role", OperationClass.ADMIN),
    ))


@dataclass(frozen=True, slots=True)
class CapturePlan:
    operations: tuple[str, ...]
    required_rights: frozenset[str]
    environment: Environment
    probes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    allowed: bool
    code: BoundaryCode
    coverage: tuple[tuple[str, OperationClass], ...] = ()
    denied_ops: tuple[str, ...] = ()
    disqualifying_rights: tuple[str, ...] = ()
    duplicate_ops: tuple[str, ...] = ()
    invalid_count: int = 0


def _deny(code: BoundaryCode, **kw: object) -> BoundaryDecision:
    return BoundaryDecision(False, code, **kw)  # type: ignore[arg-type]


def _classify(raw: object, registry: OperationRegistry) -> tuple[str, OperationClass | None]:
    name = canonical_operation(raw)
    if not name:
        return INVALID_PLACEHOLDER, None
    return name, registry.classify(name)


def evaluate(
    plan: object,
    registry: object,
    allowed_read_rights: object = DEFAULT_ALLOWED_READ_RIGHTS,
) -> BoundaryDecision:
    if (
        type(plan) is not CapturePlan
        or type(registry) is not OperationRegistry
        or type(allowed_read_rights) is not frozenset
        or type(plan.operations) is not tuple
        or type(plan.probes) is not tuple
        or type(plan.required_rights) is not frozenset
        or type(plan.environment) is not Environment
    ):
        return _deny(BoundaryCode.INVALID_INPUT)
    if not plan.operations:
        return _deny(BoundaryCode.EMPTY_PLAN)

    coverage: list[tuple[str, OperationClass]] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    denied: list[str] = []
    invalid = 0
    first_class_code: BoundaryCode | None = None
    for raw in plan.operations:
        name, klass = _classify(raw, registry)
        if klass is None:
            invalid += 1
            klass = OperationClass.UNCLASSIFIED
        if name in seen:
            if name not in duplicates:
                duplicates.append(name)
            continue
        seen.add(name)
        coverage.append((name, klass))
        if klass is not OperationClass.READ:
            denied.append(name)
            if first_class_code is None and name != INVALID_PLACEHOLDER:
                first_class_code = _CLASS_CODE[klass]

    allowed_rights = {clean_identity(r) for r in allowed_read_rights} - {""}
    bad_rights: list[str] = []
    for raw in sorted(plan.required_rights, key=repr):
        right = clean_identity(raw)
        if not right:
            bad_rights.append(INVALID_PLACEHOLDER)
        elif right in DISQUALIFYING_RIGHTS or right not in allowed_rights:
            bad_rights.append(right)

    probe_code = (
        BoundaryCode.PROBE_DENIED_IN_PROD
        if plan.environment is Environment.PROD
        else BoundaryCode.PROBE_DENIED
    )
    probe_denied = False
    for raw in plan.probes:
        name, klass = _classify(raw, registry)
        if klass is not OperationClass.READ:
            probe_denied = True
            if name not in denied:
                denied.append(name)

    if invalid:
        code = BoundaryCode.OPERATION_NAME_INVALID
    elif first_class_code is not None:
        code = first_class_code
    elif bad_rights:
        code = BoundaryCode.RIGHTS_DISQUALIFY
    elif probe_denied:
        code = probe_code
    else:
        code = BoundaryCode.ALLOWED
    return BoundaryDecision(
        code is BoundaryCode.ALLOWED, code, tuple(coverage), tuple(denied),
        tuple(bad_rights), tuple(duplicates), invalid,
    )
