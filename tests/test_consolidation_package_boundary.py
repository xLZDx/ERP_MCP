"""The default wheel/image source roots contain only the gateway and S15 packages."""
from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_default_package_discovery_excludes_private_writer_and_s16() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_config = project["tool"]["setuptools"]["packages"]["find"]
    assert package_config["where"] == ["src"]
    assert package_config["include"] == [
        "business_ai_gateway",
        "business_ai_gateway.*",
        "erp_mcp_s15",
        "erp_mcp_s15.*",
    ]


def test_runtime_image_copies_only_public_package_roots() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime_source_copies = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().startswith("COPY src/")
    ]
    assert runtime_source_copies == [
        "COPY src/business_ai_gateway ./src/business_ai_gateway",
        "COPY src/erp_mcp_s15 ./src/erp_mcp_s15",
    ]
    assert "erp_mcp_private_writer" not in "\n".join(runtime_source_copies)
    assert "erp_mcp_s16" not in "\n".join(runtime_source_copies)
