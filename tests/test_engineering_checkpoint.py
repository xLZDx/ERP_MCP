import json

import pytest

from scripts.engineering_checkpoint import REPORTS, check_checkpoint, implementation_fingerprint


def prepare(root):
    (root / "src").mkdir()
    (root / "src/fixture.py").write_text("value = 1\n")
    for name in REPORTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ENGINEERING_CHECKPOINT=FIXTURE_01\n")
    checkpoint = {"schema_version": 1, "batch_id": "FIXTURE_01",
                  "implementation_sha256": implementation_fingerprint(root),
                  "production_decision": "NO-GO", "dod_status": "PARTIAL",
                  "pr_number": 11, "pr_state": "DRAFT"}
    for name in REPORTS:
        with (root / name).open("a") as report:
            report.write(f"ENGINEERING_IMPLEMENTATION={checkpoint['implementation_sha256']}\n")
    (root / "reports/CURRENT_ENGINEERING_CHECKPOINT.json").write_text(json.dumps(checkpoint))


def test_checkpoint_accepts_matching_content_and_line_endings(tmp_path):
    prepare(tmp_path)
    assert check_checkpoint(tmp_path)["batch_id"] == "FIXTURE_01"
    (tmp_path / "src/fixture.py").write_bytes(b"value = 1\r\n")
    check_checkpoint(tmp_path)


def test_checkpoint_rejects_source_drift(tmp_path):
    prepare(tmp_path)
    (tmp_path / "src/fixture.py").write_text("value = 2\n")
    with pytest.raises(ValueError, match="implementation content changed"):
        check_checkpoint(tmp_path)


def test_checkpoint_also_binds_test_plane_implementation(tmp_path):
    prepare(tmp_path)
    (tmp_path / 'testbed').mkdir()
    (tmp_path / 'testbed/exporter.py').write_text('changed test-only implementation\n')
    with pytest.raises(ValueError, match='implementation content changed'):
        check_checkpoint(tmp_path)


def test_platform_specific_generated_metadata_is_not_implementation(tmp_path):
    prepare(tmp_path)
    generated = tmp_path / "src/fixture.egg-info"
    generated.mkdir()
    (generated / "PKG-INFO").write_text("platform-specific editable install metadata")
    (tmp_path / "src/.env").write_text("synthetic_private_configuration=fixture")
    check_checkpoint(tmp_path)


@pytest.mark.parametrize("report", REPORTS)
def test_checkpoint_rejects_stale_report_marker(tmp_path, report):
    prepare(tmp_path)
    (tmp_path / report).write_text("historical PASS\n")
    with pytest.raises(ValueError, match="checkpoint marker"):
        check_checkpoint(tmp_path)


def test_checkpoint_rejects_divergent_dashboard_copies(tmp_path):
    prepare(tmp_path)
    with (tmp_path / REPORTS[-1]).open("a") as dashboard:
        dashboard.write("changed\n")
    with pytest.raises(ValueError, match="dashboard copies differ"):
        check_checkpoint(tmp_path)


def test_refreshing_manifest_alone_cannot_hide_stale_report(tmp_path):
    prepare(tmp_path)
    (tmp_path / "src/fixture.py").write_text("value = 2\n")
    path = tmp_path / "reports/CURRENT_ENGINEERING_CHECKPOINT.json"
    checkpoint = json.loads(path.read_text())
    checkpoint["implementation_sha256"] = implementation_fingerprint(tmp_path)
    path.write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError, match="fingerprint is stale"):
        check_checkpoint(tmp_path)
