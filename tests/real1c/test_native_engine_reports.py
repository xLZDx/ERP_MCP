"""Native engine-report generator: identity, allowlist, safety gates, non-validating evidence class (fakes only)."""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.real1c import native_engine_reports as ner

ROOT_DIR = ner.REPO_ROOT
from scripts.real1c.evidence import (
    EVIDENCE_CLASSES,
    ValidateRefused,
    assert_can_validate,
    would_validate,
)

SHA = "b" * 64
PRE = "c" * 64
META = "d" * 64


# ---------------------------------------------------------------- fake 1C object model
class FakeItem:
    def __init__(self, name):
        self.Parameter, self.Value, self.Use = name, None, False


class FakeItems:
    def __init__(self, names):
        self.items = [FakeItem(n) for n in names]

    def Count(self):
        return len(self.items)

    def Get(self, i):
        return self.items[i]


class FakeDoc:
    def __init__(self, rows):
        self.TableHeight, self.TableWidth, self._rows = 0, 0, rows

    def Write(self, path, kind):
        Path(path).write_bytes(b"xlsx-bytes:" + str(kind).encode())


class FakeComposer:
    def __init__(self, names):
        self.Settings = type("S", (), {"DataParameters": type("P", (), {"Items": FakeItems(names)})()})()

    def Initialize(self, source):
        self.source = source

    def LoadSettings(self, settings):
        self.loaded = settings


class FakeReport:
    def __init__(self, names):
        self.DataCompositionSchema = type("Sch", (), {"DefaultSettings": object()})()
        self.SettingsComposer = FakeComposer(names)


class FakeManager:
    def __init__(self, conn, name):
        self.conn, self.name = conn, name

    def Create(self):
        self.conn.created.append(self.name)
        if self.name in self.conn.broken:
            raise RuntimeError("no right for this report")
        return FakeReport(self.conn.param_names)


class FakeReports:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return FakeManager(self._conn, name)


class FakeConn:
    def __init__(self, user=ner.READER_USER, rows=5, broken=(), write_denied=True, rights=None):
        self.user, self.rows, self.broken = user, rows, set(broken)
        self.rights = rights or {}  # {(right, object name or "*config"): True}
        self.created, self.new_types, self.writes = [], [], []
        self.param_names = ["НачалоПериода", "КонецПериода", "Период", "КонецПериодаОстатки", "Other"]
        self.Reports = FakeReports(self)
        self.SpreadsheetDocumentFileType = type("T", (), {"XLSX": "XLSX"})()
        self.write_denied, self.tx = write_denied, []
        self.Metadata = type("M", (), {"Catalogs": [type("C", (), {"Name": "Cat"})()],
                                       "Documents": [type("D", (), {"Name": "Doc"})()]})()
        self.Catalogs = type("Cs", (), {"Cat": type("Cat", (), {"CreateItem": lambda _s: self._item()})()})()

    def _item(self):
        conn = self

        class Item:
            Description = ""

            def Write(self):
                if conn.write_denied:
                    raise RuntimeError("Access violation!")
                conn.writes.append(1)

        return Item()

    def AccessRight(self, right, obj):
        return self.rights.get((right, "*config" if obj is self.Metadata else obj.Name), False)

    def BeginTransaction(self):
        self.tx.append("begin")

    def RollbackTransaction(self):
        self.tx.append("rollback")

    def UserName(self):
        return self.user

    def String(self, value):
        return value

    def NewObject(self, type_name, *args):
        self.new_types.append(type_name)
        if type_name == "SpreadsheetDocument":
            self.doc = FakeDoc(self.rows)
            return self.doc
        if type_name == "DataCompositionTemplateComposer":
            return type("TC", (), {"Execute": lambda _s, *a: "template"})()
        if type_name == "DataCompositionProcessor":
            return type("P", (), {"Initialize": lambda _s, t: None})()
        if type_name == "DataCompositionResultSpreadsheetDocumentOutputProcessor":
            conn = self

            class Out:
                def SetDocument(self, doc):
                    self.doc = doc

                def Output(self, proc):
                    self.doc.TableHeight, self.doc.TableWidth = conn.rows, (3 if conn.rows else 0)

            return Out()
        return object()


