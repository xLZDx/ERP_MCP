"""Check that the current evidence package has the required authoritative artifacts."""

from __future__ import annotations

import re
from pathlib import Path

try:
    from .engineering_checkpoint import check_checkpoint
except ImportError:
    from engineering_checkpoint import check_checkpoint

REQUIRED = (
    Path("ERP_MCP_ENGINEERING_COMMAND_CENTER.html"),
    Path("reports/IMPLEMENTATION_STATUS.md"),
    Path("reports/DOD_STATUS.md"),
    Path("docs/RELEASE_OPERATIONS.md"),
    Path("deploy/alerts/prometheus.rules.yml"),
)


def check(root: Path) -> None:
    check_checkpoint(root)
    missing = [str(path) for path in REQUIRED if not (root / path).is_file()]
    if missing:
        raise ValueError(f"report artifacts missing: {', '.join(missing)}")
    status = (root / "reports/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    dod = (root / "reports/DOD_STATUS.md").read_text(encoding="utf-8")
    if "Production GO remains" not in status or "DoD remains PARTIAL" not in dod:
        raise ValueError("authoritative reports must state the current fail-closed decision")
    authoritative = status.split("## Current authoritative state", 2)[1].split(
        "## Current authoritative state", 1
    )[0]
    stale_markers = ("HOSTED CI PENDING", "TODO: UPDATE", "<CURRENT_COMMIT>")
    if any(marker in authoritative for marker in stale_markers):
        raise ValueError("authoritative report contains a stale status marker")
    if not re.search(r"Hosted confirmation:.*run `?\d{8,}`?.*PASS", authoritative, re.IGNORECASE | re.DOTALL):
        raise ValueError("authoritative report is missing current hosted confirmation")


def main() -> None:
    check(Path(__file__).resolve().parents[1])
    print(f"report reference check: PASS ({len(REQUIRED)} artifacts)")


if __name__ == "__main__":
    main()
