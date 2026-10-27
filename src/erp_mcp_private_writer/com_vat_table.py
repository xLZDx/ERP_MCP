"""Reviewed closed table from payload VAT rate codes to 1C ``СтавкиНДС`` enumeration values.

The enumeration value names of the 1C configuration are legacy and do not match the rates they hold
(Change Record 372): ``НДС18`` is 20 percent, ``НДС10`` is 8 percent and ``НДС_10`` is 10 percent. The
table below is therefore keyed by the payload code and targets the value whose displayed synonym is the
intended rate. It is a DRAFT until the clone crosswalk review accepts it; no production binding set uses
it yet and the writer stays unqualified and disabled.
"""
from __future__ import annotations

from .com_manifest import PayloadPropertyBinding

__all__ = ["VAT_RATE_CODE_TO_ENUM_VALUE", "vat_rate_binding"]

# (payload vat_rate_code, 1C enumeration value name), with the displayed rate noted per entry.
VAT_RATE_CODE_TO_ENUM_VALUE: tuple[tuple[str, str], ...] = (
    ("VAT0", "НДС0"),             # 0 percent
    ("VAT10", "НДС_10"),          # 10 percent
    ("VAT20", "НДС18"),           # 20 percent (legacy name)
)


def vat_rate_binding(payload_path: str, property_path: str) -> PayloadPropertyBinding:
    """Binding for a VAT rate field that refuses every code outside the closed table."""
    return PayloadPropertyBinding(
        payload_path,
        property_path,
        "SetValue",
        "EnumRef.СтавкиНДС",
        VAT_RATE_CODE_TO_ENUM_VALUE,
    )