# ---------------------------------------------------------------- evidence class stays non-validating
def test_engine_class_is_known_but_never_counts_for_validate():
    assert ner.EVIDENCE_CLASS in EVIDENCE_CLASSES
    cases = [{"case_id": f"C{i}", "evidence_class": ner.EVIDENCE_CLASS, "native_report_sha256": SHA} for i in range(12)]
    with pytest.raises(ValidateRefused):
        assert_can_validate({"cases": cases})
    assert not would_validate({"cases": cases})


def test_nine_ui_plus_engine_cases_still_refused():
    ui = [{"case_id": f"U{i}", "evidence_class": "NATIVE_UI_REPORT", "native_report_sha256": SHA} for i in range(9)]
    eng = [{"case_id": "E1", "evidence_class": ner.EVIDENCE_CLASS, "native_report_sha256": SHA}]
    assert not would_validate({"cases": ui + eng})


# ---------------------------------------------------------------- identity: reader only, no switch
def test_connect_signature_has_no_user_argument():
    params = set(inspect.signature(ner.connect_reader).parameters)
    assert params == {"base", "connector"}
    assert set(inspect.signature(ner.run).parameters).isdisjoint({"user", "username", "password"})


def test_module_never_references_the_admin_credential_path():
    tree = ast.parse(Path(ner.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):  # docstrings and comments may explain the rule; executable code may not break it
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef) and ast.get_docstring(node):
            node.body = node.body[1:] or [ast.Pass()]
    code = ast.unparse(tree)
    for forbidden in ("admin_1c", "Admin_1C", "com_oracle", "Oracle(", "os.environ", "getenv"):
        assert forbidden not in code, forbidden


def test_unknown_base_is_rejected_before_the_secret_is_read(monkeypatch):
    monkeypatch.setattr(ner, "_reader_password", Mock(side_effect=AssertionError("secret must not be read")))
    connector = Mock()
    with pytest.raises(ner.GeneratorRefused):
        ner.connect_reader(Path("D:/ERP_MCP_Testbed/1c/reference/working/818HA_reference_ro"), connector=connector)
    connector.assert_not_called()


def test_environment_cannot_switch_the_user(monkeypatch):
    for key in ("ERP_MCP_COM_USER", "ONEC_USER", "USERNAME", "E2E_USER"):
        monkeypatch.setenv(key, "Admin_1C")
    monkeypatch.setattr(ner, "_reader_password", lambda: "pw")
    seen = []
    conn = FakeConn()
    connector = lambda: type("C", (), {"Connect": lambda _s, text: (seen.append(text), conn)[1]})()
    session = ner.connect_reader(ner.REFERENCE_CLONE, connector=connector)
    assert session.user == ner.READER_USER
    assert f'Usr="{ner.READER_USER}"' in seen[0] and "Admin_1C" not in seen[0]


def test_a_connection_that_is_not_the_reader_is_refused(monkeypatch):
    monkeypatch.setattr(ner, "_reader_password", lambda: "pw")
    conn = FakeConn(user="Admin_1C")
    connector = lambda: type("C", (), {"Connect": lambda _s, text: conn})()
    with pytest.raises(ner.GeneratorRefused):
        ner.connect_reader(ner.REFERENCE_CLONE, connector=connector)


# ---------------------------------------------------------------- write-denial preflight
def test_preflight_denied_write_is_rolled_back():
    conn = FakeConn(write_denied=True)
    assert ner.write_denial_preflight(ner.ReaderSession(conn, ner.PROBE_CLONE.resolve(), ner.READER_USER)) == "PASS_WRITE_DENIED"
    assert conn.tx == ["begin", "rollback"]


def test_preflight_reports_an_allowed_write_and_still_rolls_back():
    conn = FakeConn(write_denied=False)
    assert ner.write_denial_preflight(ner.ReaderSession(conn, ner.PROBE_CLONE.resolve(), ner.READER_USER)) == "FAIL_WRITE_ALLOWED"
    assert conn.tx[-1] == "rollback"


def test_preflight_never_runs_on_the_reference_clone():
    conn = FakeConn()
    with pytest.raises(ner.GeneratorRefused):
        ner.write_denial_preflight(ner.ReaderSession(conn, ner.REFERENCE_CLONE.resolve(), ner.READER_USER))
    assert conn.tx == []


