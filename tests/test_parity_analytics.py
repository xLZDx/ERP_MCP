from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.real1c.parity_analytics import (
    LABEL_CROSS_COPY,
    LABEL_PROOF,
    ParityContext,
    ParityRefused,
    compare_canonical,
    run_parity,
    same_database_proof,
)

REF_A = "cccccccc-0000-0000-0000-000000000001"
REF_B = "cccccccc-0000-0000-0000-000000000002"
ACC = "aaaaaaaa-0000-0000-0000-000000000001"


def make_base(root: Path, name: str, content: bytes = b"db") -> Path:
    base = root / name
    base.mkdir()
    (base / "1Cv8.1CD").write_bytes(content)
    return base


def descriptor(root: Path, name: str, infobase: Path) -> Path:
    path = root / name
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<point xmlns="http://v8.1c.ru/8.2/virtual-resource-system" base="/pub" '
        f'ib="File=&quot;{infobase}&quot;;"><ws pointEnableCommon="false"/></point>',
        encoding="utf-8",
    )
    return path


def ctx(**over) -> ParityContext:
    values = {"run_id": "run-1", "clone_identity": "clone-a", "publication_identity": "pub-a",
              "odata_metadata_fingerprint": "f" * 64, "com_metadata_fingerprint": "f" * 64,
              "pre_fingerprint": "p" * 64, "post_fingerprint": "p" * 64}
    values.update(over)
    return ParityContext(**values)


def row(account=ACC, refs=(REF_A, None, None), debit="1.00", credit="0", **names):
    return {
        "account_key": account,
        "analytics": [{"ref": r, "type": "Catalog.X" if r else None} for r in refs],
        names.get("d", "debit"): debit, names.get("c", "credit"): credit,
    }


class Spy:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def __call__(self):
        self.calls += 1
        return self.rows


