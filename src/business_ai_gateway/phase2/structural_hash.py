"""Phase 2: read-only OData EDMX structural fingerprinting (OBSERVED only).

No database writes, approval, source connection, or semantic promotion is performed here.
The input is already-authorized, bounded metadata bytes from an existing 1C adapter.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

_CANONICALIZER_VERSION = "edmx-structural-v2"
_UNORDERED_CHILDREN = frozenset({
    "Edmx", "DataServices", "Schema", "EntityType", "ComplexType", "EntityContainer",
})
_MAX_DEPTH = 64
_MAX_NODES = 500_000


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _esc(part: str) -> str:
    """Make '::' unambiguous inside object keys (escape '%' and every ':')."""
    return part.replace("%", "%25").replace(":", "%3A")


def _sort_key(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical(element: Any, depth: int = 0, *, mask_named_schema_children: bool = False,
               parent_local: str = "") -> dict[str, Any]:
    """Preserve all namespaced tags/attrs; sort only approved unordered members.

    With mask_named_schema_children the named direct children of a Schema are
    omitted; what remains is everything NOT attributable to a
    named object (the "residual").
    """
    if depth > _MAX_DEPTH:
        raise ValueError("EDMX_DEPTH_EXCEEDED")
    local = _local(element.tag)
    children = [
        _canonical(item, depth + 1, mask_named_schema_children=mask_named_schema_children,
                   parent_local=local)
        for item in element
        # Named direct Schema children are attributable objects: omitted from the residual.
        if not (mask_named_schema_children and local == "Schema" and item.attrib.get("Name"))
    ]
    if local in _UNORDERED_CHILDREN:
        children.sort(key=_sort_key)
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


def _scope_part(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True)
class StructuralFingerprint:
    canonicalizer_version: str
    raw_sha256: str
    structural_sha256: str
    objects: tuple[tuple[str, str], ...]
    # Hash of everything that is NOT attributable to a named object.
    residual_sha256: str
    tenant_id: str
    source_id: str
    # True when objects were removed by an ACL filter: the whole-document hashes are
    # then replaced by hashes scoped to the visible objects, and a diff touching this
    # view can never prove that a change is attributable (see diff_observed).
    acl_filtered: bool = False
    withheld_count: int = 0

    def __post_init__(self) -> None:
        if not _scope_part(self.tenant_id) or not _scope_part(self.source_id):
            raise ValueError("FINGERPRINT_SCOPE_INVALID")
        if (type(self.withheld_count) is not int or self.withheld_count < 0
                or type(self.acl_filtered) is not bool
                or (self.withheld_count > 0 and not self.acl_filtered)):
            raise ValueError("FINGERPRINT_ACL_STATE_INVALID")

    def scoped_to_visible(self, visible: tuple[tuple[str, str], ...]) -> StructuralFingerprint:
        """Subject-safe view: only `visible` objects, no whole-document hashes."""
        withheld = len(self.objects) - len(visible)
        if withheld <= 0:
            return self
        scoped = _digest({"canonicalizer": self.canonicalizer_version, "tenant": self.tenant_id,
                          "source": self.source_id, "visible_objects": visible})
        return StructuralFingerprint(
            self.canonicalizer_version, scoped, scoped,
            visible, _digest({"scoped_residual": self.canonicalizer_version}),
            self.tenant_id, self.source_id, True, withheld)

    def object_hashes(self) -> dict[str, str]:
        return dict(self.objects)


def fingerprint_edmx(
    xml: bytes, *, tenant_id: str, source_id: str, max_bytes: int = 20_000_000,
    max_nodes: int = _MAX_NODES,
) -> StructuralFingerprint:
    """Produce immutable, non-authoritative metadata evidence.

    Raising on invalid/partial/ambiguous metadata is intentional: a failed scan must
    never be mistaken for an accepted schema change or a deleted object.
    """
    if not _scope_part(tenant_id) or not _scope_part(source_id):
        raise ValueError("FINGERPRINT_SCOPE_INVALID")
    if not isinstance(xml, bytes) or not xml or len(xml) > max_bytes:
        raise ValueError("EDMX_SIZE_INVALID")
    if max_nodes < 1:
        raise ValueError("EDMX_NODE_LIMIT_INVALID")
    try:
        root = ET.fromstring(xml)
    except DefusedXmlException as exc:
        raise ValueError("EDMX_FORBIDDEN_XML") from exc
    except ParseError as exc:
        raise ValueError("EDMX_PARSE_ERROR") from exc
    except RecursionError as exc:
        raise ValueError("EDMX_DEPTH_EXCEEDED") from exc
    if _local(root.tag) != "Edmx":
        raise ValueError("NOT_EDMX")
    # Bound work before the (twice-run) recursive canonicalization: count nodes iteratively.
    for count, _ in enumerate(root.iter(), 1):
        if count > max_nodes:
            raise ValueError("EDMX_NODE_LIMIT_EXCEEDED")
    try:
        tree = _canonical(root)
        residual = _canonical(root, mask_named_schema_children=True)
        return _build(xml, root, tree, residual, tenant_id, source_id)
    except RecursionError as exc:
        raise ValueError("EDMX_DEPTH_EXCEEDED") from exc


def _build(xml: bytes, root: Any, tree: dict[str, Any], residual: dict[str, Any],
           tenant_id: str, source_id: str) -> StructuralFingerprint:
    schema_list = [node for node in root.iter() if _local(node.tag) == "Schema"]
    if not schema_list:
        raise ValueError("EDMX_SCHEMA_ABSENT")
    objects: dict[str, str] = {}
    entity_set_count = 0
    for schema in schema_list:
        namespace = schema.attrib.get("Namespace", "").strip()
        if not namespace:
            raise ValueError("EDMX_NAMESPACE_ABSENT")
        for child in schema:
            kind = _local(child.tag)
            name = child.attrib.get("Name")
            if name:
                key = f"{_esc(namespace)}::{_esc(kind)}::{_esc(name)}"
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
                key = (f"{_esc(namespace)}::{_esc(container_name)}::"
                       f"{_esc(item_kind)}::{_esc(item_name)}")
                if key in objects:
                    raise ValueError("EDMX_DUPLICATE_IDENTITY")
                objects[key] = _digest(_canonical(item))
                if item_kind == "EntitySet":
                    entity_set_count += 1
    if not entity_set_count:
        raise ValueError("EDMX_ENTITY_SET_ABSENT")
    sorted_objects = tuple(sorted(objects.items()))
    # The whole normalized tree is hashed, so unnamed Schema children and all
    # non-Schema root content (Edmx/DataServices attributes, Reference) count.
    structural_sha256 = _digest({"canonicalizer": _CANONICALIZER_VERSION,
                                 "tree": tree, "objects": sorted_objects})
    residual_sha256 = _digest({"canonicalizer": _CANONICALIZER_VERSION, "residual": residual})
    return StructuralFingerprint(_CANONICALIZER_VERSION, hashlib.sha256(xml).hexdigest(),
                                 structural_sha256, sorted_objects, residual_sha256,
                                 tenant_id, source_id)