# ---------------------------------------------------------------- allowlist wrapper
def test_unallowlisted_operations_are_blocked():
    obj = Mock()
    for call in (lambda: ner._call(obj, "Delete"), lambda: ner._call(obj, "Execute2"), lambda: ner._get(obj, "Catalogs"),
                 lambda: ner._put(obj, "Description", "x"), lambda: ner._new(obj, "Query"),
                 lambda: ner._new(obj, "COMConnector")):
        with pytest.raises(ner.UnallowedOperation):
            call()
    assert obj.mock_calls == []


def test_unknown_report_name_is_blocked_before_touching_the_connection():
    conn = FakeConn()
    with pytest.raises(ner.UnallowedOperation):
        ner.generate(conn, "ОборотноСальдоваяВедомость", *ner.REFERENCE_PERIOD)
    assert conn.created == [] and conn.new_types == []


def test_generate_sets_only_declared_parameters_and_uses_only_allowlisted_types():
    conn = FakeConn()
    sheet = ner.generate(conn, "ОстаткиДенежныхСредств", *ner.REFERENCE_PERIOD)
    assert (sheet.rows, sheet.cols) == (5, 3)
    assert set(conn.new_types) <= ner._NEW


def test_generate_fills_the_period_parameters_of_a_spec():
    conn = FakeConn()
    seen = {}
    real_call = ner._call

    def spy(obj, name, *args):
        out = real_call(obj, name, *args)
        if name == "Get":
            seen[id(out)] = out
        return out

    ner._call = spy
    try:
        ner.generate(conn, "ДоходыРасходы", *ner.REFERENCE_PERIOD)
    finally:
        ner._call = real_call
    values = {str(i.Parameter): (i.Value, i.Use) for i in seen.values()}
    assert values["НачалоПериода"] == (ner.REFERENCE_PERIOD[0], True)
    assert values["КонецПериода"] == (ner.REFERENCE_PERIOD[1], True)
    assert values["Other"] == (None, False) and values["Период"] == (None, False)


# ---------------------------------------------------------------- outputs stay outside Git
def test_outputs_inside_the_repository_are_refused():
    inside = ner.REPO_ROOT / "reports" / "x.xlsx"
    with pytest.raises(ner.GeneratorRefused):
        ner.assert_private(inside)
    with pytest.raises(ner.GeneratorRefused):
        ner.export_xlsx(FakeConn(), ner.Sheet(FakeDoc(1), 1, 1), inside)
    assert not inside.exists()


def test_the_default_output_root_is_outside_the_repository():
    ner.assert_private(ner.PRIVATE_ROOT)


# ---------------------------------------------------------------- the whole run
def _fp(content, unreadable="u" * 64, per_table=None):
    return {"content_fingerprint_sha256": content, "metadata_fingerprint": META, "unreadable_fingerprint": unreadable,
            "per_table": {"Catalogs.X": 3} if per_table is None else per_table, "readable_tables": 1,
            "unreadable_tables": 2, "metadata_object_count": 3}


def _patch_run(monkeypatch, conn, *, pre=PRE, post=PRE, baseline=None, post_unreadable="u" * 64, root=None):
    monkeypatch.setattr(ner, "_reader_password", lambda: "pw")
    if root is not None:
        monkeypatch.setattr(ner, "PRIVATE_ROOT", root)
    monkeypatch.setattr(ner, "verify_reference_manifest", lambda path: {
        "metadata_fingerprint": META, "private": {"per_table_counts": baseline or {"Catalogs.X": 3, "Catalogs.Hidden": 9}}})
    prints = iter([_fp(pre), _fp(post, post_unreadable)])
    monkeypatch.setattr(ner, "readable_fingerprint", lambda c: next(prints))
    connector = lambda: type("C", (), {"Connect": lambda _s, text: conn})()
    return connector


def _run(tmp_path, connector, **kwargs):
    return ner.run(out_root=tmp_path, connector=connector, now=lambda: dt.datetime(2026, 10, 7, 12, 0, 0),  # noqa: DTZ001
                   **kwargs)


