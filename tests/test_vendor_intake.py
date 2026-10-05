import json
from pathlib import Path


MANIFEST = Path("vendor/intake.json")


def test_vendor_intake_is_pinned_and_unique():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["policy"] == "reuse-before-rewrite"

    identities = set()
    for source in data["sources"]:
        identity = (source["repo"], source.get("subpath"))
        assert identity not in identities
        identities.add(identity)

        sha = source["sha"]
        assert len(sha) == 40
        assert all(char in "0123456789abcdef" for char in sha)
        assert source["roles"]


def test_restrictive_licenses_cannot_be_ported_into_core():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    for source in data["sources"]:
        license_name = source["license"]
        mode = source["mode"]

        if license_name == "GPL-3.0":
            assert mode == "isolated-service-only"
        elif license_name == "UNVERIFIED":
            assert mode == "reference-only"


def test_primary_protocol_sources_are_present():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    repos = {source["repo"] for source in data["sources"]}

    assert "hacker-cb/1c-odata" in repos
    assert "prepod2003/mcp-rsv-data" in repos
    assert "theYahia/WWmcp" in repos
