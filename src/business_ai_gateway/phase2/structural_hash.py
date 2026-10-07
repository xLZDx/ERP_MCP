"""Phase 2: read-only OData EDMX structural fingerprinting (OBSERVED only).

No database writes, approval, source connection, or semantic promotion is performed here.
The input is already-authorized, bounded metadata bytes from an existing 1C adapter.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from defusedxml import ElementTree as ET

_CANONICALIZER_VERSION = "edmx-structural-v1"
_UNORDERED_CHILDREN = frozenset({"Schema", "EntityType", "ComplexType", "EntityContainer"})


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _canonical(element: Any) -> dict[str, Any]:
    """Preserve all namespaced tags/attrs; sort only approved unordered members."""
    children = [_canonical(item) for item in element]
    if _local(element.tag) in _UNORDERED_CHILDREN:
        children.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")))
    result: dict[str, Any] = {
        "tag": element.tag,
        "attributes": sorted(element.attrib.items()),
        "children": children,
    }
    if element.text and element.text.strip():
        # Text of annotations/documentation may have semantic significance.
        result["text"] = element.text.strip()
    return result


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class StructuralFingerprint:
    canonicalizer_version: str
    raw_sha256: str
    structural_sha256: str
    objects: tuple[tuple[str, str], ...]

    def object_hashes(self) -> dict[str, str]:
        return dict(self.objects)


def fingerprint_edmx(xml: bytes, *, max_bytes: int = 20_000_000) -> StructuralFingerprint:
    """Produce immutable, non-authoritative metadata evidence.

    Raising on invalid/partial/ambiguous metadata is intentional: a failed scan must
    never be mistaken for an accepted schema change or a deleted object.
    """
    if not isinstance(xml, bytes) or not xml or len(xml) > max_bytes:
        raise ValueError("EDMX_SIZE_INVALID")
    root = ET.fromstring(xml)
    if _local(root.tag) != "Edmx":
        raise ValueError("NOT_EDMX")
    schema_list = [node for node in root.iter() if _local(node.tag) == "Schema"]
    if not schema_list:
        raise ValueError("EDMX_SCHEMA_ABSENT")
    objects: dict[str, str] = {}
    schema_headers: list[dict[str, Any]] = []
    entity_set_count = 0
    for schema in schema_list:
        namespace = schema.attrib.get("Namespace", "").strip()
        if not namespace:
            raise ValueError("EDMX_NAMESPACE_ABSENT")
        schema_headers.append({"namespace": namespace, "attributes": sorted(schema.attrib.items())})
        for child in schema:
            kind = _local(child.tag)
            name = child.attrib.get("Name")
            if name:
                key = f"{namespace}::{kind}::{name}"
                if key in objects:
                    raise ValueError("EDMX_DUPLICATE_IDENTITY")
                objects[key] = _digest(_canonical(child))
            if kind != "EntityContainer":
                continue
            container_name = name
            if not container_name:
                raise ValueError("EDMX_CONTAINER_NAME_ABSENT")
            for item in child:
                item_name = item.attrib.get("Name")
                if not item_name:
                    continue
                item_kind = _local(item.tag)
                key = f"{namespace}::{container_name}::{item_kind}::{item_name}"
                if key in objects:
                    raise ValueError("EDMX_DUPLICATE_IDENTITY")
                objects[key] = _digest(_canonical(item))
                if item_kind == "EntitySet":
                    entity_set_count += 1
    if not entity_set_count:
        raise ValueError("EDMX_ENTITY_SET_ABSENT")
    sorted_objects = tuple(sorted(objects.items()))
    structural_sha256 = _digest({"canonicalizer": _CANONICALIZER_VERSION,
                                 "schema_headers": sorted(schema_headers, key=lambda x: (x["namespace"], x["attributes"])),
                                 "objects": sorted_objects})
    return StructuralFingerprint(_CANONICALIZER_VERSION, hashlib.sha256(xml).hexdigest(),
                                 structural_sha256, sorted_objects)
