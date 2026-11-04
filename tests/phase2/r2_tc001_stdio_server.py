"""Test-only child process that serves a revision's real public MCP tool registry."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace


def _append(event: dict) -> None:
    path = Path(os.environ["R2_TC001_EVENT_LOG"])
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")


def _safe_settings(settings) -> dict:
    values = settings.model_dump(mode="json")
    sensitive = re.compile(
        r"(?:url|dsn|database|token|secret|password|credential|key|root|file|cidr|host|ip|path)",
        re.I,
    )
    redacted = sorted(name for name in values if sensitive.search(name))
    return {
        "effective": {
            "environment": settings.environment,
            "oauth_enabled": settings.oauth_enabled,
            "oauth_required_scope": settings.oauth_required_scope,
            "business_capability_enforcement_enabled": bool(getattr(
                settings, "business_capability_enforcement_enabled", False
            )),
            "max_rows": settings.max_rows,
            "rate_limit_per_minute": settings.rate_limit_per_minute,
            "audit_include_query": settings.audit_include_query,
            "require_metadata_entity": settings.require_metadata_entity,
        },
        "inventory": {
            name: ("<REDACTED>" if sensitive.search(name) else value)
            for name, value in sorted(values.items())
        },
        "redacted_fields": redacted,
        "field_presence": {
            "business_capability_enforcement_enabled": hasattr(
                settings, "business_capability_enforcement_enabled"
            ),
        },
    }


class RecordingAudit:
    async def write(self, **event):
        _append({
            "kind": "audit",
            "tool": event.get("tool"),
            "source_id": event.get("source_id"),
            "outcome": event.get("outcome"),
            "detail_code": event.get("detail_code"),
            "policy_version": event.get("policy_version"),
            "record_tool_outcome": event.get("record_tool_outcome", True),
            "returned_items": event.get("returned_items"),
        })


class RecordingRegistry:
    async def require_source(self, _principal, source_id):
        _append({"kind": "authorization", "source_id": source_id, "decision": "allow"})
        return SimpleNamespace(id=source_id)

    async def save_capabilities(self, _capabilities):
        return {"drift_status": "ACKNOWLEDGED"}


class RecordingRateLimit:
    async def check(self, *, subject, source_id, tool):
        _append({
            "kind": "rate_limit", "subject": subject, "source_id": source_id,
            "tool": tool, "decision": "allow",
        })


class SyntheticOneCAdapter:
    def __init__(self, fixture: dict):
        self.fixture = fixture

    async def health(self, source):
        _append({"kind": "adapter", "tool": "source_health", "operation": "health_read", "source_id": source.id})
        if source.id == "synthetic-timeout":
            raise TimeoutError("deterministic synthetic timeout")
        return self.fixture["health_response"]

    async def capabilities(self, source):
        return SimpleNamespace(
            source_id=source.id,
            adapter_profile=SimpleNamespace(value="SYNTHETIC"),
            metadata_fingerprint="fixture-metadata-v1",
        )

    async def read(self, source, **arguments):
        _append({
            "kind": "adapter", "tool": "onec_read", "operation": "read", "source_id": source.id,
            "arguments": arguments,
        })
        return self.fixture["read_response"]


class FakeRuntime:
    def __init__(self, fixture: dict):
        self.audit = RecordingAudit()
        self.registry = RecordingRegistry()
        self.rate_limit = RecordingRateLimit()
        self.onec = SyntheticOneCAdapter(fixture)

    async def start(self):
        return None

    async def close(self):
        return None


def main() -> None:
    src = Path(os.environ["R2_TC001_SOURCE_ROOT"]).resolve()
    sys.path.insert(0, str(src))
    from business_ai_gateway.server import build_mcp
    from business_ai_gateway.settings import Settings

    fixture_path = Path(os.environ["R2_TC001_FIXTURE"]).resolve()
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    _append({
        "kind": "process",
        "pid": os.getpid(),
        "python": sys.executable,
        "source_root": str(src),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "environment": "test",
    })
    settings = Settings(environment="test")
    _append({"kind": "settings_snapshot", **_safe_settings(settings)})
    build_mcp(settings, FakeRuntime(fixture)).run("stdio")


if __name__ == "__main__":
    main()
