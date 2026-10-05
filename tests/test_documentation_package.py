# ruff: noqa: I001
import json
import pathlib


ROOT = pathlib.Path(".")
MANIFEST = ROOT / "docs" / "PACKAGE_MANIFEST.json"


def test_normative_documentation_package_is_complete():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert data["schema_version"] == 1
    assert data["version"] == "1.0"
    assert data["status"] == "FROZEN_FOR_IMPLEMENTATION"

    missing = [
        path
        for path in data["required_documents"]
        if not (ROOT / path).is_file()
    ]
    assert missing == []


def test_required_documents_are_not_empty():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    too_small = []
    for path in data["required_documents"]:
        file_path = ROOT / path
        if file_path.stat().st_size < 100:
            too_small.append(path)

    assert too_small == []
