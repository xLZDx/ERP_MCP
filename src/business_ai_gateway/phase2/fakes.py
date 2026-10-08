"""In-memory fakes of the Phase 2 living-registry ports (see ports.py).

``InMemoryLiving`` reproduces the observable behaviour and the error codes of db/phase2/001-003:
argument validation order, fences, lease/expiry/backoff, page-replay digests, outbox claim
generations, head CAS and the independent-approver / attestation rules. The SQL functions are the
source of truth: when they disagree with this file, this file is wrong.

Determinism: every time reading goes through the injected ``FakeClock`` (no wall clock); the fake
never generates ids or random values - callers supply every id.

Atomicity: every scoped call runs on a snapshot of the state that is restored when the call
raises, exactly like a SQL transaction that aborts (for example ``acquire_job`` rolls back the reap
it did before raising ``JOB_UNAVAILABLE``).

Not modelled (out of scope of this gate): scope-epoch bumps / suspended sources, row-level security
between tenants, company scoping, the settled-horizon race with a concurrent in-flight ingest,
session_user checks (the SQL skips them for a superuser session), floats inside hashed events.
"""
from __future__ import annotations

import copy
import functools
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .ports import (
    AcceptanceView,
    CommitResult,
    CursorView,
    EffectiveRow,
    EventKind,
    HeadView,
    JobView,
    KnownRow,
    Observation,
    OutboxRow,
    PortError,
    Scope,
    event_digest,
    jsonb_text,
    page_digest,
)
from .ports import evidence_digest as _evidence_digest

_DIGEST = re.compile(r"[a-f0-9]{64}")
_KINDS = frozenset(k.value for k in EventKind)
WORKER, READER, PROMOTER, PUBLISHER, OWNER = (
    "living_worker", "living_reader", "living_promoter", "living_publisher", "living_owner")
_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)
DEFAULT_SCOPE = Scope("A", "s1")


class FakeClock:
    """Deterministic clock. Every read advances by ``tick`` so two reads never collide."""

    def __init__(self, start: datetime | None = None, tick: timedelta = timedelta(microseconds=1)):
        self._t = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._tick = tick

    def now(self) -> datetime:
        value = self._t
        self._t += self._tick
        return value

    def advance(self, seconds: float) -> None:
        self._t += timedelta(seconds=seconds)


def _fail(code: str, detail: str = ""):
    raise PortError(code, detail)


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _text(value: object) -> str:
    return "" if value is None else value if isinstance(value, str) else jsonb_text(value)


@dataclass
class _Job:
    job_id: UUID
    kind: str
    request_digest: str
    key: str
    scope_epoch: int
    state: str = "PENDING"
    lease_owner: str | None = None
    lease_until: datetime | None = None
    fence: int = 0
    attempt: int = 0
    max_attempts: int = 5
    next_run_at: datetime | None = None
    last_error: str | None = None
    payload: dict = field(default_factory=dict)


@dataclass
class _Cursor:
    value: str
    scope_epoch: int
    version: int = 0
    last_page_digest: str | None = None


@dataclass
class _Outbox:
    seq: int
    connection_id: str
    event_id: str
    event_digest: str
    content: dict
    status: str = "PENDING"
    attempts: int = 0
    lease_owner: str | None = None
    lease_until: datetime | None = None
    claim_generation: int = 0


@dataclass
class _Att:
    attestation_id: UUID
    revision_id: UUID
    proposer: str
    observer: str
    evidence_ref: str
    evidence_digest: str
    decision: str
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass
class _Source:
    epoch: int = 0
    obs: list = field(default_factory=list)            # list[(Observation, provenance dict)]
    jobs: dict = field(default_factory=dict)           # job_id -> _Job
    cursors: dict = field(default_factory=dict)        # connection_id -> _Cursor
    outbox: dict = field(default_factory=dict)         # (connection_id, event_id) -> _Outbox
    heads: dict = field(default_factory=dict)          # model_key -> [revision_id | None, version]
    atts: dict = field(default_factory=dict)           # attestation_id -> _Att
    acceptances: dict = field(default_factory=dict)    # acceptance_id -> AcceptanceView
    trusted: dict = field(default_factory=dict)        # role -> (active, expires_at)


