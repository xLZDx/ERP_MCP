"""Strict bridge configuration (JSON). Unknown keys are rejected; the loopback restriction is enforced here."""
from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path, PureWindowsPath
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MIN_TOKEN_LENGTH = 32

Identifier = Annotated[str, StringConstraints(pattern=ID_RE.pattern)]


class ConfigError(ValueError):
    """The configuration file is invalid. The message never contains values read from the file."""


def _no_connection_string_breakers(value: str) -> str:
    if not value or any(ch in value for ch in ('"', ";", "\x00", "\r", "\n")):
        raise ValueError("value is empty or contains a forbidden character")
    return value


class BindingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    binding_id: Identifier
    version: Annotated[int, Field(ge=1)]
    source_id: Identifier
    base_path: str  # file infobase directory
    reader_user: str
    reader_secret_file: str  # DPAPI blob placed by the operator; never in Git
    allowed_company_refs: Annotated[list[str], Field(min_length=1, max_length=64)]
    clone_identity: Identifier
    metadata_fingerprint: str | None = None

    @field_validator("base_path", "reader_user")
    @classmethod
    def _plain(cls, value: str) -> str:
        return _no_connection_string_breakers(value)

    @field_validator("reader_secret_file")
    @classmethod
    def _secret_path(cls, value: str) -> str:
        if not value or "\x00" in value:
            raise ValueError("invalid path")
        return value

    @field_validator("base_path")
    @classmethod
    def _absolute(cls, value: str) -> str:
        if not PureWindowsPath(value).is_absolute():
            raise ValueError("base path must be absolute")
        return value

    @field_validator("allowed_company_refs")
    @classmethod
    def _companies(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or not all(GUID_RE.match(v) for v in value):
            raise ValueError("company refs must be distinct lowercase GUIDs")
        return value

    @field_validator("metadata_fingerprint")
    @classmethod
    def _fingerprint(cls, value: str | None) -> str | None:
        if value is not None and not FINGERPRINT_RE.match(value):
            raise ValueError("metadata fingerprint must be 64 lowercase hex characters")
        return value


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    listen_host: str
    listen_port: Annotated[int, Field(ge=1, le=65535)]
    token_file: str
    call_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30.0
    bindings: Annotated[list[BindingConfig], Field(min_length=1, max_length=256)]

    @field_validator("listen_host")
    @classmethod
    def _loopback(cls, value: str) -> str:
        if not is_loopback_host(value):
            raise ValueError("the bridge may only listen on a loopback address")
        return value

    @model_validator(mode="after")
    def _unique(self) -> BridgeConfig:
        ids = [b.binding_id for b in self.bindings]
        if len(set(ids)) != len(ids):
            raise ValueError("binding ids must be unique")
        return self

    def binding(self, binding_id: str) -> BindingConfig | None:
        for item in self.bindings:
            if item.binding_id == binding_id:
                return item
        return None


def load_config(path: str | Path) -> BridgeConfig:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return BridgeConfig.model_validate(raw)
    except Exception:  # noqa: BLE001 - validation errors echo the offending values; expose none of them
        raise ConfigError("bridge configuration is invalid") from None


def read_token(path: str | Path) -> str:
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        raise ConfigError("bridge token file is unreadable") from None
    if len(token) < MIN_TOKEN_LENGTH or any(ch.isspace() for ch in token):
        raise ConfigError("bridge token is too short or malformed")
    return token
