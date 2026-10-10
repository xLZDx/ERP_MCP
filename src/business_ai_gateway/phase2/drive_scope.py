"""Phase 2 (S7/E1) Drive least-privilege scope evaluator and corpus membership (offline, pure).

Two independent jobs, both fail closed and neither ever raises on hostile input:

1. ``evaluate_scopes`` maps OAuth scope NAMES (plain allow-listed strings, never URLs, never used to
   perform a call) to a claim: ``NARROW_FILE_SCOPE`` / ``READONLY_BROAD`` / ``BROAD`` (the broadest
   name wins). A broad claim is NEVER folder isolation: its isolation is ``APPLICATION_FILTER_ONLY``
   and it may proceed only with the explicit ``BROAD_ACCEPTED`` risk label (TC105). A narrow per-file
   grant is reported as ``FILE_GRANT_ONLY``: it does not claim folder isolation either. The value
   ``Isolation.FOLDER_ISOLATED`` exists only so a wrong label can be expressed and refused.
2. Corpus membership: a file is in scope only when its resolved parent chain (``DrivePort.get_file_meta``)
   reaches a declared root folder id within a bounded depth and call budget. Cycles terminate,
   unresolved parents give ``NOT_IN_SCOPE`` (never an exception), a shortcut is never a membership
   proof, a trashed file is not in scope and the namespace/drive id must match the corpus declaration.

``NEW_CHILD_ACCESS`` (PROVEN / NOT_PROVEN / DENIED) and scoped access (TC103) are derived only from an
observation made through the port (in tests: a scripted fake), never assumed.

Outward results carry fixed enum codes only; no caller value is echoed. Drive ids are opaque and
preserved byte-exact (validated with ``drive_port.is_valid_opaque_id``, never repaired).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .drive_cursor import DriveCorpus
from .drive_port import (
    MAX_CORPUS_ROOTS,
    DriveErrorCode,
    DrivePort,
    DrivePortError,
    DrivePortIdentity,
    FileMeta,
    is_sound_file_meta,
    is_sound_identity,
    is_valid_opaque_id,
    is_valid_scope_epoch,
)

__all__ = [
    "BROAD_ACCEPTED",
    "MAX_CORPUS_ROOTS",
    "SCOPE_ALLOW_LIST",
    "AccessProof",
    "CorpusDeclaration",
    "Isolation",
    "MembershipCode",
    "MembershipResult",
    "MembershipStatus",
    "NewChildCode",
    "NewChildObservation",
    "ProofBasis",
    "ScopeClaim",
    "ScopeCode",
    "ScopeEvaluation",
    "ScopedAccessCode",
    "ScopedAccessProof",
    "check_isolation_label",
    "declaration_from_drive_corpus",
    "evaluate_scopes",
    "observe_new_child_access",
    "prove_scoped_read",
    "resolve_membership",
]

BROAD_ACCEPTED = "BROAD_ACCEPTED"
MAX_SCOPE_NAMES = 16
MAX_SCOPE_NAME_CHARS = 64
# MAX_CORPUS_ROOTS (1000) is the one shared limit, defined in drive_port and re-exported here
DEFAULT_MAX_DEPTH = 32
DEFAULT_MAX_CALLS = 128
_MAX_DEPTH_CAP = 64
_MAX_CALLS_CAP = 1024
_SCOPE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz._")


class ScopeClaim(StrEnum):
    NARROW_FILE_SCOPE = "NARROW_FILE_SCOPE"
    READONLY_BROAD = "READONLY_BROAD"
    BROAD = "BROAD"


class Isolation(StrEnum):
    FILE_GRANT_ONLY = "FILE_GRANT_ONLY"
    APPLICATION_FILTER_ONLY = "APPLICATION_FILTER_ONLY"
    FOLDER_ISOLATED = "FOLDER_ISOLATED"  # never produced by the evaluator; only a refused label


class ScopeCode(StrEnum):
    OK = "OK"
    SCOPE_NAMES_INVALID = "SCOPE_NAMES_INVALID"
    SCOPE_NAME_INVALID = "SCOPE_NAME_INVALID"
    SCOPE_UNKNOWN = "SCOPE_UNKNOWN"
    SCOPE_SET_EMPTY = "SCOPE_SET_EMPTY"
    SCOPE_SET_TOO_LARGE = "SCOPE_SET_TOO_LARGE"
    RISK_LABELS_INVALID = "RISK_LABELS_INVALID"
    RISK_LABEL_UNKNOWN = "RISK_LABEL_UNKNOWN"
    BROAD_REQUIRES_RISK_LABEL = "BROAD_REQUIRES_RISK_LABEL"
    ISOLATION_LABEL_REFUSED = "ISOLATION_LABEL_REFUSED"
    INPUT_INVALID = "INPUT_INVALID"


# name -> claim. Plain names, not URLs: a real Google scope URL is refused as SCOPE_NAME_INVALID.
SCOPE_ALLOW_LIST: MappingProxyType[str, ScopeClaim] = MappingProxyType({
    "drive.file": ScopeClaim.NARROW_FILE_SCOPE,
    "drive.metadata.readonly": ScopeClaim.READONLY_BROAD,
    "drive.readonly": ScopeClaim.READONLY_BROAD,
    "drive": ScopeClaim.BROAD,
})
_RANK: MappingProxyType[ScopeClaim, int] = MappingProxyType(
    {ScopeClaim.NARROW_FILE_SCOPE: 0, ScopeClaim.READONLY_BROAD: 1, ScopeClaim.BROAD: 2}
)


@dataclass(frozen=True, slots=True)
class ScopeEvaluation:
    code: ScopeCode
    claim: ScopeClaim | None
    isolation: Isolation | None
    may_proceed: bool
    scopes: tuple[str, ...]


def _scope_refusal(code: ScopeCode) -> ScopeEvaluation:
    return ScopeEvaluation(code, None, None, False, ())


def evaluate_scopes(scope_names: object, risk_labels: object = ()) -> ScopeEvaluation:
    """Evaluate a requested/granted scope NAME set. Never raises; fixed codes only."""
    try:
        if type(scope_names) not in (tuple, list, frozenset, set):
            return _scope_refusal(ScopeCode.SCOPE_NAMES_INVALID)
        if len(scope_names) == 0:
            return _scope_refusal(ScopeCode.SCOPE_SET_EMPTY)
        if len(scope_names) > MAX_SCOPE_NAMES:
            return _scope_refusal(ScopeCode.SCOPE_SET_TOO_LARGE)
        names: set[str] = set()
        for name in scope_names:
            if (
                type(name) is not str
                or not 0 < len(name) <= MAX_SCOPE_NAME_CHARS
                or any(ch not in _SCOPE_CHARS for ch in name)
            ):
                return _scope_refusal(ScopeCode.SCOPE_NAME_INVALID)
            names.add(name)
        unknown = [n for n in names if n not in SCOPE_ALLOW_LIST]
        if unknown:
            return _scope_refusal(ScopeCode.SCOPE_UNKNOWN)
        if type(risk_labels) not in (tuple, list, frozenset, set) or len(risk_labels) > 8:
            return _scope_refusal(ScopeCode.RISK_LABELS_INVALID)
        for label in risk_labels:
            if type(label) is not str:
                return _scope_refusal(ScopeCode.RISK_LABELS_INVALID)
            if label != BROAD_ACCEPTED:
                return _scope_refusal(ScopeCode.RISK_LABEL_UNKNOWN)
        accepted = BROAD_ACCEPTED in risk_labels
        claim = max((SCOPE_ALLOW_LIST[n] for n in names), key=_RANK.__getitem__)
        ordered = tuple(sorted(names))
        if claim is ScopeClaim.NARROW_FILE_SCOPE:
            return ScopeEvaluation(ScopeCode.OK, claim, Isolation.FILE_GRANT_ONLY, True, ordered)
        if not accepted:
            return ScopeEvaluation(
                ScopeCode.BROAD_REQUIRES_RISK_LABEL, claim, Isolation.APPLICATION_FILTER_ONLY,
                False, ordered,
            )
        return ScopeEvaluation(
            ScopeCode.OK, claim, Isolation.APPLICATION_FILTER_ONLY, True, ordered
        )
    except Exception:  # noqa: BLE001 - hostile container (recursive, raising __iter__): fail closed
        return _scope_refusal(ScopeCode.INPUT_INVALID)


def check_isolation_label(evaluation: object, label: object) -> ScopeCode:
    """OK only when ``label`` is exactly the isolation the evaluation proved; a broad grant labelled
    ``FOLDER_ISOLATED`` (or anything else) is ``ISOLATION_LABEL_REFUSED``."""
    if (
        type(evaluation) is ScopeEvaluation
        and evaluation.isolation is not None
        and type(label) is Isolation
        and label is evaluation.isolation
        and label is not Isolation.FOLDER_ISOLATED
    ):
        return ScopeCode.OK
    return ScopeCode.ISOLATION_LABEL_REFUSED


# --- corpus -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusDeclaration:
    """Declared corpus: namespace (``account:<id>`` / ``drive:<id>``), optional shared-drive id and
    root folder ids. An empty ``root_folder_ids`` is constructible and proves nothing."""

    namespace: str
    drive_id: str | None
    root_folder_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        ns = self.namespace
        if (
            not is_valid_opaque_id(ns)
            or not any(ns.startswith(p) and len(ns) > len(p) for p in ("account:", "drive:"))
        ):
            raise ValueError("CORPUS_INVALID")
        if self.drive_id is not None and not is_valid_opaque_id(self.drive_id):
            raise ValueError("CORPUS_INVALID")
        roots = self.root_folder_ids
        if type(roots) is not tuple or len(roots) > MAX_CORPUS_ROOTS:
            raise ValueError("CORPUS_INVALID")
        if any(not is_valid_opaque_id(r) for r in roots) or len(set(roots)) != len(roots):
            raise ValueError("CORPUS_INVALID")


def _declaration_ok(corpus: object) -> bool:
    """True for a real, fully initialised ``CorpusDeclaration`` (an ``object.__new__`` shell is not)."""
    try:
        return (
            type(corpus) is CorpusDeclaration
            and type(corpus.namespace) is str  # type: ignore[attr-defined]
            and type(corpus.root_folder_ids) is tuple  # type: ignore[attr-defined]
            and (corpus.drive_id is None or type(corpus.drive_id) is str)  # type: ignore[attr-defined]
        )
    except Exception:  # noqa: BLE001 - unset slot / hostile object
        return False


def cursor_corpus_parts(corpus: object, identity: object) -> tuple[str | None, tuple[str, ...]]:
    """Read-only bridge from ``drive_cursor.DriveCorpus``: (drive_id, root ids) after checking that the
    corpus matches ``identity`` (``drive:<id>`` namespace <-> that drive id; ``account:<id>`` <-> no drive
    id, the same rule the baseline uses). Raises ``ValueError`` with a fixed code only:
    ``CORPUS_INVALID`` (wrong/forged object) or ``CORPUS_IDENTITY_MISMATCH``."""
    if not is_sound_identity(identity):
        raise ValueError("CORPUS_INVALID")
    try:
        if type(corpus) is not DriveCorpus:
            raise ValueError("CORPUS_INVALID")
        drive_id, roots = corpus.drive_id, corpus.root_folder_ids
        if (drive_id is not None and type(drive_id) is not str) or type(roots) is not tuple:
            raise ValueError("CORPUS_INVALID")
        expected = identity.namespace_id if identity.kind == "drive" else None  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - forged object: fixed code only
        raise ValueError("CORPUS_INVALID") from None
    if drive_id != expected:
        raise ValueError("CORPUS_IDENTITY_MISMATCH")
    return drive_id, roots


def declaration_from_drive_corpus(corpus: object, identity: object) -> CorpusDeclaration:
    """Build the ``CorpusDeclaration`` of a ``drive_cursor.DriveCorpus`` for ``identity`` (one declaration
    feeds ``resolve_membership`` and, via ``drive_membership.corpus_from_drive_corpus``, the checker)."""
    drive_id, roots = cursor_corpus_parts(corpus, identity)
    return CorpusDeclaration(identity.namespace, drive_id, roots)  # type: ignore[attr-defined]


class MembershipStatus(StrEnum):
    IN_SCOPE = "IN_SCOPE"
    NOT_IN_SCOPE = "NOT_IN_SCOPE"


class MembershipCode(StrEnum):
    IN_CORPUS = "IN_CORPUS"
    INPUT_INVALID = "INPUT_INVALID"
    EMPTY_CORPUS = "EMPTY_CORPUS"
    NAMESPACE_MISMATCH = "NAMESPACE_MISMATCH"
    FILE_UNRESOLVED = "FILE_UNRESOLVED"
    PARENT_UNRESOLVED = "PARENT_UNRESOLVED"
    OUTSIDE_CORPUS = "OUTSIDE_CORPUS"  # chain fully resolved and no declared root reached
    DEPTH_EXCEEDED = "DEPTH_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CYCLE = "CYCLE"
    SHORTCUT_NOT_PROOF = "SHORTCUT_NOT_PROOF"
    TRASHED = "TRASHED"
    PORT_REFUSED = "PORT_REFUSED"


@dataclass(frozen=True, slots=True)
class MembershipResult:
    status: MembershipStatus
    code: MembershipCode
    port_code: DriveErrorCode | None = None

    @property
    def in_scope(self) -> bool:
        return self.status is MembershipStatus.IN_SCOPE


def _out(code: MembershipCode, port_code: DriveErrorCode | None = None) -> MembershipResult:
    return MembershipResult(MembershipStatus.NOT_IN_SCOPE, code, port_code)


class _Abort(Exception):
    def __init__(self, result: MembershipResult) -> None:
        super().__init__(result.code.value)
        self.result = result


def graph_reaches(graph: dict[str, tuple[str, ...]], start: str, target: str) -> bool:
    """True when ``target`` is ``start`` or reachable from it through the already fetched parent edges."""
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


async def _fetch(
    port: DrivePort, identity: DrivePortIdentity, epoch: int, file_id: str, budget: list[int]
) -> FileMeta | None:
    """None = unresolved (NOT_FOUND / malformed answer); any other port refusal aborts."""
    if budget[0] <= 0:
        raise _Abort(_out(MembershipCode.BUDGET_EXCEEDED))
    budget[0] -= 1
    try:
        meta = await port.get_file_meta(identity, epoch, file_id)
    except DrivePortError as exc:
        if exc.code is DriveErrorCode.NOT_FOUND:
            return None
        raise _Abort(_out(MembershipCode.PORT_REFUSED, exc.code)) from None
    except Exception:  # noqa: BLE001 - unexpected port failure: fail closed, text dropped
        raise _Abort(_out(MembershipCode.PORT_REFUSED)) from None
    if not is_sound_file_meta(meta) or meta.file_id != file_id:
        return None
    return meta


async def resolve_membership(
    port: object,
    identity: object,
    scope_epoch: object,
    corpus: object,
    file_id: object,
    *,
    max_depth: object = DEFAULT_MAX_DEPTH,
    max_calls: object = DEFAULT_MAX_CALLS,
) -> MembershipResult:
    """Is ``file_id`` under a declared root? Bounded by ``max_depth`` parent hops and ``max_calls``
    port calls. Never raises (``asyncio.CancelledError`` still propagates)."""
    try:
        if (
            not is_sound_identity(identity)
            or not _declaration_ok(corpus)
            or not is_valid_scope_epoch(scope_epoch)
            or not is_valid_opaque_id(file_id)
            or type(max_depth) is not int
            or not 1 <= max_depth <= _MAX_DEPTH_CAP
            or type(max_calls) is not int
            or not 1 <= max_calls <= _MAX_CALLS_CAP
        ):
            return _out(MembershipCode.INPUT_INVALID)
        if not corpus.root_folder_ids:
            return _out(MembershipCode.EMPTY_CORPUS)
        if corpus.namespace != identity.namespace:
            return _out(MembershipCode.NAMESPACE_MISMATCH)
        return await _walk(port, identity, scope_epoch, corpus, file_id, max_depth, max_calls)
    except _Abort as abort:
        return abort.result
    except Exception:  # noqa: BLE001 - fail closed; never leak
        return _out(MembershipCode.PORT_REFUSED)


async def _walk(
    port: DrivePort, identity: DrivePortIdentity, epoch: int, corpus: CorpusDeclaration,
    file_id: str, max_depth: int, max_calls: int,
) -> MembershipResult:
    roots = frozenset(corpus.root_folder_ids)
    budget = [max_calls]
    leaf = await _fetch(port, identity, epoch, file_id, budget)
    if leaf is None:
        return _out(MembershipCode.FILE_UNRESOLVED)
    if leaf.drive_id != corpus.drive_id:
        return _out(MembershipCode.NAMESPACE_MISMATCH)
    if leaf.shortcut_target is not None:
        return _out(MembershipCode.SHORTCUT_NOT_PROOF)
    if leaf.trashed:
        return _out(MembershipCode.TRASHED)
    if file_id in roots:
        return MembershipResult(MembershipStatus.IN_SCOPE, MembershipCode.IN_CORPUS)
    visited = {file_id}
    graph: dict[str, tuple[str, ...]] = {file_id: leaf.parents}
    # (parent id, id of the child it was read from): the child is needed to tell a cycle from a diamond
    frontier: list[tuple[str, str]] = [(p, file_id) for p in dict.fromkeys(leaf.parents)]
    failure: MembershipCode | None = None
    for _ in range(max_depth):
        nxt: list[tuple[str, str]] = []
        # declared roots first: a root is an ancestor like any other and proves membership only when its
        # CURRENT metadata is readable, of the declared drive, not trashed and not a shortcut
        for parent, via in sorted(frontier, key=lambda pv: pv[0] not in roots):
            if parent in roots and parent not in visited:
                visited.add(parent)
                root = await _fetch(port, identity, epoch, parent, budget)
                if root is None:
                    failure = failure or MembershipCode.PARENT_UNRESOLVED
                elif root.drive_id != corpus.drive_id:
                    failure = failure or MembershipCode.NAMESPACE_MISMATCH
                elif root.shortcut_target is not None:
                    failure = failure or MembershipCode.SHORTCUT_NOT_PROOF
                elif root.trashed:
                    failure = failure or MembershipCode.TRASHED
                else:
                    return MembershipResult(MembershipStatus.IN_SCOPE, MembershipCode.IN_CORPUS)
                continue
            if parent in visited:
                # a shared ancestor (diamond) is simply already handled; only a parent that can reach
                # its own child through the fetched graph is a cycle
                if graph_reaches(graph, parent, via):
                    failure = failure or MembershipCode.CYCLE
                continue
            visited.add(parent)
            meta = await _fetch(port, identity, epoch, parent, budget)
            if meta is None:
                failure = failure or MembershipCode.PARENT_UNRESOLVED
            elif meta.drive_id != corpus.drive_id:
                failure = failure or MembershipCode.NAMESPACE_MISMATCH  # an ancestor of another drive
            elif meta.shortcut_target is not None:
                failure = failure or MembershipCode.SHORTCUT_NOT_PROOF
            elif meta.trashed:
                failure = failure or MembershipCode.TRASHED
            else:
                graph[parent] = meta.parents
                nxt.extend((p, parent) for p in dict.fromkeys(meta.parents))
        if not nxt:
            return _out(failure or MembershipCode.OUTSIDE_CORPUS)
        frontier = nxt
    return _out(MembershipCode.DEPTH_EXCEEDED)  # hop max_depth + 1 is never inspected


# --- scripted observations (TC103 / TC104) ------------------------------------------------------


class AccessProof(StrEnum):
    PROVEN = "PROVEN"
    NOT_PROVEN = "NOT_PROVEN"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class ProofBasis:
    scopes: tuple[str, ...]
    root_folder_ids: tuple[str, ...]
    observation_id: str


class ScopedAccessCode(StrEnum):
    """Fixed codes of a ``ScopedAccessProof``: the proof's own codes plus every non-proving membership code."""

    READ_IN_CORPUS = "READ_IN_CORPUS"
    OUT_OF_CORPUS = "OUT_OF_CORPUS"
    SCOPE_NOT_ACCEPTED = "SCOPE_NOT_ACCEPTED"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"
    INPUT_INVALID = "INPUT_INVALID"
    EMPTY_CORPUS = "EMPTY_CORPUS"
    NAMESPACE_MISMATCH = "NAMESPACE_MISMATCH"
    FILE_UNRESOLVED = "FILE_UNRESOLVED"
    PARENT_UNRESOLVED = "PARENT_UNRESOLVED"
    OUTSIDE_CORPUS = "OUTSIDE_CORPUS"
    DEPTH_EXCEEDED = "DEPTH_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CYCLE = "CYCLE"
    SHORTCUT_NOT_PROOF = "SHORTCUT_NOT_PROOF"
    TRASHED = "TRASHED"
    PORT_REFUSED = "PORT_REFUSED"