@dataclass
class _State:
    sources: dict = field(default_factory=dict)        # Scope -> _Source
    roles: dict = field(default_factory=dict)          # role -> set of roles it is a member of
    role_scope: set = field(default_factory=set)       # {(role, Scope)}
    ingest_seq: int = 0
    outbox_seq: int = 0


def _op(*grants: str):
    """Scoped call: enter scope (set_scope), check EXECUTE rights, run atomically."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(self, actor, scope, *args, **kwargs):
            snapshot = copy.deepcopy(self._st)
            try:
                src = self._enter(actor, scope, grants)
                return fn(self, actor, scope, src, *args, **kwargs)
            except Exception:
                self._st = snapshot
                raise
        return wrapper
    return deco


class InMemoryLiving:
    """One object implementing LedgerPort, JobQueuePort, CursorOutboxPort and HeadAttestationPort."""

    def __init__(self, clock: FakeClock | None = None, *, seed: bool = True):
        self.clock = clock or FakeClock()
        self._st = _State()
        if seed:
            self.seed_basic()

    # ------------------------------------------------------------------ directory / seed
    def seed_basic(self, scope: Scope = DEFAULT_SCOPE) -> None:
        """Mirror of tests/phase2/_pg_harness.seed_basic for one scope."""
        for role in (OWNER, WORKER, READER, PROMOTER, PUBLISHER):
            self._st.roles.setdefault(role, set())
            if role != OWNER:
                self._st.role_scope.add((role, scope))
        self._st.sources.setdefault(scope, _Source())
        self._st.sources[scope].trusted[WORKER] = (True, _FUTURE)

    def _member(self, who: str, role: str) -> bool:
        if who == role:
            return who in self._st.roles
        seen, todo = set(), [who]
        while todo:
            cur = todo.pop()
            for parent in self._st.roles.get(cur, ()):
                if parent == role:
                    return True
                if parent not in seen:
                    seen.add(parent)
                    todo.append(parent)
        return False

    def _enter(self, actor: str, scope: Scope, grants: tuple[str, ...]) -> _Source:
        src = self._st.sources.get(scope)
        if src is None or not any(sc == scope and self._member(actor, r)
                                  for r, sc in self._st.role_scope):
            _fail("SCOPE_NOT_GRANTED")
        if grants and not any(self._member(actor, g) for g in grants):
            _fail("PERMISSION_DENIED")
        return src

    async def define_actor(self, name: str, member_of: tuple[str, ...]) -> None:
        for parent in member_of:
            if parent not in self._st.roles:
                raise KeyError(parent)
        self._st.roles.setdefault(name, set()).update(member_of)

    async def now(self) -> datetime:
        return self.clock.now()

    async def scope_epoch(self, scope: Scope) -> int:
        return self._st.sources[scope].epoch

    # ------------------------------------------------------------------ ledger
    @_op(WORKER)
    def ingest_observation(self, actor, scope, src, observation_id, object_id, revision_id, kind,
                           digest, source_effective_at, observed_at, supersedes=None,
                           provenance=None):
        provenance = {} if provenance is None else provenance
        if (observation_id is None or object_id is None or object_id == "" or revision_id is None
                or kind is None or observed_at is None):
            _fail("INVALID_OBSERVATION")
        for _o, _p in src.obs:
            if _o.revision_id == revision_id:
                ex, ex_prov = _o, _p
                break
        else:
            ex = ex_prov = None
        if ex is not None:
            if ex.digest != digest:
                _fail("CONFLICTING_DIGEST")
            if ex.object_id != object_id or ex.kind != kind:
                _fail("REVISION_REUSED")
            if (ex.source_effective_at != source_effective_at or ex.observed_at != observed_at
                    or ex.supersedes != supersedes or ex_prov != provenance):
                _fail("CONFLICTING_OBSERVATION")
            return ex.observation_id
        recorded_at = self.clock.now()
        if supersedes is not None:
            parent = next((o for o, _ in src.obs if o.observation_id == supersedes), None)
            if parent is None or parent.object_id != object_id:
                _fail("SUPERSEDES_OBJECT_MISMATCH")
        if (kind not in _KINDS or observed_at > recorded_at
                or (kind == "OBSERVED" and not _is_digest(digest))
                or len(jsonb_text(provenance).encode("utf-8")) > 65536):
            _fail("CHECK_VIOLATION")
        if any(o.observation_id == observation_id for o, _ in src.obs):
            _fail("UNIQUE_VIOLATION")
        self._st.ingest_seq += 1
        src.obs.append((Observation(
            observation_id, object_id, revision_id, kind, digest, source_effective_at, observed_at,
            recorded_at, self._st.ingest_seq, supersedes), copy.deepcopy(provenance)))
        return observation_id

    def _known(self, src: _Source, k: datetime) -> list[Observation]:
        if k > self.clock.now():
            _fail("KNOWLEDGE_HORIZON_NOT_SETTLED")
        return [o for o, _ in src.obs if o.recorded_at <= k]

    @_op(WORKER, READER, PROMOTER)
    def as_known_at(self, actor, scope, src, k):
        known = self._known(src, k)
        out = []
        for obj in sorted({o.object_id for o in known}):
            rows = sorted((o for o in known if o.object_id == obj), key=lambda o: o.ingest_seq)
            latest = rows[-1]
            observed = [o for o in rows if o.kind == "OBSERVED"]
            head = observed[-1] if observed else latest
            revoked = any(o.kind == "ATTESTATION_REVOKED" and o.ingest_seq > head.ingest_seq
                          for o in rows)
            out.append(KnownRow(head, latest.kind == "OBSERVED", latest.kind, revoked))
        return tuple(out)

    @_op(WORKER, READER, PROMOTER)
    def as_effective_at(self, actor, scope, src, valid_at, k):
        known = self._known(src, k)
        out = []
        for obj in sorted({o.object_id for o in known}):
            rows = [o for o in known if o.object_id == obj]
            dated = [o for o in rows if o.kind == "OBSERVED" and o.source_effective_at is not None
                     and o.source_effective_at <= valid_at]
            undated = [o for o in rows if o.kind == "OBSERVED" and o.source_effective_at is None]
            picked = []
            if dated:
                picked.append((max(dated, key=lambda o: (o.source_effective_at, o.ingest_seq)),
                               False))
            if undated:
                picked.append((max(undated, key=lambda o: o.ingest_seq), True))
            for o, unknown in picked:
                revoked = any(r.kind == "ATTESTATION_REVOKED" and r.ingest_seq > o.ingest_seq
                              for r in rows)
                out.append(EffectiveRow(o, unknown, revoked))
        return tuple(out)

    # ------------------------------------------------------------------ jobs
    @staticmethod
    def _view(j: _Job) -> JobView:
        return JobView(j.job_id, j.state, j.lease_owner, j.lease_until, j.fence, j.attempt,
                       j.max_attempts, j.next_run_at, j.last_error, j.scope_epoch)

    def _reap(self, src: _Source, now: datetime) -> int:
        n = 0
        for j in src.jobs.values():
            if j.state == "RUNNING" and j.lease_until <= now:
                j.state = "FAILED" if j.attempt >= j.max_attempts else "PENDING"
                j.lease_owner = j.lease_until = None
                j.last_error = "LEASE_EXPIRED"
                j.next_run_at = now + timedelta(seconds=min(300, 2 ** min(j.attempt, 8)))
                n += 1
        return n

    @_op(WORKER)
    def enqueue_job(self, actor, scope, src, job_id, job_kind, request_digest, idempotency_key,
                    payload=None):
        payload = {} if payload is None else payload
        if (job_id is None or not job_kind or not idempotency_key
                or not _is_digest(request_digest)):
            _fail("INVALID_JOB")
        ex = next((j for j in src.jobs.values() if j.key == idempotency_key), None)
        if ex is not None:
            if ex.request_digest != request_digest:
                _fail("IDEMPOTENCY_CONFLICT")
            if ex.scope_epoch != src.epoch:
                _fail("SCOPE_REVOKED")
            return ex.job_id
        if job_id in src.jobs:
            _fail("UNIQUE_VIOLATION")
        if len(jsonb_text(payload).encode("utf-8")) > 65536:
            _fail("CHECK_VIOLATION")
        src.jobs[job_id] = _Job(job_id, job_kind, request_digest, idempotency_key, src.epoch,
                                next_run_at=self.clock.now(), payload=copy.deepcopy(payload))
        return job_id

    @_op(WORKER)
    def reap_expired_jobs(self, actor, scope, src):
        return self._reap(src, self.clock.now())

    @_op(WORKER)
    def acquire_job(self, actor, scope, src, job_id, worker, lease_seconds):
        if (job_id is None or not worker or lease_seconds is None
                or not 1 <= lease_seconds <= 300):
            _fail("INVALID_LEASE")
        now = self.clock.now()
        self._reap(src, now)
        if any(j.state == "RUNNING" for j in src.jobs.values()):
            _fail("JOB_UNAVAILABLE")
        j = src.jobs.get(job_id)
        if (j is None or j.state != "PENDING" or j.scope_epoch != src.epoch
                or j.attempt >= j.max_attempts or j.next_run_at > now):
            if j is not None and j.scope_epoch != src.epoch:
                _fail("SCOPE_REVOKED")
            _fail("JOB_UNAVAILABLE")
        j.state, j.lease_owner = "RUNNING", worker
        j.lease_until = now + timedelta(seconds=lease_seconds)
        j.fence += 1
        j.attempt += 1
        return j.fence

    def _live(self, src: _Source, job_id, worker, fence, now) -> _Job | None:
        j = src.jobs.get(job_id)
        if (j is not None and j.state == "RUNNING" and j.lease_owner == worker
                and j.fence == fence and j.lease_until > now and j.scope_epoch == src.epoch):
            return j
        return None

    @_op(WORKER)
    def renew_lease(self, actor, scope, src, job_id, worker, fence, lease_seconds):
        if (job_id is None or not worker or fence is None or lease_seconds is None
                or not 1 <= lease_seconds <= 300):
            _fail("INVALID_LEASE")
        now = self.clock.now()
        j = self._live(src, job_id, worker, fence, now)
        if j is None:
            _fail("STALE_JOB_FENCE")
        j.lease_until = now + timedelta(seconds=lease_seconds)
        return j.lease_until

    @_op(WORKER)
    def finish_job(self, actor, scope, src, job_id, worker, fence, completed_state, error=None):
        if (job_id is None or worker is None or fence is None or completed_state is None
                or completed_state not in ("SUCCEEDED", "FAILED", "CANCELLED")):
            _fail("INVALID_TERMINAL_STATE")
        j = self._live(src, job_id, worker, fence, self.clock.now())
        if j is None:
            _fail("STALE_JOB_FENCE")
        j.state, j.lease_owner, j.lease_until = completed_state, None, None
        j.last_error = None if completed_state == "SUCCEEDED" else error

    @_op(WORKER)
    def get_job(self, actor, scope, src, job_id):
        j = src.jobs.get(job_id)
        return None if j is None else self._view(j)

    # ------------------------------------------------------------------ cursor + outbox
    @_op(WORKER)
    def create_cursor(self, actor, scope, src, connection_id, initial_cursor):
        if not connection_id or initial_cursor is None:
            _fail("INVALID_ARGUMENT")
        cur = src.cursors.setdefault(connection_id, _Cursor(initial_cursor, src.epoch))
        return cur.version

    @_op(WORKER)
    def get_cursor(self, actor, scope, src, connection_id):
        c = src.cursors.get(connection_id)
        return None if c is None else CursorView(connection_id, c.value, c.version, c.scope_epoch,
                                                 c.last_page_digest)

    @_op(WORKER)
    def commit_cursor_page(self, actor, scope, src, connection_id, job_id, worker, fence,
                           prior_cursor, prior_version, expected_epoch, new_cursor, events):
        if (not connection_id or job_id is None or worker is None or fence is None
                or prior_cursor is None or prior_version is None or expected_epoch is None):
            _fail("INVALID_ARGUMENT")
        if (not new_cursor or not isinstance(events, list) or len(events) > 1000
                or len(jsonb_text(events).encode("utf-8")) > 4194304):
            _fail("INVALID_CURSOR_BATCH")
        for item in events:
            if (not isinstance(item, dict) or _text(item.get("event_id")) == ""
                    or len(jsonb_text(item).encode("utf-8")) > 262144
                    or not _is_digest(item.get("digest"))
                    or item["digest"] != event_digest(item)):
                _fail("INVALID_OUTBOX_EVENT")
        digest = page_digest(prior_cursor, new_cursor, events)
        if src.epoch != expected_epoch:
            _fail("SCOPE_REVOKED")
        j = src.jobs.get(job_id)
        if j is None:
            _fail("STALE_JOB_FENCE")
        if j.scope_epoch != src.epoch:
            _fail("SCOPE_REVOKED")
        if (j.state != "RUNNING" or j.lease_owner != worker or j.fence != fence
                or j.lease_until is None or j.lease_until <= self.clock.now()):
            _fail("STALE_JOB_FENCE")
        cur = src.cursors.get(connection_id)
        if cur is None:
            _fail("CURSOR_NOT_FOUND")
        if cur.scope_epoch != expected_epoch:
            _fail("SCOPE_REVOKED")
        if cur.value == new_cursor and cur.version == prior_version + 1:
            if cur.last_page_digest != digest:
                _fail("CONFLICTING_PAGE_REPLAY")
            return CommitResult(cur.version, True)
        if cur.value != prior_cursor or cur.version != prior_version:
            _fail("STALE_CURSOR_OR_SCOPE")
        cur.value, cur.version, cur.last_page_digest = new_cursor, cur.version + 1, digest
        for item in events:
            eid, edigest = _text(item["event_id"]), event_digest(item)
            ex = src.outbox.get((connection_id, eid))
            if ex is None:
                self._st.outbox_seq += 1
                src.outbox[(connection_id, eid)] = _Outbox(
                    self._st.outbox_seq, connection_id, eid, edigest, copy.deepcopy(item))
            elif ex.event_digest != edigest or ex.content != item:
                _fail("CONFLICTING_EVENT_DIGEST")
        return CommitResult(cur.version, False)

    @staticmethod
    def _ob_view(o: _Outbox) -> OutboxRow:
        return OutboxRow(o.seq, o.connection_id, o.event_id, o.event_digest,
                         copy.deepcopy(o.content), o.status, o.attempts, o.lease_owner,
                         o.lease_until, o.claim_generation)

    @_op(PUBLISHER)
    def claim_outbox(self, actor, scope, src, limit, lease_seconds, max_attempts=5):
        if (not actor or limit is None or not 1 <= limit <= 1000 or lease_seconds is None
                or not 1 <= lease_seconds <= 300 or max_attempts is None
                or not 1 <= max_attempts <= 20):
            _fail("INVALID_ARGUMENT")
        now = self.clock.now()
        rows = sorted(src.outbox.values(), key=lambda o: o.seq)
        for o in rows:
            if (o.status == "PENDING" and o.attempts >= max_attempts
                    and (o.lease_until is None or o.lease_until <= now)):
                o.status, o.lease_owner, o.lease_until = "FAILED", None, None
        claimed = [o for o in rows if o.status == "PENDING" and o.attempts < max_attempts
                   and (o.lease_until is None or o.lease_until <= now)][:limit]
        for o in claimed:
            o.attempts += 1
            o.lease_owner = actor
            o.claim_generation += 1
            o.lease_until = now + timedelta(seconds=lease_seconds)
        return tuple(self._ob_view(o) for o in claimed)

    @_op(PUBLISHER)
    def finish_outbox(self, actor, scope, src, connection_id, event_id, generation, delivered,
                      max_attempts=5):
        if (connection_id is None or event_id is None or generation is None or delivered is None
                or max_attempts is None or max_attempts < 1):
            _fail("INVALID_ARGUMENT")
        o = src.outbox.get((connection_id, event_id))
        if o is None:
            _fail("OUTBOX_EVENT_NOT_FOUND")
        if o.status != "PENDING":
            _fail("OUTBOX_INVALID_TRANSITION")
        if (o.lease_owner != actor or o.claim_generation != generation or o.lease_until is None
                or o.lease_until <= self.clock.now()):
            _fail("STALE_OUTBOX_LEASE")
        o.lease_owner = o.lease_until = None
        o.status = ("DELIVERED" if delivered else
                    "FAILED" if o.attempts >= max_attempts else "PENDING")

    @_op(WORKER)
    def list_outbox(self, actor, scope, src):
        return tuple(self._ob_view(o) for o in sorted(src.outbox.values(), key=lambda o: o.seq))

    # ------------------------------------------------------------------ heads + attestations
    def _trusted(self, src: _Source, who: str | None) -> bool:
        if not who or who not in self._st.roles:
            return False
        now = self.clock.now()
        return any(active and expires > now and role in self._st.roles
                   and self._member(who, role) for role, (active, expires) in src.trusted.items())

    async def set_trusted_reviewer(self, role, scope, active, expires_at) -> None:
        if not role or scope is None or active is None or expires_at is None:
            _fail("INVALID_ARGUMENT")
        if role not in self._st.roles:
            _fail("ROLE_NOT_FOUND")
        if scope not in self._st.sources:
            _fail("SOURCE_NOT_FOUND")
        self._st.sources[scope].trusted[role] = (active, expires_at)

    @_op(PROMOTER)
    def create_head(self, actor, scope, src, model_key):
        if not model_key:
            _fail("INVALID_ARGUMENT")
        return src.heads.setdefault(model_key, [None, 0])[1]

    @_op(WORKER, READER, PROMOTER)
    def get_head(self, actor, scope, src, model_key):
        h = src.heads.get(model_key)
        return None if h is None else HeadView(model_key, h[0], h[1])

    @_op(WORKER, READER, PROMOTER)
    def list_acceptances(self, actor, scope, src):
        return tuple(sorted(src.acceptances.values(),
                            key=lambda a: (a.model_key, a.to_version)))

    @_op(WORKER)
    def record_attestation(self, actor, scope, src, attestation_id, revision_id, proposer,
                           evidence_ref, evidence_digest, decision, expires_at):
        if (attestation_id is None or revision_id is None or not proposer or not evidence_ref
                or expires_at is None or not _is_digest(evidence_digest)
                or decision not in ("APPROVE", "REJECT")):
            _fail("INVALID_ARGUMENT")
        if not self._trusted(src, actor):
            _fail("REVIEWER_NOT_TRUSTED")
        rev = next((o for o, _ in src.obs if o.revision_id == revision_id), None)
        if rev is None or rev.kind != "OBSERVED":
            _fail("REVISION_NOT_OBSERVED")
        if evidence_digest != _evidence_digest(rev.digest, evidence_ref):
            _fail("EVIDENCE_DIGEST_MISMATCH")
        ex = src.atts.get(attestation_id)
        if ex is not None:
            if (ex.revision_id == revision_id and ex.proposer == proposer and ex.observer == actor
                    and ex.evidence_ref == evidence_ref and ex.evidence_digest == evidence_digest
                    and ex.decision == decision and ex.expires_at == expires_at):
                return attestation_id
            _fail("CONFLICTING_ATTESTATION")
        if expires_at <= self.clock.now():
            _fail("EVIDENCE_EXPIRED")
        if any(a.revision_id == revision_id and a.evidence_ref == evidence_ref
               for a in src.atts.values()):
            _fail("CONFLICTING_ATTESTATION")
        src.atts[attestation_id] = _Att(attestation_id, revision_id, proposer, actor, evidence_ref,
                                        evidence_digest, decision, expires_at)
        return attestation_id

    @_op(WORKER, PROMOTER)
    def revoke_attestation(self, actor, scope, src, attestation_id):
        if attestation_id is None:
            _fail("INVALID_ARGUMENT")
        att = src.atts.get(attestation_id)
        if att is None:
            _fail("EVIDENCE_NOT_FOUND")
        if actor != att.observer and not self._member(actor, PROMOTER):
            _fail("NOT_AUTHORIZED")
        if att.revoked_at is None:
            att.revoked_at = self.clock.now()
        return att.revoked_at

    def _not_independent(self, approver: str, obs: str, prop: str) -> bool:
        if approver == obs or approver == prop:
            return True
        return any(r in self._st.roles and (self._member(approver, r) or self._member(r, approver))
                   for r in (obs, prop))

    @_op(PROMOTER)
    def promote_head(self, actor, scope, src, model_key, expected_version, new_revision,
                     acceptance_id, evidence_ref):
        if (not actor or not evidence_ref or new_revision is None or acceptance_id is None
                or expected_version is None or model_key is None):
            _fail("INDEPENDENT_APPROVAL_REQUIRED")
        if not self._member(actor, PROMOTER):
            _fail("NOT_A_PROMOTER")
        ev = src.acceptances.get(acceptance_id)
        if ev is not None:
            if (ev.model_key == model_key and ev.from_version == expected_version
                    and ev.accepted_revision == new_revision and ev.approver_subject == actor
                    and ev.independent_evidence_ref == evidence_ref):
                return ev.to_version
            _fail("ACCEPTANCE_ID_REUSED")
        if self._member(actor, WORKER):
            _fail("APPROVER_NOT_INDEPENDENT")
        rev = next((o for o, _ in src.obs if o.revision_id == new_revision), None)
        if rev is None or rev.kind != "OBSERVED":
            _fail("REVISION_NOT_OBSERVED")
        att = next((a for a in src.atts.values()
                    if a.revision_id == new_revision and a.evidence_ref == evidence_ref), None)
        if att is None:
            _fail("EVIDENCE_NOT_FOUND")
        if self._not_independent(actor, att.observer, att.proposer):
            _fail("APPROVER_NOT_INDEPENDENT")
        if att.decision != "APPROVE":
            _fail("EVIDENCE_NOT_APPROVED")
        if att.revoked_at is not None:
            _fail("EVIDENCE_REVOKED")
        if att.expires_at <= self.clock.now():
            _fail("EVIDENCE_EXPIRED")
        if att.evidence_digest != _evidence_digest(rev.digest, evidence_ref):
            _fail("EVIDENCE_DIGEST_MISMATCH")
        if not self._trusted(src, att.observer):
            _fail("REVIEWER_NOT_TRUSTED")
        head = src.heads.get(model_key)
        if head is None or head[1] != expected_version:
            _fail("STALE_ACCEPTED_HEAD")
        head[0], head[1] = new_revision, head[1] + 1
        src.acceptances[acceptance_id] = AcceptanceView(
            acceptance_id, model_key, expected_version, head[1], new_revision, actor, evidence_ref)
        return head[1]
