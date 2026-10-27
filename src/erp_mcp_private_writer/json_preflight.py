"""Lexical JSON resource bounds applied before the standard decoder allocates a tree."""
from __future__ import annotations

MAX_JSON_DOCUMENT_DEPTH = 32
MAX_JSON_DOCUMENT_STRUCTURAL_NODES = 100_000


def check_json_document_limits(
    document: str,
    *,
    max_depth: int,
    max_structural_nodes: int,
) -> None:
    """Bound nesting and keys-plus-values; leave complete syntax validation to ``json.loads``."""
    if (type(document) is not str or type(max_depth) is not int or max_depth < 1
            or type(max_structural_nodes) is not int or max_structural_nodes < 1):
        raise ValueError("INVALID_JSON_PREFLIGHT_CONFIGURATION")

    containers: list[dict[str, str]] = []
    index = 0
    nodes = 0
    root_consumed = False
    while index < len(document):
        character = document[index]
        if character in " \t\r\n":
            index += 1
            continue
        if not containers:
            if root_consumed:
                raise ValueError("INVALID_JSON_DOCUMENT")
            nodes += 1
            if nodes > max_structural_nodes:
                raise ValueError("JSON_STRUCTURAL_LIMIT_EXCEEDED")
            index = _start_json_value(document, index, containers, max_depth)
            root_consumed = True
            continue

        current = containers[-1]
        kind, state = current["kind"], current["state"]
        if kind == "object" and state == "key_or_end":
            if character == "}":
                containers.pop()
                index += 1
            elif character == '"':
                nodes += 1
                if nodes > max_structural_nodes:
                    raise ValueError("JSON_STRUCTURAL_LIMIT_EXCEEDED")
                index = _skip_json_string(document, index)
                current["state"] = "colon"
            else:
                raise ValueError("INVALID_JSON_DOCUMENT")
        elif kind == "object" and state == "colon":
            if character != ":":
                raise ValueError("INVALID_JSON_DOCUMENT")
            current["state"] = "value"
            index += 1
        elif kind == "object" and state == "value":
            nodes += 1
            if nodes > max_structural_nodes:
                raise ValueError("JSON_STRUCTURAL_LIMIT_EXCEEDED")
            index = _start_json_value(document, index, containers, max_depth)
            current["state"] = "comma_or_end"
        elif kind == "object" and state == "comma_or_end":
            if character == ",":
                current["state"] = "key_or_end"
                index += 1
            elif character == "}":
                containers.pop()
                index += 1
            else:
                raise ValueError("INVALID_JSON_DOCUMENT")
        elif kind == "array" and state == "value_or_end":
            if character == "]":
                containers.pop()
                index += 1
            else:
                nodes += 1
                if nodes > max_structural_nodes:
                    raise ValueError("JSON_STRUCTURAL_LIMIT_EXCEEDED")
                index = _start_json_value(document, index, containers, max_depth)
                current["state"] = "comma_or_end"
        elif kind == "array" and state == "comma_or_end":
            if character == ",":
                current["state"] = "value_or_end"
                index += 1
            elif character == "]":
                containers.pop()
                index += 1
            else:
                raise ValueError("INVALID_JSON_DOCUMENT")
        else:
            raise ValueError("INVALID_JSON_DOCUMENT")
    if not root_consumed or containers:
        raise ValueError("INVALID_JSON_DOCUMENT")


def _start_json_value(
    document: str,
    index: int,
    containers: list[dict[str, str]],
    max_depth: int,
) -> int:
    character = document[index]
    if character in "[{":
        if len(containers) >= max_depth:
            raise ValueError("JSON_DEPTH_LIMIT_EXCEEDED")
        containers.append({
            "kind": "array" if character == "[" else "object",
            "state": "value_or_end" if character == "[" else "key_or_end",
        })
        return index + 1
    if character == '"':
        return _skip_json_string(document, index)
    end = index
    while end < len(document) and document[end] not in " \t\r\n,]}:":
        end += 1
    if end == index:
        raise ValueError("INVALID_JSON_DOCUMENT")
    return end


def _skip_json_string(document: str, index: int) -> int:
    index += 1
    while index < len(document):
        character = document[index]
        if character == '"':
            return index + 1
        if character == "\\":
            index += 2
        else:
            index += 1
    raise ValueError("INVALID_JSON_DOCUMENT")


__all__ = [
    "MAX_JSON_DOCUMENT_DEPTH",
    "MAX_JSON_DOCUMENT_STRUCTURAL_NODES",
    "check_json_document_limits",
]
