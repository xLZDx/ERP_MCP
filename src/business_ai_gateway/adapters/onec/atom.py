from __future__ import annotations

from defusedxml import ElementTree as ET

ATOM = "http://www.w3.org/2005/Atom"
M = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
D = "http://schemas.microsoft.com/ado/2007/08/dataservices"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _entry_to_dict(entry) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    properties = None
    for element in entry.iter():
        if element.tag == f"{{{M}}}properties":
            properties = element
            break
    if properties is None:
        return result

    for child in properties:
        if child.attrib.get(f"{{{M}}}null") == "true":
            value = None
        else:
            value = child.text
        result[_local(child.tag)] = value
    return result


def parse_atom_payload(xml_bytes: bytes) -> dict[str, list[dict[str, str | None]]]:
    root = ET.fromstring(xml_bytes)
    local = _local(root.tag)

    if local == "entry":
        return {"value": [_entry_to_dict(root)]}

    if local != "feed":
        raise ValueError(f"unsupported Atom payload root: {local}")

    entries = [
        _entry_to_dict(child)
        for child in root
        if child.tag == f"{{{ATOM}}}entry"
    ]
    return {"value": entries}
