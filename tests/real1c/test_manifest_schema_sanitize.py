from __future__ import annotations

import copy
import json

import pytest

from scripts.real1c.manifest import (
    FingerprintDrift,
    ManifestGateError,
    canonical_json,
    check_post_run,
    manifest_hash,
    sanitized_summary,
    verify_reference_manifest,
)
from scripts.real1c.sanitize import redact_text, scan_for_secrets, sha256_hex
from scripts.real1c.schema import validate_case_result

H = "b" * 64


def _manifest():
    m = {
        "golden": {"sha256": H, "size_bytes": 1234, "source_date": "2026-09-15"},
        "chain": ["GOLDEN", "RO clone", "probe clone"],
        "platform_version": "8.3.24.1",
        "configuration": {"name": "Accounting Moldova", "version": "3.0.1"},
        "metadata_fingerprint": H,
        "odata_identity_sha256": H,
        "organisations": [{"ref_sha256": H, "name": "818 HA SRL"}],
        "pre_run_fingerprint": {"sha256": H, "table_count": 42},
        "git_sha": "c" * 40,
    }
    m["manifest_sha256"] = manifest_hash(m)
    return m


def _write(tmp_path, m):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m), "utf-8")
    return p


def test_canonical_json_is_sorted_compact_unicode():
    assert canonical_json({"b": 1, "a": "я"}) == '{"a":"я","b":1}'.encode()


def test_manifest_hash_ignores_own_key():
    m = _manifest()
    assert manifest_hash(m) == manifest_hash({**m, "manifest_sha256": "zzz"})


def test_valid_manifest_passes(tmp_path):
    m = _manifest()
    assert verify_reference_manifest(_write(tmp_path, m), expected_git_sha="c" * 40) == m


