"""S8/E3 TC123 + S6b lesson rows: a refusal is not bypassed by spelling, channel or alias.

No channel parameter exists in any decision signature and no free-form command field exists in any
request type (AST-checked below). Hostile input never raises out of a public function.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import jobs_api, safe_errors
from business_ai_gateway.phase2.fakes import FakeClock
from business_ai_gateway.phase2.jobs_api import (
    ApiContext,
    ApiDecision,
    CsrfGuard,
    FakeCapturePolicy,
    FakeJobDispatcher,
    FakeScopeEpochs,
    IdempotencyStore,
    JobKind,
    JobRequest,
    RefusalLog,
    RerunRequest,
    SessionRecord,
    decide_enqueue,
    decide_rerun,
    fake_csrf_token,
    read_job,
    read_result,
)
from business_ai_gateway.phase2.safe_errors import FakeCorrelationSource
from business_ai_gateway.phase2.side_effect_boundary import (
    OperationClass,
    OperationRegistry,
    default_registry,
)
from business_ai_gateway.phase2.workbench_types import (
    FakeEntitlements,
    FakeOwnership,
    ReasonCode,
    ViewerScope,
)

R = ReasonCode
START = datetime(2026, 1, 1, tzinfo=UTC)
DIGEST = "a" * 64
DENIED_BASES = ["post_document", "create_document", "update_document", "delete_document",
                "reset_database", "grant_role"]


class StrSub(str):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


class IntSub(int):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = int.__hash__


def _ctx(registry=None, refusals=None):
    dispatcher = FakeJobDispatcher()
    ownership, entitlements = FakeOwnership(), FakeEntitlements()
    entitlements.grant("T1", "alice", "C1")
    for kind, ref in (("source_id", "SRC-1"), ("comparison_key", "CK-1"), ("run_id", "run-1"),
                      ("snapshot_id", "SN-2")):
        ownership.add("T1", "C1", kind, ref)
    ctx = ApiContext(
        csrf=CsrfGuard(fake_csrf_token), scopes=FakeScopeEpochs({("T1", "C1"): 1}),
        registry=registry or default_registry(), refusals=refusals or RefusalLog(),
        idempotency=IdempotencyStore(256, 3600), dispatcher=dispatcher, clock=FakeClock(START),
        correlation=FakeCorrelationSource(), ownership=ownership, entitlements=entitlements,
        capture_policy=FakeCapturePolicy())
    return ctx, dispatcher


SESSION = SessionRecord("S1", "T1", "alice", START + timedelta(hours=1), DIGEST)
TOKEN = fake_csrf_token(SESSION)
_counter = [0]


def _submit(ctx, operation, kind=JobKind.RESCAN, params=(("source_id", "SRC-1"),)):
    _counter[0] += 1
    req = JobRequest(ViewerScope("T1", "C1", 1), "alice", kind, operation, params,
                     f"idem-key-{_counter[0]:06d}")
    return decide_enqueue(ctx, req, SESSION, TOKEN)


def _forge(cls, **fields):
    obj = object.__new__(cls)
    for name, value in fields.items():
        object.__setattr__(obj, name, value)
    return obj


# ============================ TC123: respelling / channel / alias ============================

def _variants(base: str) -> dict[str, str]:
    full = "".join(chr(ord(c) + 0xFEE0) if c.isalpha() else c for c in base)  # fullwidth letters
    return {
        "exact": base, "upper": base.upper(), "title": base.title(), "padded": f"  {base}  ",
        "nfkc-fullwidth": full, "mixed": base[:3].upper() + base[3:],
    }


def _invalid_variants(base: str) -> dict[str, str]:
    return {
        "zero-width": base[:4] + "\u200b" + base[4:], "bom": "﻿" + base, "nul": base + "\x00",
        "newline": base + "\n", "tab": "\t" + base, "soft-hyphen": base[:2] + "­" + base[2:],
        "cyrillic-o": base.replace("o", "о", 1),
        "channel-com": "com:" + base, "channel-dc": "dc." + base, "channel-http": "http/" + base,
        "channel-suffix": base + "@mcp", "alias-trunc": base[:-3], "alias-dashed": base.replace("_", "-"),
        "space-inside": base.replace("_", " "),
    }


@pytest.mark.parametrize("base", DENIED_BASES)
def test_refused_operation_stays_refused_for_every_canonical_respelling(base):
    ctx, dispatcher = _ctx()
    baseline = _submit(ctx, base)
    assert baseline.allowed is False and baseline.reason_code is R.OPERATION_DENIED
    for spelling in _variants(base).values():
        d = _submit(ctx, spelling)
        assert d.allowed is False and d.http_class == 403
        assert d.reason_code is R.OPERATION_DENIED  # the SAME fixed code
        assert d.ticket is None
    assert dispatcher.calls == ()
    assert ctx.idempotency.record_count() == 0


@pytest.mark.parametrize("base", DENIED_BASES)
def test_invalid_or_channel_labelled_spellings_are_refused_with_one_fixed_code(base):
    ctx, dispatcher = _ctx()
    for name, spelling in _invalid_variants(base).items():
        if spelling == base:
            continue  # the substitution did not apply to this base: not an invalid spelling
        d = _submit(ctx, spelling)
        assert d.allowed is False, name
        assert d.reason_code is R.OPERATION_UNCLASSIFIED, name  # one fixed code (plan decision 11)
        assert d.http_class == 403
    assert dispatcher.calls == ()
    assert ctx.idempotency.record_count() == 0


def test_unclassified_operation_is_denied_and_stays_so_under_respelling():
    ctx, dispatcher = _ctx()
    for spelling in ("mystery_op", " MYSTERY_OP ", "ｍｙｓｔｅｒｙ_ｏｐ", "my\u200bstery_op", ""):
        d = _submit(ctx, spelling)
        assert d.reason_code is R.OPERATION_UNCLASSIFIED and d.allowed is False
    assert dispatcher.calls == ()


@pytest.mark.parametrize("klass,base", [
    (OperationClass.WRITE, "w_op"), (OperationClass.POST, "p_op"), (OperationClass.ADMIN, "a_op"),
    (OperationClass.DELETE, "d_op"), (OperationClass.RESET, "r_op")])
def test_every_non_read_class_is_denied(klass, base):
    ctx, dispatcher = _ctx(OperationRegistry.from_entries(((base, klass), ("ok_read", OperationClass.READ))))
    assert _submit(ctx, base).reason_code is R.OPERATION_DENIED
    assert _submit(ctx, base.upper()).reason_code is R.OPERATION_DENIED
    assert dispatcher.calls == ()


def test_registered_read_operation_is_allowed_only_with_typed_ids():
    ctx, dispatcher = _ctx()
    ok = _submit(ctx, "READ_DOCUMENT ")  # canonicalisation applies to the allowed side too
    assert ok.http_class == 202 and len(dispatcher.calls) == 1
    sql = _submit(ctx, "read_document", params=(("source_id", "SRC-1; DROP TABLE x"),))
    assert sql.reason_code is R.PARAMETER_SCHEMA_INVALID  # ids are a fixed charset, never free text
    assert len(dispatcher.calls) == 1
    assert _submit(ctx, "read_document", params=(("query", "select 1"),)).reason_code is \
        R.PARAMETER_SCHEMA_INVALID
    assert _submit(ctx, "read_document", params=(("command", "x"),)).reason_code is \
        R.PARAMETER_SCHEMA_INVALID


def test_refusal_log_is_sticky_even_if_a_later_registry_would_allow_the_name():
    log = RefusalLog()
    ctx_deny, d1 = _ctx(refusals=log)
    assert _submit(ctx_deny, "post_document").reason_code is R.OPERATION_DENIED
    permissive = OperationRegistry.from_entries((("post_document", OperationClass.READ),))
    ctx_open, d2 = _ctx(registry=permissive, refusals=log)
    for spelling in ("post_document", "POST_DOCUMENT", " post_document "):
        d = _submit(ctx_open, spelling)
        assert d.allowed is False and d.reason_code is R.OPERATION_DENIED
    assert d1.calls == () and d2.calls == ()
    assert ("T1", "C1", "post_document", R.OPERATION_DENIED) in log.entries()


def test_refusal_log_is_per_scope_and_bounded():
    log = RefusalLog(max_entries=3, per_tenant=3)
    for i in range(10):
        log.record("T1", "C1", f"op_{i}", R.OPERATION_DENIED)
    assert len(log.entries()) == 3
    assert log.lookup("T2", "C1", "op_0") is None
    assert log.lookup("T1", "C1", "op_0") is R.OPERATION_DENIED
    log.record("T1", "C1", "op_x", "not-a-code")  # type: ignore[arg-type]
    assert "not-a-code" not in repr(log.entries()) and len(log.entries()) == 3
    with pytest.raises(ValueError, match="^REFUSAL_LOG_INVALID$"):
        RefusalLog(max_entries=0)


def test_refusal_log_is_append_only():
    log = RefusalLog()
    log.record("T1", "C1", "post_document", R.OPERATION_DENIED)
    log.record("T1", "C1", "post_document", R.OPERATION_UNCLASSIFIED)  # cannot rewrite the code
    assert log.lookup("T1", "C1", "post_document") is R.OPERATION_DENIED
    assert not hasattr(log, "clear") and not hasattr(log, "remove") and not hasattr(log, "delete")


def test_evaluate_only_receives_validated_plans(monkeypatch):
    seen: list[object] = []
    real = jobs_api.evaluate

    def spy(plan, *a, **k):
        seen.append(plan)
        return real(plan, *a, **k)

    monkeypatch.setattr(jobs_api, "evaluate", spy)
    ctx, _ = _ctx()
    for spelling in ("post_document", "POST_DOCUMENT", "read_document", "x\u200by", "", "a" * 10_000):
        _submit(ctx, spelling)
    assert seen, "evaluate must be used"
    for plan in seen:
        assert all(op and op == op.strip().casefold() and op.isascii() for op in plan.operations)


def test_rerun_has_no_operation_and_cannot_carry_a_denied_one():
    assert "operation" not in {f.name for f in dataclasses.fields(RerunRequest)}


# ============================ AST: no channel / no free-form command ============================

FORBIDDEN_NAMES = {"channel", "command", "cmd", "query", "sql", "onec_code", "raw", "script",
                   "code", "expression", "statement", "payload", "body", "transport"}
MODULES = (jobs_api, safe_errors)


def _tree(module) -> ast.Module:
    return ast.parse(Path(inspect.getsourcefile(module)).read_text(encoding="utf-8"))


@pytest.mark.parametrize("module", MODULES)
def test_no_function_signature_has_a_channel_or_free_form_parameter(module):
    for node in ast.walk(_tree(module)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            names += [a.arg for a in (args.vararg, args.kwarg) if a]
            assert not FORBIDDEN_NAMES & {n.lower() for n in names}, node.name
            assert args.kwarg is None, node.name  # no **kwargs smuggling


@pytest.mark.parametrize("module", MODULES)
def test_no_dataclass_field_is_a_free_form_command(module):
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    assert item.target.id.lower() not in FORBIDDEN_NAMES, (node.name, item.target.id)


def test_runtime_request_fields_have_no_command_like_name():
    for cls in (JobRequest, RerunRequest, SessionRecord, ApiDecision):
        assert not FORBIDDEN_NAMES & {f.name for f in dataclasses.fields(cls)}, cls.__name__
    for fn in (decide_enqueue, decide_rerun, read_job, read_result):
        assert not FORBIDDEN_NAMES & set(inspect.signature(fn).parameters), fn.__name__


ALLOWED_IMPORT_ROOTS = {
    "__future__", "collections", "dataclasses", "datetime", "enum", "hashlib", "heapq", "hmac", "re",
    "threading", "time", "types", "typing"}
BANNED_ROOTS = {"httpx", "requests", "socket", "subprocess", "os", "pathlib", "sqlite3", "psycopg",
                "psycopg2", "asyncpg", "sqlalchemy", "http", "urllib", "flask", "fastapi",
                "starlette", "django", "aiohttp", "win32com", "pythoncom", "http.cookies"}


@pytest.mark.parametrize("module", MODULES)
def test_modules_import_only_stdlib_and_sibling_phase2(module):
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root in ALLOWED_IMPORT_ROOTS and root not in BANNED_ROOTS, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert node.level == 1, "one-dot imports only"
                assert node.module and "." not in node.module
                assert not {"drive_http", "capture_loop", "connector_sdk"} & {node.module}
            else:
                assert node.module.split(".")[0] in ALLOWED_IMPORT_ROOTS, node.module
        elif isinstance(node, ast.Attribute):
            assert not (isinstance(node.value, ast.Name) and node.value.id == "os")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "eval", "exec", "compile", "__import__"}


def test_no_real_looking_token_in_module_sources():
    for module in MODULES:
        text = Path(inspect.getsourcefile(module)).read_text(encoding="utf-8")
        assert "$(" not in text and "BEGIN PRIVATE" not in text and "ya29." not in text


# ============================ S6b lesson rows: hostile input never raises ============================

def _hostile_objects():
    rec: list = []
    rec.append(rec)
    deep: object = ()
    for _ in range(2000):
        deep = (deep,)
    return [None, 0, -1, 10**30, 1.5, float("nan"), b"x", rec, deep, {"a": 1}, object(), StrSub("x"),
            IntSub(1), "x" * 1_000_000, "\x00", ReasonCode.NOT_FOUND]


def _valid_request():
    return JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                      (("source_id", "SRC-1"),), "idem-key-0001")


@pytest.mark.parametrize("hostile", _hostile_objects(), ids=lambda v: type(v).__name__)
def test_public_functions_never_raise_on_hostile_arguments(hostile):
    ctx, dispatcher = _ctx()
    req, rerun = _valid_request(), RerunRequest(
        ViewerScope("T1", "C1", 1), "alice", "CK-1", "run-1", "SN-2", "idem-key-0002")
    viewer = ViewerScope("T1", "C1", 1)

    class Gate:
        def check(self, request):
            return None

        def commit(self, request):
            return jobs_api.RerunCommit("run-new-1", jobs_api.RunState.CREATED)

    results = [
        decide_enqueue(hostile, req, SESSION, TOKEN), decide_enqueue(ctx, hostile, SESSION, TOKEN),
        decide_enqueue(ctx, req, hostile, TOKEN), decide_enqueue(ctx, req, SESSION, hostile),
        decide_rerun(hostile, rerun, SESSION, TOKEN, Gate()),
        decide_rerun(ctx, hostile, SESSION, TOKEN, Gate()),
        decide_rerun(ctx, rerun, hostile, TOKEN, Gate()),
        decide_rerun(ctx, rerun, SESSION, hostile, Gate()),
        decide_rerun(ctx, rerun, SESSION, TOKEN, hostile),
        read_job(hostile, viewer, SESSION, "JOB-000001"), read_job(ctx, hostile, SESSION, "x"),
        read_job(ctx, viewer, hostile, "x"), read_job(ctx, viewer, SESSION, hostile),
        read_result(hostile, viewer, SESSION, "x"), read_result(ctx, hostile, SESSION, "x"),
        read_result(ctx, viewer, hostile, "x"), read_result(ctx, viewer, SESSION, hostile),
    ]
    for d in results:
        assert type(d) is ApiDecision
        assert d.allowed is False or d.ticket is not None or d.job is not None
        assert repr(d) and "x" * 100 not in repr(d)
    assert dispatcher.calls == ()


def test_forged_instances_are_refused_not_raised():
    ctx, dispatcher = _ctx()
    forged_req = object.__new__(JobRequest)
    forged_session = object.__new__(SessionRecord)
    forged_scope = object.__new__(ViewerScope)
    for req, ses in ((forged_req, SESSION), (_valid_request(), forged_session)):
        d = decide_enqueue(ctx, req, ses, TOKEN)
        assert d.allowed is False and d.http_class in (400, 401)
    half = _forge(JobRequest, scope=ViewerScope("T1", "C1", 1))
    assert decide_enqueue(ctx, half, SESSION, TOKEN).allowed is False
    assert read_job(ctx, forged_scope, SESSION, "JOB-1").allowed is False
    assert dispatcher.calls == ()


def test_lying_eq_subclasses_cannot_pass_exact_type_checks():
    ctx, dispatcher = _ctx()
    with pytest.raises(ValueError):
        ViewerScope("T1", "C1", IntSub(1))
    sub_op = _forge(JobRequest, scope=ViewerScope("T1", "C1", 1), actor_id="alice",
                    kind=JobKind.RESCAN, operation=StrSub("post_document"),
                    params=(("source_id", "SRC-1"),), idempotency_key="idem-key-0001")
    assert decide_enqueue(ctx, sub_op, SESSION, TOKEN).allowed is False
    sub_key = _forge(JobRequest, scope=ViewerScope("T1", "C1", 1), actor_id="alice",
                     kind=JobKind.RESCAN, operation="read_document",
                     params=(("source_id", "SRC-1"),), idempotency_key=StrSub("idem-key-0001"))
    assert decide_enqueue(ctx, sub_key, SESSION, TOKEN).allowed is False
    sub_token = decide_enqueue(ctx, _valid_request(), SESSION, StrSub(TOKEN))
    assert sub_token.reason_code is R.CSRF_REJECTED
    sub_actor = _forge(JobRequest, scope=ViewerScope("T1", "C1", 1), actor_id=StrSub("alice"),
                       kind=JobKind.RESCAN, operation="read_document",
                       params=(("source_id", "SRC-1"),), idempotency_key="idem-key-0001")
    assert decide_enqueue(ctx, sub_actor, SESSION, TOKEN).allowed is False
    sub_param = _forge(JobRequest, scope=ViewerScope("T1", "C1", 1), actor_id="alice",
                       kind=JobKind.RESCAN, operation="read_document",
                       params=((StrSub("source_id"), StrSub("SRC-1")),), idempotency_key="idem-key-0001")
    assert decide_enqueue(ctx, sub_param, SESSION, TOKEN).reason_code is R.PARAMETER_SCHEMA_INVALID
    assert dispatcher.calls == ()


def test_huge_and_recursive_params_are_refused_cheaply():
    ctx, dispatcher = _ctx()
    rec: list = []
    rec.append(rec)
    for params in ((("source_id", "x" * 1_000_000),), (("source_id", rec),),
                   tuple((f"p{i}", "v") for i in range(100_000)), ((rec, rec),)):
        req = _forge(JobRequest, scope=ViewerScope("T1", "C1", 1), actor_id="alice",
                     kind=JobKind.RESCAN, operation="read_document", params=params,
                     idempotency_key="idem-key-0001")
        d = decide_enqueue(ctx, req, SESSION, TOKEN)
        assert d.reason_code is R.PARAMETER_SCHEMA_INVALID
    assert dispatcher.calls == ()


def test_forged_session_with_lying_fields_is_refused():
    ctx, dispatcher = _ctx()
    forged = _forge(SessionRecord, session_id="S1", tenant_id=StrSub("T1"), actor_id="alice",
                    expires_at=SESSION.expires_at, csrf_secret_digest=DIGEST)
    assert decide_enqueue(ctx, _valid_request(), forged, TOKEN).reason_code is R.SESSION_INVALID

    class FutureSub(datetime):
        pass

    sub_time = _forge(SessionRecord, session_id="S1", tenant_id="T1", actor_id="alice",
                      expires_at=FutureSub(2099, 1, 1, tzinfo=UTC), csrf_secret_digest=DIGEST)
    assert decide_enqueue(ctx, _valid_request(), sub_time, TOKEN).reason_code is R.SESSION_INVALID
    assert dispatcher.calls == ()


def test_naive_or_non_utc_expiry_is_handled():
    with pytest.raises(ValueError, match="^SESSION_INVALID$"):
        SessionRecord("S1", "T1", "alice", datetime(2030, 1, 1), DIGEST)  # noqa: DTZ001 - naive on purpose
    plus3 = datetime(2026, 1, 1, 3, 30, tzinfo=UTC).astimezone(
        __import__("datetime").timezone(timedelta(hours=3)))
    s = SessionRecord("S1", "T1", "alice", plus3, DIGEST)
    ctx, _ = _ctx()
    assert decide_enqueue(ctx, _valid_request(), s, fake_csrf_token(s)).http_class == 202


def test_clock_returning_garbage_is_dependency_failed():
    ctx, dispatcher = _ctx()

    class BadClock:
        def __init__(self, value):
            self.value = value

        def now(self):
            return self.value

    for value in (None, "2026-01-01", datetime(2026, 1, 1), 5):  # noqa: DTZ001
        bad = dataclasses.replace(ctx, clock=BadClock(value))
        d = decide_enqueue(bad, _valid_request(), SESSION, TOKEN)
        assert d.allowed is False and d.reason_code is R.DEPENDENCY_FAILED
    assert dispatcher.calls == ()


def test_scope_source_returning_hostile_epoch_is_refused():
    ctx, dispatcher = _ctx()

    class Scopes:
        def __init__(self, value):
            self.value = value

        def current_epoch(self, tenant_id, company_id):
            return self.value

    for value in (IntSub(1), True, "1", None, 1.0):
        d = decide_enqueue(dataclasses.replace(ctx, scopes=Scopes(value)), _valid_request(), SESSION, TOKEN)
        assert d.allowed is False and d.reason_code is R.SCOPE_EPOCH_STALE
    assert dispatcher.calls == ()


def test_csrf_derivation_garbage_rejects_instead_of_raising():
    ctx, dispatcher = _ctx()
    for derive in (lambda s: None, lambda s: StrSub(TOKEN), lambda s: 5, lambda s: 1 / 0,
                   lambda s: "FAKE-" + "é"):
        guarded = dataclasses.replace(ctx, csrf=CsrfGuard(derive))
        d = decide_enqueue(guarded, _valid_request(), SESSION, TOKEN)
        assert d.reason_code is R.CSRF_REJECTED
    non_ascii = decide_enqueue(ctx, _valid_request(), SESSION, "FAKE-éé")
    assert non_ascii.reason_code is R.CSRF_REJECTED
    assert dispatcher.calls == ()


def test_csrf_compare_uses_constant_time_primitive(monkeypatch):
    calls: list[tuple[object, object]] = []
    real = jobs_api.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(jobs_api.hmac, "compare_digest", spy)
    guard = CsrfGuard(fake_csrf_token)
    assert guard.check(SESSION, TOKEN) is True and guard.check(SESSION, TOKEN[:-1] + "0") is False
    assert len(calls) == 2 and all(type(x) is bytes and type(y) is bytes for x, y in calls)
    assert fake_csrf_token(SESSION) == fake_csrf_token(SESSION)  # deterministic derivation


def test_context_with_wrong_component_types_is_refused():
    ctx, dispatcher = _ctx()
    for field in ("csrf", "idempotency", "refusals", "registry"):
        bad = _forge(ApiContext, **{f.name: getattr(ctx, f.name) for f in dataclasses.fields(ApiContext)})
        object.__setattr__(bad, field, object())
        d = decide_enqueue(bad, _valid_request(), SESSION, TOKEN)
        assert d.allowed is False and d.reason_code is R.INTERNAL_REFUSED
    assert dispatcher.calls == ()


def test_decision_types_are_frozen_slotted_and_authority_is_evaluation_only():
    ctx, _ = _ctx()
    d = decide_enqueue(ctx, _valid_request(), SESSION, TOKEN)
    assert d.authority == "EVALUATION_ONLY" and d.ticket.authority == "EVALUATION_ONLY"
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.allowed = False  # type: ignore[misc]
    assert not hasattr(d, "__dict__") and not hasattr(d.ticket, "__dict__")
    with pytest.raises(ValueError):
        ApiDecision(True, 418, None, jobs_api.NextAction.NO_ACTION, "CORR-1", None, None)
    with pytest.raises(ValueError):
        ApiDecision(True, 202, R.NOT_FOUND, jobs_api.NextAction.NO_ACTION, "CORR-1", None, None)
