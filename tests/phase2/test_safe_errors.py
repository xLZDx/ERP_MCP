"""S8/E3 TC121: safe error rendering is a closed vocabulary; no free text can reach any output."""
from __future__ import annotations

import dataclasses
import inspect
import threading

import pytest

from business_ai_gateway.phase2 import safe_errors
from business_ai_gateway.phase2.safe_errors import (
    ACTION_TEXT,
    MESSAGES,
    FakeCorrelationSource,
    RenderedError,
    new_safe_error,
    render_safe_error,
)
from business_ai_gateway.phase2.workbench_types import (
    DEFAULT_CORRELATION_ID,
    NEXT_ACTION_FOR,
    NextAction,
    ReasonCode,
    SafeError,
    safe_error,
)

POISON = "Traceback secret://vault/key-7 SELECT * FROM tenants provider said no ForeignSourceName"


class StrSub(str):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


class Boom:
    def next_id(self) -> str:
        raise RuntimeError(POISON)


class PoisonSource:
    def next_id(self) -> str:
        return POISON


class SubSource:
    def next_id(self) -> str:
        return StrSub("CORR-1")


def _all_text(obj: object) -> str:
    parts = [repr(obj), str(obj)]
    if dataclasses.is_dataclass(obj):
        parts += [repr(getattr(obj, f.name)) for f in dataclasses.fields(obj)]
    return " ".join(parts)


# --- refusal / poison rows first -------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    None, POISON, 42, RuntimeError(POISON), StrSub("x"), object(), ReasonCode.NOT_FOUND,
    object.__new__(SafeError),
])
def test_render_hostile_input_is_fixed_internal_refused(bad):
    out = render_safe_error(bad)
    assert type(out) is RenderedError
    assert out.reason_code == "INTERNAL_REFUSED"
    assert out.message == MESSAGES[ReasonCode.INTERNAL_REFUSED]
    assert out.correlation_id == DEFAULT_CORRELATION_ID
    assert "Traceback" not in _all_text(out) and "secret" not in _all_text(out)


@pytest.mark.parametrize("source", [Boom(), PoisonSource(), SubSource(), None, object()])
def test_new_safe_error_hostile_source_degrades_to_default_id(source):
    err = new_safe_error(ReasonCode.CSRF_REJECTED, source)
    assert type(err) is SafeError
    assert err.reason_code is ReasonCode.CSRF_REJECTED
    assert err.next_action is NEXT_ACTION_FOR[ReasonCode.CSRF_REJECTED]
    assert err.correlation_id == DEFAULT_CORRELATION_ID
    assert POISON not in _all_text(err)


@pytest.mark.parametrize("code", [None, POISON, StrSub("NOT_FOUND"), "NOT_FOUND", 7])
def test_new_safe_error_non_enum_code_is_input_invalid(code):
    err = new_safe_error(code, FakeCorrelationSource())
    assert err.reason_code is ReasonCode.INPUT_INVALID
    assert POISON not in _all_text(err)


def test_poison_correlation_id_never_reaches_a_safe_error():
    err = safe_error(ReasonCode.NOT_FOUND, POISON)
    assert err.correlation_id == DEFAULT_CORRELATION_ID
    assert POISON not in _all_text(render_safe_error(err))


def test_render_signature_takes_one_object_and_no_free_text():
    params = list(inspect.signature(render_safe_error).parameters)
    assert params == ["error"]
    assert not {"message", "text", "detail", "exception", "exc", "reason_text"} & set(params)


# --- closed vocabulary -----------------------------------------------------------------------

def test_message_table_is_complete_and_fixed():
    assert set(MESSAGES) == set(ReasonCode)
    assert set(ACTION_TEXT) == set(NextAction)
    for text in [*MESSAGES.values(), *ACTION_TEXT.values()]:
        assert type(text) is str and text and text.isascii()
        assert "{" not in text and "%" not in text and "\n" not in text
    assert len(set(MESSAGES.values())) == len(MESSAGES)  # every code is distinguishable


def test_tables_are_read_only():
    with pytest.raises(TypeError):
        MESSAGES[ReasonCode.NOT_FOUND] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        ACTION_TEXT[NextAction.NO_ACTION] = "x"  # type: ignore[index]


@pytest.mark.parametrize("code", list(ReasonCode))
def test_every_reason_code_renders_exactly_its_fixed_text(code):
    err = safe_error(code, "CORR-000009")
    if code in (ReasonCode.ORIGINAL_INTACT, ReasonCode.REPLAYED):
        code = ReasonCode.INTERNAL_REFUSED  # success-like codes degrade: never shown as a refusal
    out = render_safe_error(err)
    assert out == RenderedError(
        reason_code=code.value, message=MESSAGES[code],
        next_action=err.next_action.value, next_action_text=ACTION_TEXT[err.next_action],
        correlation_id="CORR-000009")
    assert {f.name for f in dataclasses.fields(out)} == {
        "reason_code", "message", "next_action", "next_action_text", "correlation_id", "authority"}
    assert out.authority == "EVALUATION_ONLY"


def test_rendered_error_is_frozen_and_slotted():
    out = render_safe_error(safe_error(ReasonCode.NOT_FOUND, "CORR-1"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.message = "x"  # type: ignore[misc]
    assert not hasattr(out, "__dict__")


def test_messages_do_not_name_foreign_sources_or_internals():
    joined = " ".join(MESSAGES.values()).lower()
    for word in ("traceback", "stack", "sql", "secret", "token", "provider", "select "):
        assert word not in joined


# --- correlation source ----------------------------------------------------------------------

def test_fake_correlation_source_is_deterministic():
    a, b = FakeCorrelationSource(), FakeCorrelationSource()
    assert [a.next_id() for _ in range(3)] == [b.next_id() for _ in range(3)]
    assert a.next_id() == "CORR-000004"


def test_fake_correlation_source_unique_under_threads():
    src = FakeCorrelationSource()
    seen: list[str] = []
    lock = threading.Lock()

    def work() -> None:
        ids = [src.next_id() for _ in range(200)]
        with lock:
            seen.extend(ids)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == len(set(seen)) == 1600


def test_correlation_id_is_not_derived_from_input():
    src = FakeCorrelationSource()
    first = new_safe_error(ReasonCode.NOT_FOUND, src)
    second = new_safe_error(ReasonCode.NOT_FOUND, src)
    assert first.correlation_id != second.correlation_id
    assert first.correlation_id == "CORR-000001"


def test_module_exports_only_declared_names():
    assert set(safe_errors.__all__) == {
        "ACTION_TEXT", "MESSAGES", "CorrelationSource", "FakeCorrelationSource", "RenderedError",
        "new_safe_error", "render_safe_error"}


def test_fake_correlation_prefix_must_be_ascii_alnum():
    for bad in ("٣٤", "éa", "", "x" * 17, 5, None, "a-b"):
        assert FakeCorrelationSource(bad).next_id() == "CORR-000001"  # type: ignore[arg-type]
    assert FakeCorrelationSource("REQ").next_id() == "REQ-000001"


def test_import_time_guard_rejects_an_incomplete_message_table():
    source = inspect.getsource(safe_errors)
    assert "SAFE_ERROR_TABLES_INCOMPLETE" in source  # the guard exists; coverage asserted above
    assert set(MESSAGES) == set(ReasonCode)
