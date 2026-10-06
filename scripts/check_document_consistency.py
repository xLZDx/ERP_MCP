"""Fail when the authoritative dashboard/report/document index drift apart."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .engineering_checkpoint import check_checkpoint
except ImportError:
    from engineering_checkpoint import check_checkpoint

REQUIRED_LINKS = (
    "ERP_MCP_ENGINEERING_COMMAND_CENTER.html",
    "IMPLEMENTATION_STATUS.md",
    "DOD_STATUS.md",
    "REQUIREMENTS_TRACEABILITY.md",
)


def check(root: Path) -> None:
    check_checkpoint(root)
    index = (root / "docs/DOCUMENT_INDEX.md").read_text(encoding="utf-8")
    status = (root / "reports/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    dod = (root / "reports/DOD_STATUS.md").read_text(encoding="utf-8")
    dashboard = (root / "ERP_MCP_ENGINEERING_COMMAND_CENTER.html").read_text(encoding="utf-8")
    missing = [item for item in REQUIRED_LINKS if item not in index and item not in dashboard]
    if missing:
        raise ValueError(f"document index/dashboard missing references: {', '.join(missing)}")
    if "Production GO remains NO-GO" not in status or "DoD remains PARTIAL" not in dod:
        raise ValueError("authoritative status decision is not synchronized")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    check(args.root)
    print("document consistency check: PASS")


if __name__ == "__main__":
    main()