def test_missing_path_and_none_and_garbage(tmp_path):
    with pytest.raises(ManifestGateError):
        verify_reference_manifest(None)
    with pytest.raises(ManifestGateError):
        verify_reference_manifest(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", "utf-8")
    with pytest.raises(ManifestGateError):
        verify_reference_manifest(bad)


def test_tampered_hash_raises(tmp_path):
    m = _manifest()
    m["platform_version"] = "8.3.99"
    with pytest.raises(ManifestGateError, match="does not match"):
        verify_reference_manifest(_write(tmp_path, m))


@pytest.mark.parametrize(
    "key",
    ["golden", "chain", "platform_version", "configuration", "metadata_fingerprint",
     "odata_identity_sha256", "organisations", "pre_run_fingerprint"],
)  # fmt: skip
def test_missing_key_raises(tmp_path, key):
    m = _manifest()
    del m[key]
    m["manifest_sha256"] = manifest_hash(m)
    with pytest.raises(ManifestGateError, match=key):
        verify_reference_manifest(_write(tmp_path, m))


def test_short_chain_and_wrong_git_sha(tmp_path):
    m = _manifest()
    m["chain"] = ["GOLDEN", "RO clone"]
    m["manifest_sha256"] = manifest_hash(m)
    with pytest.raises(ManifestGateError, match="chain"):
        verify_reference_manifest(_write(tmp_path, m))
    with pytest.raises(ManifestGateError, match="git"):
        verify_reference_manifest(_write(tmp_path, _manifest()), expected_git_sha="d" * 40)


def test_post_run_drift():
    pre = {"sha256": H, "table_count": 1}
    check_post_run(pre, {"sha256": H, "table_count": 1})
    with pytest.raises(FingerprintDrift):
        check_post_run(pre, {"sha256": "c" * 64})


def test_sanitized_summary_has_no_names_or_raw_refs():
    m = _manifest()
    s = sanitized_summary(m)
    blob = json.dumps(s)
    assert "818 HA" not in blob and "Accounting Moldova" not in blob
    assert s["manifest_sha256"] == m["manifest_sha256"]
    assert s["organisation_count"] == 1 and s["configuration_version"] == "3.0.1"


# schema


def _result(**over):
    r = {
        "schema_version": 1, "case_id": "ST-010", "kind": "ST", "title": "t",
        "catalogue_class": "RR", "disposition": "PASS", "reason_code": "oracle_match",
        "evidence_classes": ["GATEWAY_OBSERVATION"],
        "observations": [{"probe": "p", "outcome": "o", "detail": "d"}],
        "tools_called": ["APR"], "oracle": "ONAT", "git_sha": "a" * 40,
        "manifest_sha256": H, "finished_at": "2026-10-07T10:00:00Z",
    }  # fmt: skip
    r.update(over)
    return r


def test_schema_valid_result():
    assert validate_case_result(_result()) == []


def test_schema_missing_and_bad_values():
    r = _result()
    del r["oracle"]
    assert validate_case_result(r) == ["missing key: oracle"]
    assert validate_case_result(_result(schema_version=2))
    assert validate_case_result(_result(kind="ZZ"))
    assert validate_case_result(_result(disposition="MAYBE"))
    assert validate_case_result(_result(git_sha="abc"))
    assert validate_case_result(_result(evidence_classes=["BOGUS"]))
    assert validate_case_result(_result(catalogue_class=None))
    assert validate_case_result(_result(kind="NR", catalogue_class=None, disposition="EVIDENCE_REQUIRED")) == []
    assert "PASS is allowed only for catalogue_class RR" in validate_case_result(_result(kind="NR", catalogue_class=None))
    assert "PASS is allowed only for catalogue_class RR" in validate_case_result(_result(catalogue_class="EV"))


def test_schema_pass_needs_observation_and_real_evidence():
    assert validate_case_result(_result(observations=[]))
    assert validate_case_result(_result(evidence_classes=["NONE"]))
    assert not validate_case_result(_result(disposition="INCONCLUSIVE", observations=[]))


def test_schema_com_query_cannot_claim_validated():
    ok = _result(evidence_classes=["NATIVE_COM_QUERY"])
    assert validate_case_result(ok) == []
    bad = copy.deepcopy(ok)
    bad["observations"][0]["detail"] = "profile validated by COM query"
    assert validate_case_result(bad)


# sanitize


def test_redacts_guid_secret_and_headers():
    g = "123e4567-e89b-12d3-a456-426614174000"
    out = redact_text(f"ref {g} password=hunter2 Authorization: Basic QWRtaW46cGFzcw==")
    assert g not in out and "hunter2" not in out and "QWRtaW46" not in out
    assert "guid:" + sha256_hex(g)[:8] in out
    assert "Bearer <redacted>" in redact_text("Authorization: Bearer abc.def.ghi123")
    assert "user:pw" not in redact_text("http://user:pw@host/x")
    assert "<secret-path>" in redact_text(r"see D:\secrets\one\blob.bin now")
    assert "AAAA1111BBBB2222CCCC" not in redact_text("key: AAAA1111BBBB2222CCCC")


def test_scan_finds_planted_secrets():
    assert "credential_assignment" in scan_for_secrets("x password=hunter2 y")
    assert "admin_credential" in scan_for_secrets("Admin_1C login, password: s3cret")
    assert "basic_auth_header" in scan_for_secrets("Authorization: Basic QWRtaW46cGFzcw==")
    assert "url_userinfo" in scan_for_secrets("https://u:p@example/x")
    assert scan_for_secrets("clean text, Admin_1C class identity rejected") == []
    assert scan_for_secrets(r"blob stored at D:\secrets\dpapi\token.bin") == []


def test_post_run_check_rejects_malformed_fingerprints():
    with pytest.raises(FingerprintDrift):
        check_post_run({"sha256": "zzz"}, {"sha256": "zzz"})


@pytest.mark.parametrize("text", ['{"password": "hunter2"}', "{'client_secret': 'abc123xyz'}", '"token":"abcdef"'])
def test_quoted_credential_pairs_are_detected_and_redacted(text):
    assert "quoted_credential_pair" in scan_for_secrets(text)
    assert "hunter2" not in redact_text(text) and "abc123xyz" not in redact_text(text) and "abcdef" not in redact_text(text)
