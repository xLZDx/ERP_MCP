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
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="d1", file_scope_allowed=lambda _: None
    ).prepare(page(changes=(change(),)), stored_cursor="c1")
    assert batch.candidates == ()
    assert batch.denied_changes == 1


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
    assert batch.denied_changes == 1


def test_unknown_change_status_does_not_count():
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id=None, file_scope_allowed=lambda _: True
    ).prepare(page(changes=(change(kind=DriveChangeKind.UNKNOWN),)), stored_cursor="c1")
    assert batch.candidates == ()


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
    assert batch.candidates[0].revision_id == "r2"
    assert not hasattr(batch.candidates[0], "validated")
