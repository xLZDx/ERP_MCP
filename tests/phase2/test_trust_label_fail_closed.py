"""Guard against promoting offline comparison/observation metadata by construction."""
import pytest

from business_ai_gateway.phase2.purchase_reconciliation import (
    PurchaseComparison,
    PurchaseResultKind,
)
from business_ai_gateway.phase2.reconciliation import Comparison, ComparisonState
from business_ai_gateway.phase2.structural_diff import (
    ChangeKind,
    ObjectChange,
    ObservedDiff,
)


@pytest.mark.parametrize("authority", ["VALIDATED", "NATIVE_PASS", ""])
def test_trial_balance_comparison_cannot_forge_authority(authority):
    with pytest.raises(ValueError, match="RECONCILIATION_AUTHORITY_FORBIDDEN"):
        Comparison(ComparisonState.MATCH, "ROWS_EQUAL", "policy-1", (), authority=authority)


@pytest.mark.parametrize("authority", ["VALIDATED", "NATIVE_PASS", ""])
def test_purchase_comparison_cannot_forge_authority(authority):
    with pytest.raises(ValueError, match="PURCHASE_AUTHORITY_FORBIDDEN"):
        PurchaseComparison(PurchaseResultKind.MATCH, "POSTED_DOCUMENTS_EQUAL", authority=authority)


@pytest.mark.parametrize("trust", ["VALIDATED", "ACCEPTED", ""])
def test_observed_diff_cannot_forge_trust_level(trust):
    with pytest.raises(ValueError, match="PHASE2_TRUST_LEVEL_FORBIDDEN"):
        ObservedDiff(
            tenant_id="tenant-a", source_id="source-a",
            canonicalizer_version="edmx-structural-v2",
            previous_raw_sha256="a" * 64, observed_raw_sha256="b" * 64,
            previous_structural_sha256="a" * 64,
            observed_structural_sha256="b" * 64,
            changes=(ObjectChange("Purchase", ChangeKind.MODIFIED, "a" * 64, "b" * 64),),
            unattributed_structural_change=False,
            trust_level=trust,
        )

class _AlwaysEqual:
    def __eq__(self, _other):
        return True

    def __ne__(self, _other):
        return False


def test_nonstring_trust_spoof_cannot_promote_numeric_comparison():
    with pytest.raises(ValueError, match="RECONCILIATION_AUTHORITY_FORBIDDEN"):
        Comparison(ComparisonState.MATCH, "ROWS_EQUAL", "policy-1", (),
                   authority=_AlwaysEqual())


def test_nonstring_trust_spoof_cannot_promote_purchase_comparison():
    with pytest.raises(ValueError, match="PURCHASE_AUTHORITY_FORBIDDEN"):
        PurchaseComparison(PurchaseResultKind.MATCH, "POSTED_DOCUMENTS_EQUAL",
                           authority=_AlwaysEqual())


def test_nonstring_trust_spoof_cannot_promote_observed_diff():
    with pytest.raises(ValueError, match="PHASE2_TRUST_LEVEL_FORBIDDEN"):
        ObservedDiff(
            tenant_id="tenant-a", source_id="source-a",
            canonicalizer_version="edmx-structural-v2",
            previous_raw_sha256="a" * 64, observed_raw_sha256="b" * 64,
            previous_structural_sha256="a" * 64, observed_structural_sha256="b" * 64,
            changes=(ObjectChange("Purchase", ChangeKind.MODIFIED, "a" * 64, "b" * 64),),
            unattributed_structural_change=False,
            trust_level=_AlwaysEqual(),
        )
