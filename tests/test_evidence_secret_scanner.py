import pytest

from scripts.scan_sensitive_artifacts import scan


@pytest.mark.parametrize("payload", [
    '{"password":"test-only-credential"}',
    '{"client_secret": "test-only-credential"}',
    "Authorization:Bearer short",
    "Authorization:   Bearer short",
    "Cookie:session=test-only-credential",
    '{"dsn":"postgresql://synthetic:fixture@db/example"}',
])
def test_scanner_detects_secret_fields_without_exposing_value(tmp_path, payload):
    artifact = tmp_path / "evidence.json"
    artifact.write_text(payload, encoding="utf-8")
    assert scan([artifact]) == [str(artifact)]


@pytest.mark.parametrize("payload", [
    "Authorization: [REDACTED]", "Authorization:   [REDACTED]",
    '{"authorization":"[REDACTED]"}', '{"status":"NOT_RUN"}',
])
def test_scanner_accepts_redaction_with_variable_whitespace(tmp_path, payload):
    artifact = tmp_path / "evidence.json"
    artifact.write_text(payload, encoding="utf-8")
    assert scan([artifact]) == []
