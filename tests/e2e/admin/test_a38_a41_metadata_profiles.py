"""A38-A41: metadata refresh evidence, failure handling, stale profiles, unknown capabilities.

Fake1C is stopped, or replaced by a read-only stand-in on its port, only inside
``outage`` / ``fake1c_replaced_by`` / ``drifted_fake1c`` blocks that always restore it.
"""

from __future__ import annotations

import pytest
from admin_support import (
    drifted_fake1c,
    expect,
    fake1c_replaced_by,
    outage,
    recorder_app,
    resync_capabilities,
    unique,
)

pytestmark = [pytest.mark.admin]

FAKE1C_ENTITY_SETS = 10


def _caps_row(evidence, source_id):
    return evidence.one("SELECT * FROM bag.source_capabilities WHERE source_id=$1", source_id)


def _profile_status(evidence, profile_id):
    import uuid

    return evidence.scalar("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1",
                           uuid.UUID(profile_id))


# --------------------------------------------------------------------------------------- A38
def test_A38_refresh_records_fingerprint_from_observed_metadata(e2e_env, world, evidence):
    world.need("source", "caps")
    pa = world.pa
    observed = expect(pa.post("/admin/v1/source-probes", {
        "base_url": e2e_env.fake1c_url, "username_secret_ref": "FAKE1C_USERNAME",
        "password_secret_ref": "FAKE1C_PASSWORD"}), 200, "A38 independent probe")
    before = _caps_row(evidence, world.source_id)
    refreshed = expect(pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                               {"reason": "A38 refresh"}), 200, "A38 refresh")
    row = _caps_row(evidence, world.source_id)
    fingerprint = refreshed.body["metadata_fingerprint"]
    assert fingerprint and fingerprint == row["metadata_fingerprint"], (
        "response and stored fingerprint differ")
    assert fingerprint == observed.body["capabilities"]["metadata_fingerprint"], (
        "stored fingerprint is not the one derived from the metadata the source serves")
    assert row["metadata_supported"] is True and row["entity_set_count"] == FAKE1C_ENTITY_SETS
    assert row["discovered_at"] >= before["discovered_at"]
    audit = evidence.admin_events(refreshed)
    assert len(audit) == 1 and audit[0]["action"] == "capability.refresh"
    assert audit[0]["outcome"] == "success" and audit[0]["source_id"] == world.source_id
    assert not world.ev.rows("SELECT 1 FROM bag.source_capabilities WHERE source_id=$1 AND "
                             "metadata_fingerprint IS NULL", world.source_id)


# --------------------------------------------------------------------------------------- A39
@pytest.mark.parametrize("mode", ["fake1c-down", "broken-metadata"])
def test_A39_refresh_failure_recorded_without_invented_fingerprint(e2e_env, world, evidence,
                                                                    mode):
    world.need("source", "caps")
    before = _caps_row(evidence, world.source_id)
    assert before["metadata_fingerprint"], "precondition: previous capability evidence exists"
    try:
        if mode == "fake1c-down":
            context = outage(e2e_env, "fake1c")
        else:
            context = fake1c_replaced_by(e2e_env, lambda: recorder_app([], broken=True))
        with context:
            failed = world.pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                                   {"reason": f"A39 refresh while {mode}"})
        after = _caps_row(evidence, world.source_id)
        audit = evidence.admin_events(failed)
    finally:
        # A product that accepted the broken metadata leaves DRIFTED evidence behind; restore
        # STABLE evidence so later rows are not poisoned by this one.
        resync_capabilities(world)
    assert failed.status >= 400, f"refresh must fail while {mode}: {failed.describe()}"
    assert set(failed.body) == {"error"}, f"unsanitized failure body: {failed.describe()}"
    for secret in e2e_env.secrets.get("fake1c_password", ""), e2e_env.secrets["fake1c_username"]:
        assert secret not in failed.text
    assert after["metadata_fingerprint"] == before["metadata_fingerprint"], (
        "fingerprint changed by a failed refresh")
    assert after["discovered_at"] == before["discovered_at"], "failed refresh rewrote evidence"
    assert after["drift_status"] == before["drift_status"]
    assert audit and audit[0]["outcome"] == "error", f"failure not recorded: {audit}"
    assert audit[0]["action"] == "capability.refresh" and audit[0]["detail_code"]
    recovered = expect(world.pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                                     {"reason": "A39 recovery"}), 200, "A39 recovery refresh")
    assert recovered.body["metadata_fingerprint"] == before["metadata_fingerprint"]


