import pytest

from business_ai_gateway.models import Source


def make_source(**overrides):
    data = {
        "id": "s1",
        "project": "onec",
        "kind": "onec_odata",
        "display_name": "Company",
        "base_url": "https://1c.example.com/base/odata/standard.odata",
        "username_secret_ref": "u",
        "password_secret_ref": "p",
        "read_only": True,
        "enabled": True,
        "tags": (),
        "entity_allow_patterns": ("Catalog_*", "Document_*"),
        "entity_deny_patterns": ("Document_Secret*",),
    }
    data.update(overrides)
    return Source(**data)


def test_source_is_read_only_and_https_in_production():
    make_source().validate_runtime(production=True)
    with pytest.raises(ValueError):
        make_source(read_only=False).validate_runtime(production=True)
    with pytest.raises(ValueError):
        make_source(
            base_url="http://1c.example.com/odata"
        ).validate_runtime(production=True)


def test_source_host_must_match_explicit_production_allowlist():
    source = make_source()
    source.validate_runtime(
        production=True, allowed_source_hosts=("1c.example.com",)
    )
    with pytest.raises(ValueError, match="BAG_SOURCE_HOST_ALLOWLIST"):
        source.validate_runtime(
            production=True, allowed_source_hosts=("other.example.com",)
        )


def test_entity_policy_deny_wins():
    source = make_source()
    assert source.entity_allowed("Catalog_Organizations")
    assert not source.entity_allowed("Document_SecretPayroll")
    assert not source.entity_allowed("InformationRegister_X")
