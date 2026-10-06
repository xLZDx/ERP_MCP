"""Bounded artifact verification; no generator/oracle computation or native write path."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .schema import ScenarioManifest

MAX_FILE_BYTES = 8_000_000
MAX_TOTAL_BYTES = 32_000_000
MAX_RECORDS = 20_000
FILES = frozenset({"manifest.json", "master-data.jsonl", "events.jsonl",
                   "expected/positions.jsonl", "expected/correspondences.jsonl",
                   "expected/inventory.jsonl"})
REQUIRED = frozenset({"manifest.json", "master-data.jsonl", "events.jsonl",
                      "expected/positions.jsonl"})
EVENT_TYPES = frozenset({"com.ferma.trade.executed.v1", "com.ferma.payment.instructed.v1",
                         "com.ferma.payment.settled.v1", "com.ferma.credit_note.issued.v1",
                         "com.ferma.partial_invoice.issued.v1", "com.ferma.inventory.moved.v1",
                         "com.ferma.inventory.returned.v1"})


@dataclass(frozen=True)
class SeedInputs:
    manifest: ScenarioManifest
    master_data: tuple[Any, ...]
    events: tuple[Any, ...]


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _json(raw: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("non-finite JSON number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _read(root: Path, name: str) -> bytes:
    relative = PurePosixPath(name)
    if name not in FILES and name != "checksums.sha256":
        raise ValueError("unapproved scenario path")
    target = root
    for component in relative.parts:
        target = target / component
        if target.is_symlink():
            raise ValueError("scenario symlinks are forbidden")
    if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("scenario file missing or oversized")
    with target.open("rb") as stream:
        payload = stream.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError("scenario file exceeded limit")
    return payload


def verify(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("scenario root must be a real directory")
    contents = {}
    total = 0
    actual_paths = set()
    paths = []
    for path in root.iterdir():
        if len(paths) >= len(FILES) + 1:
            raise ValueError("unexpected scenario entries")
        if path.is_symlink():
            raise ValueError("scenario symlinks are forbidden")
        if path.is_dir():
            if path.name != "expected":
                raise ValueError("unexpected scenario directory")
            for child in path.iterdir():
                paths.append(child)
                if len(paths) > len(FILES) + 1:
                    raise ValueError("too many scenario entries")
        else:
            paths.append(path)
    for path in paths:
        if path.is_symlink():
            raise ValueError("scenario symlinks are forbidden")
        if not path.is_file():
            raise ValueError("unexpected scenario directory")
        if path.is_file():
            actual_paths.add(path.relative_to(root).as_posix())
            if len(actual_paths) > len(FILES) + 1:
                raise ValueError("unexpected scenario files")
    for line in _read(root, "checksums.sha256").decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([a-zA-Z0-9./-]+)", line)
        if not match:
            raise ValueError("invalid checksum entry")
        digest, name = match.groups()
        if name in contents:
            raise ValueError("duplicate checksum path")
        raw = _read(root, name)
        total += len(raw)
        if total > MAX_TOTAL_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("scenario size or digest mismatch")
        contents[name] = raw
    if not REQUIRED.issubset(contents):
        raise ValueError("required scenario artifacts absent from checksums")
    if actual_paths != set(contents) | {"checksums.sha256"}:
        raise ValueError("scenario contains unverified files")
    return contents


def _records(raw: bytes) -> tuple[dict[str, Any], ...]:
    rows = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        item = _json(line)
        if not isinstance(item, dict):
            raise TypeError("scenario record must be an object")
        rows.append(item)
        if len(rows) > MAX_RECORDS:
            raise ValueError("scenario record limit exceeded")
    return tuple(rows)


def load_seed_inputs(root: Path) -> SeedInputs:
    # Verification belongs to package intake. Only the three seed artifacts leave this boundary;
    # no expected paths or oracle values are supplied to a command/seeder consumer.
    contents = verify(root)
    manifest = ScenarioManifest.model_validate(_json(contents["manifest.json"].decode("utf-8")))
    master = _records(contents["master-data.jsonl"])
    events = _records(contents["events.jsonl"])
    identities = set()
    for event in events:
        if event.get("event_type") not in EVENT_TYPES:
            raise ValueError("unsupported canonical event type")
        for key in ("scenario_id", "run_id", "universe_id"):
            if event.get(key) != getattr(manifest, key):
                raise ValueError("event scope does not match scenario")
        identity = event.get("event_id")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("event identity missing or duplicated")
        identities.add(identity)
        if event.get("schema_version") != "1.0.0" or type(event.get("simulation_tick")) is not int or event["simulation_tick"] < 0:
            raise ValueError("canonical envelope version/tick is invalid")
        for key in ("idempotency_key", "correlation_id", "business_date"):
            if not isinstance(event.get(key), str) or not event[key] or len(event[key]) > 256:
                raise ValueError("canonical envelope field missing or oversized")
        if datetime.fromisoformat(event["business_date"]).utcoffset() is None:
            raise ValueError("business date requires an explicit timezone")
        if event["event_type"] == "com.ferma.trade.executed.v1":
            if any(key in event for key in ("total", "line_total", "expected", "oracle")):
                raise ValueError("trade carries derived oracle/total rather than facts")
            if event.get("trade_id") != event["idempotency_key"]:
                raise ValueError("trade idempotency key differs from canonical trade identity")
            for field in ("quantity", "unit_price"):
                fact = event.get(field, "")
                if type(fact) not in (str, int, float) or len(str(fact)) > 64:
                    raise ValueError("invalid or oversized trade numeric fact")
                try:
                    amount = Decimal(str(fact))
                except (InvalidOperation, TypeError, ValueError):
                    raise ValueError("invalid trade numeric fact") from None
                if not amount.is_finite() or amount <= 0:
                    raise ValueError("trade facts must be finite and positive")
    return SeedInputs(manifest, tuple(_freeze(item) for item in master),
                      tuple(_freeze(item) for item in events))
