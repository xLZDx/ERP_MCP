"""Reference-lane manifest: canonical hash, gate, drift check, sanitised summary."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
SELF_KEY = "manifest_sha256"


class ManifestGateError(Exception):
    """The reference manifest is missing, tampered or incomplete."""


class FingerprintDrift(Exception):
    """The database fingerprint changed during the run."""


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k != SELF_KEY}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def _hex64(v: Any) -> bool:
    return isinstance(v, str) and bool(_HEX64.match(v))


def _check_shape(m: Mapping[str, Any]) -> list[str]:
    errs: list[str] = []
    golden = m.get("golden")
    if not isinstance(golden, Mapping):
        errs.append("golden")
    else:
        size = golden.get("size_bytes")
        if not _hex64(golden.get("sha256")):
            errs.append("golden.sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            errs.append("golden.size_bytes")
        if not golden.get("source_date"):
            errs.append("golden.source_date")
    chain = m.get("chain")
    if not isinstance(chain, list) or len(chain) < 3 or not all(isinstance(x, str) for x in chain):
        errs.append("chain")
    if not m.get("platform_version"):
        errs.append("platform_version")
    cfg = m.get("configuration")
    if not isinstance(cfg, Mapping) or not cfg.get("name") or not cfg.get("version"):
        errs.append("configuration")
    if not _hex64(m.get("metadata_fingerprint")):
        errs.append("metadata_fingerprint")
    if not _hex64(m.get("odata_identity_sha256")):
        errs.append("odata_identity_sha256")
    orgs = m.get("organisations")
    if (
        not isinstance(orgs, list)
        or not orgs
        or not all(isinstance(o, Mapping) and _hex64(o.get("ref_sha256")) for o in orgs)
    ):
        errs.append("organisations")
    pre = m.get("pre_run_fingerprint")
    if not isinstance(pre, Mapping) or not _hex64(pre.get("sha256")):
        errs.append("pre_run_fingerprint.sha256")
    else:
        tc = pre.get("table_count")
        if not isinstance(tc, int) or isinstance(tc, bool) or tc <= 0:
            errs.append("pre_run_fingerprint.table_count")
    return errs


def verify_reference_manifest(
    path_or_none: str | Path | None, *, expected_git_sha: str | None = None
) -> dict[str, Any]:
    if path_or_none is None:
        raise ManifestGateError("reference manifest path not provided")
    try:
        manifest = json.loads(Path(path_or_none).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestGateError(f"reference manifest unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestGateError("reference manifest must be a JSON object")
    missing = _check_shape(manifest)
    if missing:
        raise ManifestGateError(f"manifest missing/invalid keys: {missing}")
    stored = manifest.get(SELF_KEY)
    if not _hex64(stored) or stored.lower() != manifest_hash(manifest):
        raise ManifestGateError("manifest_sha256 does not match recomputed hash")
    if expected_git_sha is not None and manifest.get("git_sha") != expected_git_sha:
        raise ManifestGateError("manifest git_sha does not match expected git sha")
    return manifest


def check_post_run(pre: Mapping[str, Any], post: Mapping[str, Any]) -> None:
    if pre.get("sha256") != post.get("sha256") or not _hex64(pre.get("sha256")):
        raise FingerprintDrift(
            f"fingerprint drift: pre={pre.get('sha256')!r} post={post.get('sha256')!r}"
        )


def sanitized_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Only hashes, counts, versions and dates; no names, refs, paths or urls."""
    golden = manifest.get("golden") or {}
    pre = manifest.get("pre_run_fingerprint") or {}
    cfg = manifest.get("configuration") or {}
    orgs = manifest.get("organisations") or []
    return {
        "golden_sha256": golden.get("sha256"),
        "golden_size_bytes": golden.get("size_bytes"),
        "golden_source_date": golden.get("source_date"),
        "chain_length": len(manifest.get("chain") or []),
        "platform_version": manifest.get("platform_version"),
        "configuration_version": cfg.get("version"),
        "metadata_fingerprint": manifest.get("metadata_fingerprint"),
        "odata_identity_sha256": manifest.get("odata_identity_sha256"),
        "organisation_count": len(orgs),
        "organisation_ref_sha256": [o.get("ref_sha256") for o in orgs if isinstance(o, Mapping)],
        "pre_run_fingerprint_sha256": pre.get("sha256"),
        "pre_run_table_count": pre.get("table_count"),
        SELF_KEY: manifest.get(SELF_KEY),
    }
