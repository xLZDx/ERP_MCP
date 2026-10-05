from business_ai_gateway.adapters.onec.atom import parse_atom_payload
from testbed.fake1c.app import _atom


def test_atom_payload_normalizes_to_value_rows():
    payload = _atom([{"Code": "A", "Description": "Alpha", "Empty": None}])
    parsed = parse_atom_payload(payload)
    assert parsed == {
        "value": [{"Code": "A", "Description": "Alpha", "Empty": None}]
    }