# --------------------------------------------------------------------------------------- A40
def test_A40_stale_profile_cannot_be_validated_or_acknowledged(e2e_env, world, evidence):
    world.need("source", "caps", "roles")
    pra, pa = world.role_session("PROFILE_ADMIN"), world.pa
    original_fp = _caps_row(evidence, world.source_id)["metadata_fingerprint"]
    draft = expect(world.create_profile(pra, world.source_id), 201, "A40 draft profile").body["id"]
    expect(world.add_mapping(pra, draft), 201, "A40 draft mapping")
    try:
        with drifted_fake1c(e2e_env):
            drifted = expect(pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                                     {"reason": "A40 observe drifted metadata"}), 200,
                             "A40 refresh against changed metadata")
            drift_row = _caps_row(evidence, world.source_id)
            assert drift_row["drift_status"] == "DRIFTED", drift_row["drift_status"]
            new_fp = drift_row["metadata_fingerprint"]
            assert new_fp != original_fp == drift_row["previous_metadata_fingerprint"], drifted.text

            # Validation while drift is unacknowledged is rejected.
            blocked = world.validate_profile(pra, draft)
            assert blocked.status in (400, 409), blocked.describe()
            # Acknowledging a fingerprint that is not the current one is rejected.
            stale_ack = pa.post(f"/admin/v1/sources/{world.source_id}/drift-acknowledgements", {
                "expected_fingerprint": original_fp, "reason": "A40 stale acknowledgement"})
            assert stale_ack.status == 409, stale_ack.describe()
            assert _caps_row(evidence, world.source_id)["drift_status"] == "DRIFTED", (
                "a stale fingerprint acknowledged the drift")
            audit = evidence.admin_events(stale_ack)
            assert audit and audit[0]["outcome"] == "conflict"
            # The exact current fingerprint is accepted, and only then.
            expect(pa.post(f"/admin/v1/sources/{world.source_id}/drift-acknowledgements", {
                "expected_fingerprint": new_fp, "reason": "A40 acknowledge exact drift"}), 200,
                "A40 exact acknowledgement")
            replayed_ack = pa.post(f"/admin/v1/sources/{world.source_id}/drift-acknowledgements",
                                   {"expected_fingerprint": new_fp, "reason": "A40 second ack"})
            assert replayed_ack.status == 409, "acknowledging stable metadata must conflict"

            # The draft profile was built on the old fingerprint: validation is rejected.
            stale = world.validate_profile(pra, draft)
            assert stale.status == 409, stale.describe()
            assert _profile_status(evidence, draft) != "VALIDATED", "stale profile validated"
            audit = evidence.admin_events(stale)
            assert audit and audit[0]["outcome"] == "conflict"
    finally:
        resync_capabilities(world)
    assert _caps_row(evidence, world.source_id)["metadata_fingerprint"] == original_fp


def test_A40_validated_profile_turns_stale_on_drift_and_stays_unusable(e2e_env, world,
                                                                        evidence):
    """Needs a profile that validated successfully, i.e. register-capability evidence."""
    world.need("source", "caps", "roles")
    pra = world.role_session("PROFILE_ADMIN")
    validated = expect(world.create_profile(pra, world.source_id), 201, "A40 control").body["id"]
    expect(world.add_mapping(pra, validated), 201, "A40 control mapping")
    control = world.validate_profile(pra, validated)
    assert control.status == 200, (
        "cannot create a VALIDATED profile in this environment (no register capability "
        f"evidence / sidecar?): {control.describe()}")
    try:
        with drifted_fake1c(e2e_env):
            expect(world.pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                                 {"reason": "A40 drift"}), 200, "A40 refresh")
            assert _profile_status(evidence, validated) == "STALE"
            again = world.validate_profile(pra, validated)
            assert again.status == 409, again.describe()
            assert _profile_status(evidence, validated) == "STALE"
    finally:
        resync_capabilities(world)


# --------------------------------------------------------------------------------------- A41
def test_A41_unknown_capability_fails_closed(e2e_env, world, evidence):
    world.need("source", "caps", "roles")
    pra, aa = world.role_session("PROFILE_ADMIN"), world.role_session("ACCESS_ADMIN")
    pid = expect(world.create_profile(pra, world.source_id), 201, "A41 profile").body["id"]
    unknown = [{"entity_set": "AccumulationRegister_E2EDoesNotExist", "method": "Turnovers"}]
    expect(world.add_mapping(pra, pid, required=unknown), 201, "A41 mapping is only a candidate")
    rejected = world.validate_profile(pra, pid)
    assert rejected.status >= 400, f"unknown capability implicitly allowed: {rejected.describe()}"
    assert _profile_status(evidence, pid) != "VALIDATED", (
        "profile validated with an unknown capability")
    audit = evidence.admin_events(rejected)
    assert audit and audit[0]["outcome"] in {"error", "conflict"}, "rejection not audited"

    before = evidence.count("capability_overrides")
    override = aa.post("/admin/v1/capability-overrides", {
        "principal_kind": "subject", "principal_id": unique("e2e-scratch"),
        "capability_key": "capability.that.does.not.exist", "source_id": world.source_id,
        "company_id": None, "effect": "allow", "reason": "A41 unknown capability"})
    assert override.status == 400 and override.error == "INVALID_REQUEST", override.describe()
    concept = world.add_mapping(pra, pid, concept="bitcoin")
    assert concept.status == 400, concept.describe()
    malformed = world.add_mapping(pra, pid, required=[{"entity_set": "X", "method": "m", "x": 1}],
                                  concept="cash")
    assert malformed.status == 400, malformed.describe()
    assert evidence.count("capability_overrides") == before, "unknown capability stored"
