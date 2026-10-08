import dataclasses

import pytest

from business_ai_gateway.phase2.drive_changes import (
    DriveChange,
    DriveChangeKind,
    DriveChangeProjector,
    DrivePage,
)


def page(token="c1", changes=(), next_token=None, new_token="c2"):
    return DrivePage(token, tuple(changes), next_token, new_token)


def change(cid="1", file_id="a", revision="r1", kind=DriveChangeKind.UPSERT, drive="d1"):
    return DriveChange(cid, file_id, revision, kind, drive)


def test_valid_candidate_is_unattested_only():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda f: f == "a"
    ).prepare(page(changes=(change(),)), stored_cursor="c1")
    assert batch.candidates[0].status == "UNATTESTED"
    assert batch.is_checkpoint and batch.next_cursor == "c2"
    assert batch.durable_commit_required


def test_unknown_folder_membership_is_not_automatically_allowed():
    projector = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: None
    )
    with pytest.raises(ValueError, match="FOLDER_MEMBERSHIP_UNVERIFIED"):
        projector.prepare(page(changes=(change(),)), stored_cursor="c1")


def test_cross_drive_event_does_not_leak_file():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(drive="d2"),)), stored_cursor="c1")
    assert batch.candidates == ()
    assert batch.denied_changes == 1


def test_trashed_file_is_not_new_native_evidence():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(kind=DriveChangeKind.REMOVED),)), stored_cursor="c1")
    assert batch.candidates == ()
    # Removal is not lost in a counter: it is an explicit tombstone candidate.
    assert [(t.file_id, t.reason) for t in batch.tombstones] == [("a", "REMOVED")]
    assert batch.denied_changes == 0


def test_unknown_change_is_reported_separately_and_requires_pause():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id=None, file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(kind=DriveChangeKind.UNKNOWN),)), stored_cursor="c1")
    assert batch.candidates == ()
    assert batch.unknown_changes == 1
    assert batch.denied_changes == 0
    assert batch.requires_gap_or_pause is True


def test_clean_batch_does_not_require_pause():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id=None, file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(),)), stored_cursor="c1")
    assert batch.unknown_changes == 0
    assert batch.requires_gap_or_pause is False
    assert batch.tombstones == ()


def test_access_loss_is_membership_changed_tombstone():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: False
    ).prepare(page(changes=(change(),)), stored_cursor="c1")
    assert batch.candidates == ()
    assert [(t.file_id, t.reason) for t in batch.tombstones] == [("a", "MEMBERSHIP_CHANGED")]
    assert batch.tombstones[0].change_id == "1"


def test_folder_change_marks_descendants_for_requalification():
    folder = DriveChange("9", "folder-1", "r1", DriveChangeKind.UPSERT, "d1",
                         mime_type="application/vnd.google-apps.folder", parents=("root",))
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: True
    ).prepare(page(changes=(folder,)), stored_cursor="c1")
    assert batch.requalify_folder_ids == ("folder-1",)
    assert batch.candidates == ()


def test_removed_folder_requalifies_and_tombstones():
    folder = DriveChange("9", "folder-1", None, DriveChangeKind.REMOVED, "d1",
                         mime_type="application/vnd.google-apps.folder")
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: True
    ).prepare(page(changes=(folder,)), stored_cursor="c1")
    assert batch.requalify_folder_ids == ("folder-1",)
    assert [t.reason for t in batch.tombstones] == ["REMOVED"]


def test_drive_change_keeps_mime_type_and_parents():
    c = DriveChange("1", "a", "r", DriveChangeKind.UPSERT, "d1",
                    mime_type="application/pdf", parents=("p1", "p2"))
    assert c.mime_type == "application/pdf" and c.parents == ("p1", "p2")


def test_missing_drive_id_in_drive_scoped_unknown_is_unknown_not_silent():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(kind=DriveChangeKind.UNKNOWN, drive=None),)),
              stored_cursor="c1")
    assert batch.unknown_changes == 1 and batch.requires_gap_or_pause is True


