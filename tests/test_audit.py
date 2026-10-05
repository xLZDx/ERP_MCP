from business_ai_gateway.audit import query_fingerprint


def test_audit_fingerprint_is_stable_and_hides_raw_query():
    one = query_fingerprint({"filter": "INN eq '123'"})
    two = query_fingerprint({"filter": "INN eq '123'"})
    assert one == two
    assert "123" not in one
    assert len(one) == 64
