from __future__ import annotations

try:
    from .migrate import load_migrations
except ImportError:
    from migrate import load_migrations


def main() -> int:
    migrations = load_migrations()
    print(
        f"migration identities valid: {len(migrations)} files, "
        f"versions 001..{migrations[-1].version:03d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
