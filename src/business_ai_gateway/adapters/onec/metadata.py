from __future__ import annotations

from dataclasses import dataclass

from defusedxml import ElementTree as ET

from ...models import MetadataEntity


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _attribute(element, local_name: str) -> str | None:
    return next(
        (
            value
            for key, value in element.attrib.items()
            if _local_name(key).casefold() == local_name.casefold()
        ),
        None,
    )


def _annotation_pair(element) -> tuple[str, str] | None:
    term = _attribute(element, "term")
    value = _attribute(element, "string")
    if term and value:
        return term.casefold(), value
    return None


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
    # Well-formed XML is not OData metadata: an HTML error page or a proxy banner parses fine
    # but must never be fingerprinted as service metadata.
    if root.tag.rsplit("}", 1)[-1] != "Edmx" or not any(
        element.tag.rsplit("}", 1)[-1] in {"Schema", "EntityType", "EntitySet"}
        for element in root.iter()
    ):
        raise ValueError("response is not OData $metadata")

    namespace_aliases: dict[str, str] = {}
    for element in root.iter():
        if _local_name(element.tag) != "Schema":
            continue
        namespace = element.attrib.get("Namespace")
        alias = element.attrib.get("Alias")
        if namespace and alias:
            if alias in namespace_aliases and namespace_aliases[alias] != namespace:
                raise ValueError("ambiguous metadata namespace alias")
            namespace_aliases[alias] = namespace

    def canonical_type(type_name: str) -> str:
        namespace, separator, short_name = type_name.rpartition(".")
        if separator and namespace in namespace_aliases:
            return f"{namespace_aliases[namespace]}.{short_name}"
        return type_name

    external_property_annotations: dict[tuple[str, str], dict[str, str]] = {}
    for element in root.iter():
        if _local_name(element.tag) != "Annotations":
            continue
        target = _attribute(element, "target")
        if not target or "/" not in target:
            continue
        target_type, property_name = target.rsplit("/", 1)
        key = (canonical_type(target_type), property_name)
        for annotation in element:
            pair = _annotation_pair(annotation)
            if pair is None:
                continue
            term, value = pair
            values = external_property_annotations.setdefault(key, {})
            if term.endswith(".label"):
                values.setdefault("label", value)
            elif term.endswith(".description"):
                values.setdefault("description", value)

    type_namespaces = {
        id(item): schema.attrib.get("Namespace", "")
        for schema in root.iter() if _local_name(schema.tag) == "Schema"
        for item in schema.iter() if _local_name(item.tag) == "EntityType"
    }
    type_props: dict[str, tuple[str, ...]] = {}
    type_property_types: dict[str, tuple[tuple[str, str | None], ...]] = {}
    type_property_labels: dict[str, tuple[tuple[str, str], ...]] = {}
    type_property_descriptions: dict[str, tuple[tuple[str, str], ...]] = {}
    type_nav: dict[str, tuple[str, ...]] = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "EntityType":
            continue
        type_name = element.attrib.get("Name")
        if not type_name:
            continue
        namespace = type_namespaces.get(id(element), "")
        type_name = f"{namespace}.{type_name}" if namespace else type_name
        if type_name in type_props:
            raise ValueError("duplicate metadata entity type")
        props: list[str] = []
        property_types: list[tuple[str, str | None]] = []
        property_labels: list[tuple[str, str]] = []
        property_descriptions: list[tuple[str, str]] = []
        nav: list[str] = []
        for child in element:
            local = _local_name(child.tag)
            name = child.attrib.get("Name")
            if not name:
                continue
            if local == "Property":
                props.append(name)
                property_types.append((name, child.attrib.get("Type")))
                label = None
                description = None
                for attribute_name, value in child.attrib.items():
                    attribute_local = _local_name(attribute_name).casefold()
                    if attribute_local == "label" and label is None:
                        label = value
                    elif attribute_local in {"description", "quickinfo"} and description is None:
                        description = value
                for annotation in child:
                    if _local_name(annotation.tag) != "Annotation":
                        continue
                    pair = _annotation_pair(annotation)
                    if pair is None:
                        continue
                    annotation_term, annotation_value = pair
                    if annotation_term.endswith(".label") and label is None:
                        label = annotation_value
                    elif annotation_term.endswith(".description") and description is None:
                        description = annotation_value
                if label:
                    property_labels.append((name, label))
                if description:
                    property_descriptions.append((name, description))
            elif local == "NavigationProperty":
                nav.append(name)
        type_props[type_name] = tuple(props)
        type_property_types[type_name] = tuple(property_types)
        type_property_labels[type_name] = tuple(property_labels)
        type_property_descriptions[type_name] = tuple(property_descriptions)
        type_nav[type_name] = tuple(nav)

    annotation_cache: dict[str, tuple[tuple, tuple]] = {}
    entities = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "EntitySet":
            continue
        name = element.attrib.get("Name")
        entity_type = element.attrib.get("EntityType", "")
        if not name:
            continue
        type_key = canonical_type(entity_type)
        if "." not in type_key:
            matches = [key for key in type_props if key.rsplit(".", 1)[-1] == type_key]
            if len(matches) > 1:
                raise ValueError("ambiguous unqualified metadata entity type")
            if matches:
                type_key = matches[0]
        if type_key not in annotation_cache:
            property_labels = dict(type_property_labels.get(type_key, ()))
            property_descriptions = dict(type_property_descriptions.get(type_key, ()))
            for property_name in type_props.get(type_key, ()):
                external = external_property_annotations.get(
                    (type_key, property_name), {}
                )
                property_labels.setdefault(property_name, external.get("label", ""))
                property_descriptions.setdefault(property_name, external.get("description", ""))
            annotation_cache[type_key] = (
                tuple((key, value) for key, value in property_labels.items() if value),
                tuple((key, value) for key, value in property_descriptions.items() if value),
            )
        labels, descriptions = annotation_cache[type_key]
        entities.append(
            MetadataEntity(
                name=name,
                entity_type=entity_type,
                properties=type_props.get(type_key, ()),
                navigation_properties=type_nav.get(type_key, ()),
                property_types=type_property_types.get(type_key, ()),
                property_labels=labels,
                property_descriptions=descriptions,
            )
        )
    entities.sort(key=lambda x: x.name)
    return MetadataIndex(entities=tuple(entities))
