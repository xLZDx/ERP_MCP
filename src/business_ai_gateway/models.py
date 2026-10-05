from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    project: str
    kind: str
    display_name: str
    base_url: str
    username_secret_ref: str | None
    password_secret_ref: str | None
    read_only: bool
    enabled: bool
    tags: tuple[str, ...]
    entity_allow_patterns: tuple[str, ...]
    entity_deny_patterns: tuple[str, ...]

    def validate_runtime(self, *, production: bool):
        if self.project != "onec" or self.kind != "onec_odata":
            raise ValueError("1C MVP supports only onec/onec_odata")
        if not self.read_only:
            raise ValueError("writable source is forbidden")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("source base_url must be absolute HTTP(S)")
        if parsed.username or parsed.password:
            raise ValueError("credentials in source URL are forbidden")
        if parsed.query or parsed.fragment:
            raise ValueError("source base_url must not contain query/fragment")
        if production and parsed.scheme != "https":
            raise ValueError("production 1C source must use HTTPS")

    def entity_allowed(self, entity: str) -> bool:
        if self.entity_deny_patterns and any(
            fnmatch(entity, pattern) for pattern in self.entity_deny_patterns
        ):
            return False
        if not self.entity_allow_patterns:
            return True
        return any(fnmatch(entity, pattern) for pattern in self.entity_allow_patterns)


@dataclass(frozen=True, slots=True)
class MetadataEntity:
    name: str
    entity_type: str
    properties: tuple[str, ...]


def source_from_record(row: Any) -> Source:
    return Source(
        id=row["source_id"],
        project=row["project"],
        kind=row["kind"],
        display_name=row["display_name"],
        base_url=row["base_url"],
        username_secret_ref=row["username_secret_ref"],
        password_secret_ref=row["password_secret_ref"],
        read_only=row["read_only"],
        enabled=row["enabled"],
        tags=tuple(row["tags"] or []),
        entity_allow_patterns=tuple(row["entity_allow_patterns"] or []),
        entity_deny_patterns=tuple(row["entity_deny_patterns"] or []),
    )
