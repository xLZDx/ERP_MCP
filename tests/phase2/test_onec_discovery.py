import threading

import pytest

from business_ai_gateway.phase2 import onec_discovery
from business_ai_gateway.phase2.onec_discovery import OneCMetadataDiscovery

XML = (b'<e:Edmx xmlns:e="urn:edmx" xmlns:m="urn:edm"><e:DataServices>'
       b'<m:Schema Namespace="Demo"><m:EntityType Name="Org"/><m:EntityType Name="Secret"/>'
       b'<m:EntityContainer Name="Default"><m:EntitySet Name="Catalog_Orgs" '
       b'EntityType="Demo.Org"/></m:EntityContainer></m:Schema>'
       b'</e:DataServices></e:Edmx>')


async def _audit_ok(event, details):
    return None


def _allow_all(subject, source_id, qualified_name, *, tenant_id):
    return True


def make(allowed, fetch, *, audit=_audit_ok, entity_allowed=_allow_all, **kw):
    return OneCMetadataDiscovery(
        allow_source_metadata=allowed, fetch_registered_metadata=fetch,
        audit=audit, entity_allowed=entity_allowed, **kw,
    )


async def _fetch_xml(source, max_bytes, *, tenant_id):
    return XML


async def _allow(subject, source, *, tenant_id):
    return True


@pytest.mark.asyncio
async def test_allowlisted_source_only_and_observed_only():
    calls = []

    async def allowed(subject, source, *, tenant_id):
        calls.append(("auth", subject, source))
        return subject == "auditor" and source == "onec-reference"

    async def fetch(source, max_bytes, *, tenant_id):
        calls.append(("read", source, max_bytes))
        return XML

    client = make(allowed, fetch)
    result = await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                                  tenant_id="t1")
    assert result.trust == "OBSERVED_ONLY"
    assert result.fingerprint.structural_sha256
    assert (result.fingerprint.tenant_id, result.fingerprint.source_id) == ("t1", "onec-reference")
    assert calls == [("auth", "auditor", "onec-reference"),
                     ("read", "onec-reference", 20_000_000)]


@pytest.mark.asyncio
async def test_size_limit_is_passed_to_fetch_contract():
    seen = []

    async def fetch(source, max_bytes, *, tenant_id):
        seen.append(max_bytes)
        return XML

    client = make(_allow, fetch, max_metadata_bytes=1_000_000)
    await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                         tenant_id="t1")
    assert seen == [1_000_000]


@pytest.mark.asyncio
async def test_company_reader_without_source_grant_never_dispatches():
    calls = []

    async def denied(subject, source, *, tenant_id):
        return False

    async def fetch(source, max_bytes, *, tenant_id):
        calls.append(source)
        return XML

    audits = []

    async def audit(event, details):
        audits.append(event)

    client = make(denied, fetch, audit=audit)
    with pytest.raises(PermissionError, match="SOURCE_METADATA_ACCESS_DENIED"):
        await client.observe(authenticated_subject="company_user", source_id="onec-reference",
                             tenant_id="t1")
    assert calls == []
    assert audits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("acl_result", [1, "yes", object(), None, [True]])
async def test_acl_result_must_be_exactly_true(acl_result):
    calls = []

    async def allowed(subject, source, *, tenant_id):
        return acl_result

    async def fetch(source, max_bytes, *, tenant_id):
        calls.append(source)
        return XML

    client = make(allowed, fetch)
    with pytest.raises(PermissionError, match="SOURCE_METADATA_ACCESS_DENIED"):
        await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                             tenant_id="t1")
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", [None, 7, b"onec-reference", ["onec-reference"], ""])
async def test_non_string_source_id_is_permission_error_not_type_error(source_id):
    calls = []

    async def allowed(subject, source, *, tenant_id):
        calls.append("auth")
        return True

    client = make(allowed, _fetch_xml)
    with pytest.raises(PermissionError, match="INVALID_SCOPE"):
        await client.observe(authenticated_subject="auditor", source_id=source_id,
                             tenant_id="t1")
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("subject,tenant", [("", "t1"), (None, "t1"), ("auditor", ""),
                                            ("auditor", None), (5, "t1")])
async def test_invalid_subject_or_tenant_is_permission_error(subject, tenant):
    client = make(_allow, _fetch_xml)
    with pytest.raises(PermissionError, match="INVALID_SCOPE"):
        await client.observe(authenticated_subject=subject, source_id="onec-reference",
                             tenant_id=tenant)


