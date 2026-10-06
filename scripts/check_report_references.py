"""Check that the current evidence package has the required authoritative artifacts."""

from __future__ import annotations

from pathlib import Path

REQUIRED = (
    Path("ERP_MCP_ENGINEERING_COMMAND_CENTER.html"),
    Path("reports/IMPLEMENTATION_STATUS.md"),
    Path("reports/DOD_STATUS.md"),
    Path("docs/RELEASE_OPERATIONS.md"),
    Path("deploy/alerts/prometheus.rules.yml"),
)


def check(root: Path) -> None:
    missing = [str(path) for path in REQUIRED if not (root / path).is_file()]
    if missing:
        raise ValueError(f"report artifacts missing: {', '.join(missing)}")
    status = (root / "reports/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    dod = (root / "reports/DOD_STATUS.md").read_text(encoding="utf-8")
    if "Production GO remains" not in status or "DoD remains PARTIAL" not in dod:
        raise ValueError("authoritative reports must state the current fail-closed decision")


def main() -> None:
    check(Path(__file__).resolve().parents[1])
    print(f"report reference check: PASS ({len(REQUIRED)} artifacts)")


if __name__ == "__main__":
    main()
