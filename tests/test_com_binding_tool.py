"""The operator helper never approves a binding and agrees with the gateway's own derivations."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from business_ai_gateway.analytics_balance import (
    ComBinding,
    configuration_fingerprint,
    load_com_bindings,
    validate_binding,
)
from business_ai_gateway.evidence_store import PrivateEvidenceStore, _write_new
from scripts.real1c import com_binding_tool as tool

BASE_URL = "http://1c.example.invalid/base/odata/standard.odata"
COMPANY = "f3727523-9689-4b73-973e-9754360fd0a0"
META = "a" * 64


@pytest.fixture
def private_dir(tmp_path):
    return PrivateEvidenceStore.create(tmp_path)._root


def argv(out, **over):
    values = {
        "--out": str(out), "--source-id": "source-1", "--binding-id": "bind-1", "--version": "1",
        "--base-url": BASE_URL, "--credential-identity": "reader-ref", "--clone-identity": "clone-A",
        "--platform-version": "8.3.27.2342", "--metadata-fingerprint": META, "--company": COMPANY,
    }
    values.update(over)
    return ["draft", *[item for pair in values.items() for item in pair]]


def test_draft_is_revoked_loadable_and_never_overwrites(private_dir):
    out = private_dir / "bindings.json"
    assert tool.main(argv(out)) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    (record,) = document["bindings"]
    assert record["status"] == "REVOKED"
    (binding,) = load_com_bindings(out, hashlib.sha256(out.read_bytes()).hexdigest())
    assert isinstance(binding, ComBinding) and binding.status == "REVOKED"
    with pytest.raises(FileExistsError):
        tool.main(argv(out))


def test_derived_values_match_the_gateway_formulas(private_dir):
    out = private_dir / "bindings.json"
    tool.main(argv(out))
    (binding,) = load_com_bindings(out, hashlib.sha256(out.read_bytes()).hexdigest())
    caps = SimpleNamespace(platform_version="8.3.27.2342", adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                           metadata_fingerprint=META)
    assert binding.configuration_fingerprint == configuration_fingerprint(caps)
    assert binding.source_base_url_sha256 == hashlib.sha256(BASE_URL.encode()).hexdigest()
    source = SimpleNamespace(id="source-1", base_url=BASE_URL, username_secret_ref="reader-ref")
    # a draft is revoked, so the gateway refuses it until the operator approves it by hand
    with pytest.raises(Exception, match="COM_BINDING_NOT_APPROVED"):
        validate_binding(binding, source=source, capabilities=caps, company_external_ref=COMPANY)
    approved = ComBinding(**{name: getattr(binding, name) for name in ComBinding.__dataclass_fields__}
                          | {"status": "APPROVED"})
    validate_binding(approved, source=source, capabilities=caps, company_external_ref=COMPANY)


def test_pin_prints_the_file_digest_and_refuses_an_invalid_file(private_dir, capsys):
    out = private_dir / "bindings.json"
    tool.main(argv(out))
    capsys.readouterr()  # drop the draft message
    assert tool.main(["pin", "--file", str(out)]) == 0
    assert capsys.readouterr().out.strip() == hashlib.sha256(out.read_bytes()).hexdigest()
    bad = private_dir / "bad.json"
    _write_new(bad, b'{"schema_version": 1, "bindings": [{}]}')
    with pytest.raises(Exception, match="COM_BINDINGS_INVALID"):
        tool.main(["pin", "--file", str(bad)])


def test_missing_platform_version_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(argv(tmp_path / "x.json", **{"--platform-version": ""}))