def test_full_run_records_hashes_and_marks_the_class_non_validating(monkeypatch, tmp_path):
    conn = FakeConn()
    record = _run(tmp_path, _patch_run(monkeypatch, conn, root=tmp_path), reports=["ДоходыРасходы", "ОстаткиТоваров"])
    assert record["evidence_class"] == "NATIVE_ENGINE_REPORT" and record["validating"] is False
    assert record["identity"] == ner.READER_USER and record["preflight_probe_clone"] == "PASS_WRITE_DENIED"
    assert record["evidence_valid"] is True
    assert [r["status"] for r in record["reports"]] == ["GENERATED", "GENERATED"]
    files = sorted((tmp_path / "run_20261007_120000").glob("*.xlsx"))
    assert len(files) == 2 and all(len(r["sha256"]) == 64 for r in record["reports"])
    saved = json.loads((tmp_path / "run_20261007_120000" / "manifest.json").read_text(encoding="utf-8"))
    assert saved["validating"] is False


def test_a_report_the_reader_cannot_run_is_unavailable_without_retry(monkeypatch, tmp_path):
    conn = FakeConn(broken={"ОстаткиТоваров"})
    record = _run(tmp_path, _patch_run(monkeypatch, conn, root=tmp_path), reports=["ОстаткиТоваров", "ДоходыРасходы"])
    by_name = {r["report"]: r for r in record["reports"]}
    assert by_name["ОстаткиТоваров"]["status"] == "UNAVAILABLE" and "sha256" not in by_name["ОстаткиТоваров"]
    assert by_name["ДоходыРасходы"]["status"] == "GENERATED"
    assert conn.created.count("ОстаткиТоваров") == 1  # no retry


def test_an_empty_sheet_is_recorded_empty_and_not_exported(monkeypatch, tmp_path):
    conn = FakeConn(rows=0)
    record = _run(tmp_path, _patch_run(monkeypatch, conn, root=tmp_path), reports=["ДоходыРасходы"])
    assert record["reports"][0]["status"] == "EMPTY"
    assert not list(tmp_path.rglob("*.xlsx"))


def test_a_failed_write_denial_preflight_stops_before_any_report(monkeypatch, tmp_path):
    conn = FakeConn(write_denied=False)
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, _patch_run(monkeypatch, conn, root=tmp_path), reports=["ДоходыРасходы"])
    assert conn.created == []


def test_fingerprint_drift_voids_the_evidence(monkeypatch, tmp_path):
    conn = FakeConn()
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, _patch_run(monkeypatch, conn, post="e" * 64, root=tmp_path), reports=["ДоходыРасходы"])
    saved = json.loads((tmp_path / "run_20261007_120000" / "manifest.json").read_text(encoding="utf-8"))
    assert saved["evidence_valid"] is False


def test_a_readable_table_that_differs_from_the_manifest_baseline_stops_the_run(monkeypatch, tmp_path):
    conn = FakeConn()
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, _patch_run(monkeypatch, conn, baseline={"Catalogs.X": 4}, root=tmp_path), reports=["ДоходыРасходы"])
    assert conn.created == []


def test_a_change_in_the_unreadable_set_voids_the_evidence(monkeypatch, tmp_path):
    conn = FakeConn()
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, _patch_run(monkeypatch, conn, post_unreadable="v" * 64, root=tmp_path), reports=["ДоходыРасходы"])
    saved = json.loads((tmp_path / "run_20261007_120000" / "manifest.json").read_text(encoding="utf-8"))
    assert saved["evidence_valid"] is False


def test_the_record_states_how_much_of_the_base_the_reader_could_fingerprint(monkeypatch, tmp_path):
    record = _run(tmp_path, _patch_run(monkeypatch, FakeConn(), root=tmp_path), reports=["ДоходыРасходы"])
    assert record["fingerprint_coverage"] == {"readable_tables": 1, "unreadable_tables": 2, "metadata_objects": 3}


def test_unknown_report_in_the_request_is_refused_before_connecting(monkeypatch, tmp_path):
    connector = Mock()
    monkeypatch.setattr(ner, "PRIVATE_ROOT", tmp_path)
    monkeypatch.setattr(ner, "_reader_password", Mock(side_effect=AssertionError("must not connect")))
    with pytest.raises(ner.UnallowedOperation):
        _run(tmp_path, connector, reports=["КарточкаСчета"])
    connector.assert_not_called()