class NewChildCode(StrEnum):
    CHILD_READABLE = "CHILD_READABLE"
    CHILD_HIDDEN = "CHILD_HIDDEN"
    CHILD_FORBIDDEN = "CHILD_FORBIDDEN"  # 403 on the child's FILE metadata read (not a history 403)
    CHILD_OUTSIDE_CORPUS = "CHILD_OUTSIDE_CORPUS"
    SCOPE_NOT_ACCEPTED = "SCOPE_NOT_ACCEPTED"
    EMPTY_CORPUS = "EMPTY_CORPUS"
    INPUT_INVALID = "INPUT_INVALID"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"


@dataclass(frozen=True, slots=True)
class ScopedAccessProof:
    status: AccessProof
    code: ScopedAccessCode
    basis: ProofBasis | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not AccessProof or type(self.code) is not ScopedAccessCode:
            raise ValueError("PROOF_CODE_INVALID")


@dataclass(frozen=True, slots=True)
class NewChildObservation:
    """``NEW_CHILD_ACCESS`` verdict; ``code`` is a fixed ``NewChildCode``."""

    status: AccessProof
    code: NewChildCode
    basis: ProofBasis | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not AccessProof or type(self.code) is not NewChildCode:
            raise ValueError("PROOF_CODE_INVALID")