@pytest.mark.asyncio
async def test_arbitrary_url_denied_before_authorization():
    calls = []

    async def allowed(subject, source, *, tenant_id):
        calls.append("auth")
        return True

    async def fetch(source, max_bytes, *, tenant_id):
        calls.append("read")
        return XML

    client = make(allowed, fetch)
    with pytest.raises(PermissionError, match="INVALID_SCOPE"):
        await client.observe(authenticated_subject="auditor", source_id="http://evil.test/",
                             tenant_id="t1")
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_metadata_not_observed_or_accepted():
    async def fetch(source, max_bytes, *, tenant_id):
        return b"<html>gateway error</html>"

    client = make(_allow, fetch)
    with pytest.raises(ValueError, match="NOT_EDMX"):
        await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                             tenant_id="t1")


@pytest.mark.asyncio
async def test_oversized_metadata_fails_closed():
    client = make(_allow, _fetch_xml, max_metadata_bytes=15)
    with pytest.raises(ValueError, match="EDMX_SIZE_INVALID"):
        await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                             tenant_id="t1")


@pytest.mark.asyncio
async def test_fingerprint_runs_off_the_event_loop_thread(monkeypatch):
    main_thread = threading.get_ident()
    seen = []
    real = onec_discovery.fingerprint_edmx

    def spy(*args, **kwargs):
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(onec_discovery, "fingerprint_edmx", spy)
    client = make(_allow, _fetch_xml)
    await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                         tenant_id="t1")
    assert len(seen) == 1
    assert seen[0] != main_thread


@pytest.mark.asyncio
async def test_audit_written_before_adapter_is_called():
    order = []

    async def audit(event, details):
        order.append(("audit", event, dict(details)))

    async def fetch(source, max_bytes, *, tenant_id):
        order.append(("fetch",))
        return XML

    client = make(_allow, fetch, audit=audit)
    await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                         tenant_id="t1")
    assert [o[0] for o in order] == ["audit", "fetch"]
    assert order[0][1] == "onec.metadata.fetch"
    assert order[0][2] == {"subject": "auditor", "tenant_id": "t1", "source_id": "onec-reference"}


@pytest.mark.asyncio
async def test_audit_write_failure_is_fail_closed():
    calls = []

    async def audit(event, details):
        raise OSError("audit sink down")

    async def fetch(source, max_bytes, *, tenant_id):
        calls.append(source)
        return XML

    client = make(_allow, fetch, audit=audit)
    with pytest.raises(PermissionError, match="AUDIT_WRITE_FAILED") as info:
        await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                             tenant_id="t1")
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert calls == []


def test_audit_and_entity_callbacks_are_mandatory():
    with pytest.raises(TypeError):
        OneCMetadataDiscovery(allow_source_metadata=_allow, fetch_registered_metadata=_fetch_xml)
    with pytest.raises(TypeError, match="CALLBACKS"):
        make(_allow, _fetch_xml, audit=None)
    with pytest.raises(TypeError, match="CALLBACKS"):
        make(_allow, _fetch_xml, entity_allowed=None)


@pytest.mark.asyncio
async def test_objects_are_filtered_by_entity_allowed_before_return():
    asked = []

    def entity_allowed(subject, source_id, qualified_name, *, tenant_id):
        asked.append((subject, source_id, qualified_name))
        return "Secret" not in qualified_name

    client = make(_allow, _fetch_xml, entity_allowed=entity_allowed)
    result = await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                                  tenant_id="t1")
    names = [name for name, _ in result.fingerprint.objects]
    assert "Demo::EntityType::Org" in names
    assert not any("Secret" in n for n in names)
    assert result.withheld_objects == 1
    assert all(s == ("auditor", "onec-reference") for s in [(a[0], a[1]) for a in asked])
    assert "Secret" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", [1, "yes", None, object()])
async def test_entity_allowed_result_must_be_exactly_true(verdict):
    client = make(_allow, _fetch_xml, entity_allowed=lambda s, src, n, *, tenant_id: verdict)
    result = await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                                  tenant_id="t1")
    assert result.fingerprint.objects == ()
    assert result.withheld_objects > 0


@pytest.mark.asyncio
async def test_tenant_is_passed_to_every_callback():
    seen = []

    async def allowed(subject, source, *, tenant_id):
        seen.append(("allow", tenant_id))
        return True

    async def fetch(source, max_bytes, *, tenant_id):
        seen.append(("fetch", tenant_id))
        return XML

    def entity(subject, source, name, *, tenant_id):
        seen.append(("entity", tenant_id))
        return True

    await make(allowed, fetch, entity_allowed=entity).observe(
        authenticated_subject="auditor", source_id="onec-reference", tenant_id="t1")
    assert {t for _, t in seen} == {"t1"}
    assert {k for k, _ in seen} == {"allow", "fetch", "entity"}


