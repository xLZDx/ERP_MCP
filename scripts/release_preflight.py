"""Run deterministic local release evidence checks without contacting production systems."""

from __future__ import annotations

from pathlib import Path

REQUIRED_PATHS = (
    Path("pyproject.toml"),
    Path("uv.lock"),
    Path("requirements-runtime.lock"),
    Path("vendor/UPSTREAMS.md"),
    Path("vendor/intake.json"),
    Path("docs/ADAPTER_CENSUS.md"),
    Path("docs/ADAPTER_INTAKE_PLAN.md"),
    Path("docs/adr/ADR-0003-reuse-before-rewrite.md"),
    Path("deploy/PRODUCTION.md"),
    Path("deploy/ROLLBACK.md"),
)


def validate_release_tree(root: Path) -> list[str]:
    missing = [str(path) for path in REQUIRED_PATHS if not (root / path).is_file()]
    if missing:
        raise ValueError(f"release evidence files missing: {', '.join(missing)}")
    return [path.as_posix() for path in REQUIRED_PATHS]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = validate_release_tree(root)
    print(f"release preflight: PASS ({len(paths)} required evidence files)")
    print("production GO: NO-GO until external 1C, reconciliation and operator gates close")


if __name__ == "__main__":
    main()