def _input_ok(identity: object, epoch: object, corpus: object, file_id: object, obs: object) -> bool:
    return (
        is_sound_identity(identity)
        and is_valid_scope_epoch(epoch)
        and _declaration_ok(corpus)
        and is_valid_opaque_id(file_id)
        and is_valid_opaque_id(obs)
    )


async def prove_scoped_read(
    port: object,
    identity: object,
    scope_epoch: object,
    corpus: object,
    file_id: object,
    scope_names: object,
    observation_id: object,
    risk_labels: object = (),
) -> ScopedAccessProof:
    """TC103: PROVEN only when the scope set is acceptable AND a read of ``file_id`` through the port
    succeeded AND the file resolves under a declared root. Out-of-corpus is DENIED; an empty corpus or
    an unresolved file proves nothing (NOT_PROVEN)."""
    try:
        if not _input_ok(identity, scope_epoch, corpus, file_id, observation_id):
            return ScopedAccessProof(AccessProof.NOT_PROVEN, ScopedAccessCode.INPUT_INVALID)
        evaluation = evaluate_scopes(scope_names, risk_labels)
        if not evaluation.may_proceed:
            return ScopedAccessProof(AccessProof.DENIED, ScopedAccessCode.SCOPE_NOT_ACCEPTED)
        if not corpus.root_folder_ids:  # type: ignore[union-attr]
            return ScopedAccessProof(AccessProof.NOT_PROVEN, ScopedAccessCode.EMPTY_CORPUS)
        member = await resolve_membership(port, identity, scope_epoch, corpus, file_id)
        if member.in_scope:
            basis = ProofBasis(evaluation.scopes, corpus.root_folder_ids, observation_id)  # type: ignore[union-attr,arg-type]
            return ScopedAccessProof(AccessProof.PROVEN, ScopedAccessCode.READ_IN_CORPUS, basis)
        if member.code in (
            MembershipCode.OUTSIDE_CORPUS,
            MembershipCode.NAMESPACE_MISMATCH,
            MembershipCode.SHORTCUT_NOT_PROOF,
        ):
            return ScopedAccessProof(AccessProof.DENIED, ScopedAccessCode.OUT_OF_CORPUS)
        return ScopedAccessProof(AccessProof.NOT_PROVEN, ScopedAccessCode(member.code.value))
    except Exception:  # noqa: BLE001
        return ScopedAccessProof(AccessProof.NOT_PROVEN, ScopedAccessCode.OBSERVATION_FAILED)