def test_wrong_cursor_denied():
    client = DriveChangeProjector(
        connection_id="conn", drive_id="d1", file_scope_allowed=lambda _: True
    )
    with pytest.raises(ValueError, match="CURSOR_COMPARE_AND_SWAP_FAILED"):
        client.prepare(page(), stored_cursor="old")


def test_intermediate_page_continuation():
    client = DriveChangeProjector(
        connection_id="conn", drive_id=None, file_scope_allowed=lambda _: True
    )
    batch = client.prepare(page(next_token="intermediate", new_token=None), stored_cursor="c1")
    assert batch.next_cursor == "intermediate"
    assert not batch.is_checkpoint


def test_duplicate_change_id_is_refused():
    client = DriveChangeProjector(
        connection_id="conn", drive_id=None, file_scope_allowed=lambda _: True
    )
    with pytest.raises(ValueError, match="DUPLICATE_CHANGE_ID"):
        client.prepare(page(changes=(change(file_id="a"), change(file_id="b"))),
                       stored_cursor="c1")


@pytest.mark.parametrize("next_token,new_token", [(None, None), ("n", "c")])
def test_page_continuation_or_new_start_exclusive(next_token, new_token):
    with pytest.raises(ValueError, match="XOR"):
        page(next_token=next_token, new_token=new_token)


def test_revision_is_not_immutable_authority_by_itself():
    client = DriveChangeProjector(
        connection_id="conn", drive_id=None, file_scope_allowed=lambda _: True
    )
    batch = client.prepare(page(changes=(change(revision="r2"),)), stored_cursor="c1")
    candidate = batch.candidates[0]
    assert candidate.revision_id == "r2"
    # A revision id never upgrades trust: the candidate stays UNATTESTED and
    # carries no validation/attestation fields at all.
    assert candidate.status == "UNATTESTED"
    assert {f.name for f in dataclasses.fields(candidate)} == {
        "connection_id", "file_id", "revision_id", "change_id", "status"
    }


def _unknown_batch():
    return DriveChangeProjector(
        connection_id="conn-1", drive_id=None, file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(kind=DriveChangeKind.UNKNOWN),)), stored_cursor="c1")


def test_next_cursor_cannot_be_committed_while_unknown_changes_exist():
    batch = _unknown_batch()
    assert batch.unknown_changes == 1
    assert batch.next_cursor == "c1" and batch.is_checkpoint is False
    assert batch.committable_cursor() == "c1"
    assert batch.committable_cursor(recorded_gap="  ") == "c1"
    assert batch.committable_cursor(recorded_gap="gap-7") == "c2"


def test_clean_batch_commits_provider_cursor_without_gap():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id=None, file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(),)), stored_cursor="c1")
    assert batch.committable_cursor() == "c2" and batch.is_checkpoint


def test_batch_with_unknown_changes_cannot_be_built_with_advancing_cursor():
    batch = _unknown_batch()
    with pytest.raises(ValueError, match="CURSOR_ADVANCE_FORBIDDEN"):
        dataclasses.replace(batch, next_cursor="c2")
    with pytest.raises(ValueError, match="CURSOR_ADVANCE_FORBIDDEN"):
        dataclasses.replace(batch, is_checkpoint=True)


def test_removed_tombstone_without_mime_type_is_a_possible_folder():
    gone = DriveChange("9", "maybe-folder", None, DriveChangeKind.REMOVED, "d1")
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: True
    ).prepare(page(changes=(gone,)), stored_cursor="c1")
    assert batch.requalify_folder_ids == ("maybe-folder",)
    typed = DriveChange("10", "doc", None, DriveChangeKind.REMOVED, "d1", mime_type="text/plain")
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: True
    ).prepare(page(changes=(typed,)), stored_cursor="c1")
    assert batch.requalify_folder_ids == ()
