import pytest

from business_ai_gateway.compatibility import (
    MetadataDriftUnacknowledged,
    require_acknowledged_metadata,
)


def test_reads_allow_stable_metadata_and_legacy_unknown_state():
    require_acknowledged_metadata({"drift_status": "STABLE"})
    require_acknowledged_metadata({"drift_status": "UNKNOWN"})
    require_acknowledged_metadata({})


def test_reads_fail_closed_until_metadata_drift_is_acknowledged():
    with pytest.raises(MetadataDriftUnacknowledged, match="fingerprint changed"):
        require_acknowledged_metadata({"drift_status": "DRIFTED"})
