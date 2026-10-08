"""Operator helper for the COM route of ``accounting_balance_by_analytics`` (ADR-0008 section 6).

``draft`` writes a bindings file whose single binding is **REVOKED**: the tool computes the derived values (base-URL
hash, configuration fingerprint) so nobody types them by hand, but it never approves anything. Approval is the
operator's act: review the file, change ``status`` to ``APPROVED`` yourself, then run ``pin`` and put the printed
sha256 into ``BAG_COM_BINDINGS_SHA256``. The file must live outside Git and outside any symlink or junction, in a private directory
(the gateway refuses a file that is not owner-only).

    python -m scripts.real1c.com_binding_tool draft --out C:/private/com_bindings.json --source-id <id> \
        --binding-id <id> --version 1 --base-url <source base url> --credential-identity <username secret ref> \
        --clone-identity <base identity> --platform-version 8.3.27.2342 --metadata-fingerprint <64 hex> \
        --company <external company guid> [--company ...]
    python -m scripts.real1c.com_binding_tool pin --file C:/private/com_bindings.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from business_ai_gateway.analytics_balance import load_com_bindings
from business_ai_gateway.evidence_store import _write_new


def configuration_fingerprint(platform_version: str, adapter_profile: str) -> str:
    """Same formula as ``analytics_balance.configuration_fingerprint`` for a capability object."""
    if not platform_version or not adapter_profile:
        raise SystemExit("platform version and adapter profile are required (set platform_version_hint on the source)")
    return hashlib.sha256(f"{platform_version}:{adapter_profile}".encode()).hexdigest()


def build_draft(args: argparse.Namespace, now: datetime | None = None) -> dict:
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": 1,
        "bindings": [{
            "source_id": args.source_id,
            "binding_id": args.binding_id,
            "version": args.version,
            "clone_identity": args.clone_identity,
            "configuration_fingerprint": configuration_fingerprint(args.platform_version, args.adapter_profile),
            "metadata_fingerprint": args.metadata_fingerprint,
            "source_base_url_sha256": hashlib.sha256(args.base_url.encode()).hexdigest(),
            "credential_identity": args.credential_identity,
            "allowed_company_refs": list(args.company),
            "status": "REVOKED",  # never approved by a tool
            "approved_at": stamp,
        }],
    }


def cmd_draft(args: argparse.Namespace) -> int:
    document = build_draft(args)
    data = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    out = Path(args.out)
    _write_new(out, data)  # exclusive create with an owner-only ACL: an existing file is never overwritten
    load_com_bindings(out, hashlib.sha256(data).hexdigest())  # the gateway's own loader must accept it
    print(f"draft written: {out} (status REVOKED; review it, set APPROVED yourself, then run `pin`)")
    return 0


def cmd_pin(args: argparse.Namespace) -> int:
    path = Path(args.file)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    load_com_bindings(path, digest)  # refuses an invalid file
    print(digest)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="com_binding_tool")
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("--out", required=True)
    draft.add_argument("--source-id", required=True)
    draft.add_argument("--binding-id", required=True)
    draft.add_argument("--version", type=int, required=True)
    draft.add_argument("--base-url", required=True)
    draft.add_argument("--credential-identity", required=True)
    draft.add_argument("--clone-identity", required=True)
    draft.add_argument("--platform-version", required=True)
    draft.add_argument("--adapter-profile", default="ODATA_JSON_V3")
    draft.add_argument("--metadata-fingerprint", required=True)
    draft.add_argument("--company", action="append", required=True)
    draft.set_defaults(func=cmd_draft)
    pin = sub.add_parser("pin")
    pin.add_argument("--file", required=True)
    pin.set_defaults(func=cmd_pin)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