def test_proof_passes_for_same_physical_file(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    proof = same_database_proof(descriptor(tmp_path, "default.vrd", clone), clone, reference_path=ref)
    assert len(proof.com_base_sha256) == 64


def test_proof_accepts_alias_path_to_same_file(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    alias = tmp_path / "clone_a" / ".." / "clone_a"
    assert same_database_proof(descriptor(tmp_path, "d.vrd", alias), clone, reference_path=ref)


def test_proof_refuses_other_clone_with_identical_bytes(tmp_path):
    a = make_base(tmp_path, "clone_a", b"same")
    b = make_base(tmp_path, "clone_b", b"same")
    ref = make_base(tmp_path, "reference")
    with pytest.raises(ParityRefused):
        same_database_proof(descriptor(tmp_path, "d.vrd", b), a, reference_path=ref)


def test_proof_refuses_reference_on_either_side(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    with pytest.raises(ParityRefused):
        same_database_proof(descriptor(tmp_path, "d.vrd", ref), ref, reference_path=ref)
    with pytest.raises(ParityRefused):
        same_database_proof(descriptor(tmp_path, "d.vrd", clone), ref, reference_path=ref)
    with pytest.raises(ParityRefused):
        same_database_proof(descriptor(tmp_path, "d.vrd", ref), clone, reference_path=ref)


def test_proof_accepts_the_unquoted_descriptor_form_written_by_real_publications(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    path = tmp_path / "real.vrd"
    path.write_text(f'<point base="/pub" ib="File={clone};"><ws pointEnableCommon="true"/></point>', encoding="utf-8")
    proof = same_database_proof(path, clone, reference_path=ref)
    assert proof.publication_infobase_sha256 == proof.com_base_sha256


def test_proof_refuses_bad_descriptors(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    cases = {
        "missing.vrd": None,
        "garbage.vrd": "<point",
        "noib.vrd": '<point base="/x"/>',
        "server.vrd": '<point ib="Srvr=&quot;s&quot;;Ref=&quot;r&quot;;"/>',
        "two.vrd": '<root><point ib="File=&quot;a&quot;;"/><point ib="File=&quot;b&quot;;"/></root>',
    }
    for name, text in cases.items():
        if text is not None:
            (tmp_path / name).write_text(text, encoding="utf-8")
        with pytest.raises(ParityRefused):
            same_database_proof(tmp_path / name, clone, reference_path=ref)


def test_run_refuses_mismatched_pair_before_any_fetch(tmp_path):
    clone_a = make_base(tmp_path, "clone_a")
    clone_b = make_base(tmp_path, "clone_b")
    ref = make_base(tmp_path, "reference")
    odata, com = Spy([row()]), Spy([row()])
    with pytest.raises(ParityRefused):
        run_parity(context=ctx(), com_base_path=clone_a, reference_path=ref, odata_fetch=odata,
                   com_fetch=com, publication_descriptor_path=descriptor(tmp_path, "d.vrd", clone_b))
    assert odata.calls == 0 and com.calls == 0


def test_run_refuses_reference_without_descriptor(tmp_path):
    ref = make_base(tmp_path, "reference")
    odata, com = Spy([]), Spy([])
    with pytest.raises(ParityRefused):
        run_parity(context=ctx(), com_base_path=ref, reference_path=ref, odata_fetch=odata, com_fetch=com)
    assert odata.calls == com.calls == 0


def test_label_parity_proof_only_with_descriptor_proof(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    proof = run_parity(context=ctx(), com_base_path=clone, reference_path=ref, odata_fetch=Spy([row()]),
                       com_fetch=Spy([row()]), publication_descriptor_path=descriptor(tmp_path, "d.vrd", clone))
    assert proof["label"] == LABEL_PROOF and proof["result"]["equal"] is True
    cross = run_parity(context=ctx(), com_base_path=clone, reference_path=ref, odata_fetch=Spy([row()]),
                       com_fetch=Spy([row()]))
    assert cross["label"] == LABEL_CROSS_COPY and cross["same_database_proof"] is None


def test_manifest_records_identity_and_is_never_overwritten(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    out = tmp_path / "manifest.json"
    kwargs = {"context": ctx(), "com_base_path": clone, "reference_path": ref,
              "odata_fetch": Spy([row()]), "com_fetch": Spy([row()]), "manifest_path": out}
    run_parity(**kwargs)
    saved = json.loads(out.read_text(encoding="utf-8"))
    for key in ("run_id", "clone_identity", "publication_identity", "odata_metadata_fingerprint",
                "com_metadata_fingerprint", "pre_fingerprint", "post_fingerprint", "label"):
        assert key in saved
    with pytest.raises(FileExistsError):
        run_parity(**kwargs)


def test_changed_fingerprints_void_equality(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    manifest = run_parity(context=ctx(post_fingerprint="q" * 64), com_base_path=clone, reference_path=ref,
                          odata_fetch=Spy([row()]), com_fetch=Spy([row()]))
    assert manifest["fingerprints_stable"] is False and manifest["result"]["equal"] is False


def test_differing_metadata_fingerprints_void_equality(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    manifest = run_parity(context=ctx(com_metadata_fingerprint="z" * 64), com_base_path=clone,
                          reference_path=ref, odata_fetch=Spy([row()]), com_fetch=Spy([row()]))
    assert manifest["fingerprints_stable"] is False and manifest["result"]["equal"] is False


def test_empty_run_identity_is_refused_before_any_fetch(tmp_path):
    clone = make_base(tmp_path, "clone_a")
    ref = make_base(tmp_path, "reference")
    odata, com = Spy([row()]), Spy([row()])
    with pytest.raises(ParityRefused):
        run_parity(context=ctx(run_id=""), com_base_path=clone, reference_path=ref,
                   odata_fetch=odata, com_fetch=com)
    assert odata.calls == 0 and com.calls == 0


def test_compare_equal_ignores_order_and_field_naming():
    odata = [row(refs=(REF_A, None, None)), row(refs=(REF_B, None, None), debit="2.5")]
    com = [row(refs=(REF_B, None, None), debit="2.50"), row(refs=(REF_A, None, None), d="debit")]
    odata_alt = [row(refs=(REF_A, None, None), d="balance_debit", c="balance_credit"), odata[1]]
    result = compare_canonical(odata, com)
    assert result.equal and result.matched_keys == 2 and result.odata_sha256 == result.com_sha256
    assert compare_canonical(odata_alt, com).equal


def test_compare_detects_differences_and_reports_no_values():
    odata = [row(refs=(REF_A, None, None), debit="123.45"), row(refs=(REF_B, None, None))]
    com = [row(refs=(REF_A, None, None), debit="123.46"), row(refs=(REF_A, REF_B, None))]
    result = compare_canonical(odata, com)
    assert (result.matched_keys, result.only_in_odata, result.only_in_com, result.amount_mismatches) == (
        1, 1, 1, 1)
    assert not result.equal and result.odata_sha256 != result.com_sha256
    blob = json.dumps(result.__dict__)
    assert "123.45" not in blob and REF_A not in blob