def test_fixed_paths_agree_with_the_lane_runner():
    from scripts.real1c import run_lane

    assert ner.REFERENCE_MANIFEST == run_lane.MANIFEST
    assert ner.PRIVATE_ROOT.parent == run_lane.PRIVATE_DIR
    assert ner.REFERENCE_CLONE == Path(run_lane.REF_DIR).parent / "working" / "818HA_test_ready"


def test_preflight_denied_already_at_item_creation_is_a_pass():
    conn = FakeConn()
    conn.Catalogs = type("Cs", (), {"Cat": type("Cat", (), {"CreateItem": lambda _s: (_ for _ in ()).throw(RuntimeError("Access violation!"))})()})()
    session = ner.ReaderSession(conn, ner.PROBE_CLONE.resolve(), ner.READER_USER)
    assert ner.write_denial_preflight(session) == "PASS_WRITE_DENIED"
    assert conn.tx == ["begin", "rollback"]


def test_readable_fingerprint_skips_tables_the_identity_cannot_read():
    from scripts.real1c import com_fingerprint as cf

    class Tbl:
        def __init__(self, n):
            self.n = n

        def Count(self):
            return 1

        def Get(self, i):
            return type("R", (), {"К": self.n})()

    class Q:
        def __init__(self, text):
            self.text = text

        def Выполнить(self):
            if "Скрытый" in self.text:
                raise RuntimeError("Insufficient rights to use table")
            return self

        def Выгрузить(self):
            return Tbl(7)

    empty: list = []
    md = type("Md", (), {"Catalogs": [type("O", (), {"Name": "Видимый"})(), type("O", (), {"Name": "Скрытый"})()],
                         "Documents": empty, "AccumulationRegisters": empty, "AccountingRegisters": empty,
                         "InformationRegisters": empty, "ChartsOfAccounts": empty})()

    conn = type("C", (), {"Metadata": md, "NewObject": lambda _s, kind, text: Q(text)})()
    fp = cf.readable_fingerprint(conn)
    assert fp["readable_tables"] == 1 and fp["unreadable_tables"] == 1
    assert fp["per_table"] == {"Catalogs.Видимый": 7} and fp["metadata_object_count"] == 2
    with pytest.raises(RuntimeError):  # the strict fingerprint (oracle) must NOT swallow rights errors
        cf.fingerprint_of(conn)


def test_a_metadata_fingerprint_that_differs_from_the_manifest_stops_the_run(monkeypatch, tmp_path):
    conn = FakeConn()
    connector = _patch_run(monkeypatch, conn, root=tmp_path)
    monkeypatch.setattr(ner, "verify_reference_manifest", lambda path: {
        "metadata_fingerprint": "9" * 64, "private": {"per_table_counts": {"Catalogs.X": 3}}})
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, connector, reports=["ДоходыРасходы"])
    assert conn.created == []


def test_a_reader_that_can_fingerprint_no_table_cannot_start_a_run(monkeypatch, tmp_path):
    conn = FakeConn()
    monkeypatch.setattr(ner, "PRIVATE_ROOT", tmp_path)
    monkeypatch.setattr(ner, "_reader_password", lambda: "pw")
    monkeypatch.setattr(ner, "verify_reference_manifest", lambda path: {
        "metadata_fingerprint": META, "private": {"per_table_counts": {"Catalogs.X": 3}}})
    monkeypatch.setattr(ner, "readable_fingerprint", lambda c: _fp(PRE, per_table={}))
    connector = lambda: type("C", (), {"Connect": lambda _s, text: conn})()
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, connector, reports=["ДоходыРасходы"])
    assert conn.created == []


def test_run_refuses_an_output_root_inside_the_repository(monkeypatch):
    connector = Mock()
    monkeypatch.setattr(ner, "_reader_password", Mock(side_effect=AssertionError("must not connect")))
    target = ner.REPO_ROOT / "reports" / "native_engine_must_not_exist"
    with pytest.raises(ner.GeneratorRefused):
        ner.run(out_root=target, connector=connector)
    connector.assert_not_called()
    assert not target.exists()


