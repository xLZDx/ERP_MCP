from __future__ import annotations

from dataclasses import dataclass

from defusedxml import ElementTree as ET

from ...models import MetadataEntity


@dataclass(frozen=True, slots=True)
class MetadataIndex:
    entities: tuple[MetadataEntity, ...]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(x.name for x in self.entities)

    def find(self, contains: str, limit: int = 50) -> list[MetadataEntity]:
        needle = contains.casefold().strip()
        items = (
            list(self.entities)
            if not needle
            else [
                x
                for x in self.entities
                if needle in x.name.casefold()
                or needle in x.entity_type.casefold()
            ]
        )
        return items[:limit]


def parse_metadata(xml_bytes: bytes) -> MetadataIndex:
    root = ET.fromstring(xml_bytes)

    type_props: dict[str, tuple[str, ...]] = {}
    type_nav: dict[str, tuple[str, ...]] = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "EntityType":
            continue
        type_name = element.attrib.get("Name")
        if not type_name:
            continue
        props: list[str] = []
        nav: list[str] = []
        for child in element:
            local = child.tag.rsplit("}", 1)[-1]
            name = child.attrib.get("Name")
            if not name:
                continue
            if local == "Property":
                props.append(name)
            elif local == "NavigationProperty":
                nav.append(name)
        type_props[type_name] = tuple(props)
        type_nav[type_name] = tuple(nav)

    entities = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "EntitySet":
            continue
        name = element.attrib.get("Name")
        entity_type = element.attrib.get("EntityType", "")
        if not name:
            continue
        short_type = entity_type.rsplit(".", 1)[-1]
        entities.append(
            MetadataEntity(
                name=name,
                entity_type=entity_type,
                properties=type_props.get(short_type, ()),
                navigation_properties=type_nav.get(short_type, ()),
            )
        )
    entities.sort(key=lambda x: x.name)
    return MetadataIndex(entities=tuple(entities))