@pytest.mark.asyncio
async def test_grant_for_other_tenant_is_denied_without_fetch():
    calls = []

    async def allowed(subject, source, *, tenant_id):
        return (tenant_id, source) == ("t1", "onec-reference")

    async def fetch(source, max_bytes, *, tenant_id):
        calls.append(tenant_id)
        return XML

    client = make(allowed, fetch)
    with pytest.raises(PermissionError, match="SOURCE_METADATA_ACCESS_DENIED"):
        await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                             tenant_id="t2")
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant,source", [(" t1", "onec-reference"), ("t1 ", "onec-reference"),
                                           ("t1", "onec-reference "), ("  ", "onec-reference")])
async def test_unstripped_scope_is_invalid_before_audit_and_fetch(tenant, source):
    calls = []

    async def audit(event, details):
        calls.append("audit")

    async def fetch(source_id, max_bytes, *, tenant_id):
        calls.append("fetch")
        return XML

    with pytest.raises(PermissionError, match="INVALID_SCOPE"):
        await make(_allow, fetch, audit=audit).observe(
            authenticated_subject="auditor", source_id=source, tenant_id=tenant)
    assert calls == []


@pytest.mark.asyncio
async def test_filtered_view_is_partial_and_hides_whole_document_hashes():
    from business_ai_gateway.phase2.structural_hash import fingerprint_edmx
    full = fingerprint_edmx(XML, tenant_id="t1", source_id="onec-reference")
    client = make(_allow, _fetch_xml,
                  entity_allowed=lambda s, src, n, *, tenant_id: "Secret" not in n)
    result = await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                                  tenant_id="t1")
    fp = result.fingerprint
    assert result.completeness == "PARTIAL_ACL_FILTERED"
    assert fp.acl_filtered and fp.withheld_count == 1
    assert {fp.raw_sha256, fp.structural_sha256, fp.residual_sha256}.isdisjoint(
        {full.raw_sha256, full.structural_sha256, full.residual_sha256})
    unfiltered = await make(_allow, _fetch_xml).observe(
        authenticated_subject="auditor", source_id="onec-reference", tenant_id="t1")
    assert unfiltered.completeness == "COMPLETE" and not unfiltered.fingerprint.acl_filtered


@pytest.mark.asyncio
async def test_visible_and_hidden_change_together_is_unknown_impact():
    from business_ai_gateway.phase2.structural_diff import diff_observed
    xml2 = XML.replace(b'Name="Org"', b'Name="Org" Abstract="true"').replace(
        b'Name="Secret"', b'Name="Secret" Abstract="true"')
    state = {"xml": XML}

    async def fetch(source, max_bytes, *, tenant_id):
        return state["xml"]

    client = make(_allow, fetch, entity_allowed=lambda s, src, n, *, tenant_id: "Secret" not in n)
    kw = {"authenticated_subject": "auditor", "source_id": "onec-reference", "tenant_id": "t1"}
    before = (await client.observe(**kw)).fingerprint
    state["xml"] = xml2
    after = (await client.observe(**kw)).fingerprint
    diff = diff_observed(before, after)
    assert diff.has_changes and diff.unattributed_structural_change is True


@pytest.mark.asyncio
async def test_fetch_timeout_has_stable_code():
    import asyncio

    async def slow(source, max_bytes, *, tenant_id):
        await asyncio.sleep(5)
        return XML

    client = make(_allow, slow, fetch_timeout_seconds=0.05)
    with pytest.raises(onec_discovery.OneCFetchError) as info:
        await client.observe(authenticated_subject="auditor", source_id="onec-reference",
                             tenant_id="t1")
    assert info.value.code == "ONEC_FETCH_TIMEOUT"


@pytest.mark.asyncio
async def test_hanging_audit_or_acl_callback_fails_closed():
    import asyncio

    async def hang_audit(event, details):
        await asyncio.sleep(5)

    async def hang_allow(subject, source, *, tenant_id):
        await asyncio.sleep(5)

    with pytest.raises(PermissionError, match="AUDIT_WRITE_FAILED"):
        await make(_allow, _fetch_xml, audit=hang_audit, callback_timeout_seconds=0.05).observe(
            authenticated_subject="auditor", source_id="onec-reference", tenant_id="t1")
    with pytest.raises(PermissionError, match="SOURCE_METADATA_ACCESS_DENIED"):
        await make(hang_allow, _fetch_xml, callback_timeout_seconds=0.05).observe(
            authenticated_subject="auditor", source_id="onec-reference", tenant_id="t1")
