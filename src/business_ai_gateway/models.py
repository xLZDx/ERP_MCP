from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any
from urllib.parse import urlparse
from uuid import UUID


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
    platform_version_hint: str | None = None
    fallback_kind: str | None = None
    fallback_base_url: str | None = None

    def validate_runtime(self, *, production: bool):
        if self.project != "onec" or self.kind not in {"onec_odata", "onec_auto"}:
            raise ValueError("1C MVP supports only onec/onec_odata or onec/onec_auto")
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

        if self.fallback_kind is not None and self.fallback_kind != "onec_http_query":
            raise ValueError("unsupported 1C fallback kind")
        if self.fallback_base_url:
            fallback = urlparse(self.fallback_base_url)
            if fallback.scheme not in {"http", "https"} or not fallback.hostname:
                raise ValueError("fallback_base_url must be absolute HTTP(S)")
            if fallback.username or fallback.password or fallback.query or fallback.fragment:
                raise ValueError("credentials/query/fragment in fallback URL are forbidden")
            if production and fallback.scheme != "https":
                raise ValueError("production 1C fallback must use HTTPS")

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
    navigation_properties: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Company:
    id: UUID
    source_id: str
    external_ref: str
    display_name: str
    legal_name: str | None
    country_code: str | None
    enabled: bool
    is_default: bool


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
        platform_version_hint=row["platform_version_hint"],
        fallback_kind=row["fallback_kind"],
        fallback_base_url=row["fallback_base_url"],
    )


def company_from_record(row: Any) -> Company:
    return Company(
        id=row["company_id"],
        source_id=row["source_id"],
        external_ref=row["external_ref"],
        display_name=row["display_name"],
        legal_name=row["legal_name"],
        country_code=row["country_code"],
        enabled=row["enabled"],
        is_default=row["is_default"],
    )