async def observe_new_child_access(
    port: object,
    identity: object,
    scope_epoch: object,
    corpus: object,
    child_file_id: object,
    scope_names: object,
    observation_id: object,
    risk_labels: object = (),
) -> NewChildObservation:
    """TC104: the caller names a child created AFTER the grant; the verdict comes only from reading it.
    Readable and under a declared root -> PROVEN. 403 -> DENIED. Not found (hidden or deleted: not
    distinguishable) or any other failure -> NOT_PROVEN. A child that cannot be shown to be inside the
    corpus never proves anything."""
    try:
        if not _input_ok(identity, scope_epoch, corpus, child_file_id, observation_id):
            return NewChildObservation(AccessProof.NOT_PROVEN, NewChildCode.INPUT_INVALID)
        evaluation = evaluate_scopes(scope_names, risk_labels)
        if not evaluation.may_proceed:
            return NewChildObservation(AccessProof.DENIED, NewChildCode.SCOPE_NOT_ACCEPTED)
        if not corpus.root_folder_ids:  # type: ignore[union-attr]
            return NewChildObservation(AccessProof.NOT_PROVEN, NewChildCode.EMPTY_CORPUS)
        member = await resolve_membership(port, identity, scope_epoch, corpus, child_file_id)
        if member.in_scope:
            basis = ProofBasis(evaluation.scopes, corpus.root_folder_ids, observation_id)  # type: ignore[union-attr,arg-type]
            return NewChildObservation(AccessProof.PROVEN, NewChildCode.CHILD_READABLE, basis)
        if member.code is MembershipCode.FILE_UNRESOLVED:
            return NewChildObservation(AccessProof.NOT_PROVEN, NewChildCode.CHILD_HIDDEN)
        if member.code is MembershipCode.PORT_REFUSED:
            if member.port_code is DriveErrorCode.FORBIDDEN_HISTORY:
                return NewChildObservation(AccessProof.DENIED, NewChildCode.CHILD_FORBIDDEN)
            return NewChildObservation(AccessProof.NOT_PROVEN, NewChildCode.OBSERVATION_FAILED)
        return NewChildObservation(AccessProof.NOT_PROVEN, NewChildCode.CHILD_OUTSIDE_CORPUS)
    except Exception:  # noqa: BLE001
        return NewChildObservation(AccessProof.NOT_PROVEN, NewChildCode.OBSERVATION_FAILED)