def test_the_default_component_list_and_the_loops_that_use_it():
    common = (ROOT_DIR / "scripts" / "e2e" / "_common.ps1").read_text(encoding="utf-8")
    assert "@('fake1c', 'sidecar', 'idp', 'gateway')" in common
    for name in ("up.ps1", "reset.ps1"):
        text = (ROOT_DIR / "scripts" / "e2e" / name).read_text(encoding="utf-8")
        assert "$script:ProcessComponents" in text or name == "reset.ps1"
        assert "'fake1c'" not in text and "'sidecar'" not in text, name


# ---------------------------------------------------------------- sprint-end review remediation
def test_a_non_rights_error_in_the_preflight_is_inconclusive_and_refuses_the_run(monkeypatch, tmp_path):
    conn = FakeConn()
    conn.Catalogs = type("Cs", (), {"Cat": type("Cat", (), {"CreateItem": lambda _s: (_ for _ in ()).throw(
        RuntimeError("Field 'Description' is required"))})()})()
    session = ner.ReaderSession(conn, ner.PROBE_CLONE.resolve(), ner.READER_USER)
    assert ner.write_denial_preflight(session) == "INCONCLUSIVE_NON_RIGHTS_ERROR"
    assert conn.tx == ["begin", "rollback"]
    run_conn = FakeConn()
    run_conn.Catalogs = conn.Catalogs
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, _patch_run(monkeypatch, run_conn, root=tmp_path), reports=["ДоходыРасходы"])
    assert run_conn.created == []


def test_rights_sweep_records_service_write_rights_without_refusing(monkeypatch, tmp_path):
    conn = FakeConn(rights={("Insert", "Cat"): True, ("Update", "Cat"): True})
    record = _run(tmp_path, _patch_run(monkeypatch, conn, root=tmp_path), reports=["ДоходыРасходы"])
    assert record["reader_write_rights"]["counts"] == {"Insert": 1, "Update": 1, "Delete": 0}
    assert record["reader_write_rights"]["by_kind"] == {"Catalogs": 1}
    assert len(record["reader_write_rights"]["names_sha256"]) == 64


@pytest.mark.parametrize("rights", [
    {("Update", "Doc"): True},
    {("Insert", "Doc"): True},
    {("Administration", "*config"): True},
])
def test_a_reader_that_may_write_documents_or_administer_refuses_the_run(monkeypatch, tmp_path, rights):
    conn = FakeConn(rights=rights)
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, _patch_run(monkeypatch, conn, root=tmp_path), reports=["ДоходыРасходы"])
    assert conn.created == []


def test_a_connect_error_is_wrapped_without_its_text(monkeypatch):
    monkeypatch.setattr(ner, "_reader_password", lambda: "s3cret-pw")

    class Boom:
        def Connect(self, text):
            raise RuntimeError("bad connection string: " + text)

    with pytest.raises(ner.GeneratorRefused) as err:
        ner.connect_reader(ner.REFERENCE_CLONE, connector=lambda: Boom())
    assert "s3cret-pw" not in str(err.value) and err.value.__cause__ is None


def test_the_probe_clone_must_not_resolve_to_the_reference_clone(monkeypatch):
    monkeypatch.setattr(ner, "PROBE_CLONE", ner.REFERENCE_CLONE)
    with pytest.raises(ner.GeneratorRefused):
        ner.connect_reader(ner.REFERENCE_CLONE, connector=Mock())


def test_an_output_root_outside_the_private_root_is_refused(tmp_path):
    with pytest.raises(ner.GeneratorRefused):
        ner.assert_private(tmp_path / "elsewhere")


def test_a_manifest_without_a_baseline_is_refused(monkeypatch, tmp_path):
    conn = FakeConn()
    connector = _patch_run(monkeypatch, conn, root=tmp_path)
    monkeypatch.setattr(ner, "verify_reference_manifest", lambda path: {"metadata_fingerprint": META})
    with pytest.raises(ner.GeneratorRefused):
        _run(tmp_path, connector, reports=["ДоходыРасходы"])
    assert conn.created == []


def test_the_evidence_basis_says_what_was_actually_compared(monkeypatch, tmp_path):
    record = _run(tmp_path, _patch_run(monkeypatch, FakeConn(), root=tmp_path), reports=["ДоходыРасходы"])
    assert "row counts unchanged on 1 readable tables" in record["evidence_basis"]
