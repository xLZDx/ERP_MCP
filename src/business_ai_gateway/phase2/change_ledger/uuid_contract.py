"""Canonical UUID predicates shared by S12/S13 Python boundaries."""

from __future__ import annotations

from uuid import RFC_4122, UUID


def _parse_canonical_nonzero_uuid(value: object) -> UUID | None:
    """Parse only exact-length canonical UUID text, without normalizing caller input."""
    if type(value) is not str or len(value) != 36:
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value and parsed.int != 0 else None


def is_canonical_nonzero_uuid(value: object) -> bool:
    """Accept exact lowercase canonical UUID text except the all-zero sentinel."""
    return _parse_canonical_nonzero_uuid(value) is not None


def is_canonical_process_instance_uuid(value: object) -> bool:
    """Require a canonical nonzero UUID with RFC variant and a defined version 1 through 8."""
    parsed = _parse_canonical_nonzero_uuid(value)
    return (parsed is not None and parsed.version in range(1, 9)
            and parsed.variant == RFC_4122)
