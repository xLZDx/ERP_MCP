"""Synthetic Ed25519 signing identities of the change-ledger tests (lane TEST, simulation program P1b-2).

Every seed is the SHA-256 of a plain label (the key id), so it is synthetic, public and reproducible; none of these keys
protects anything and none may ever gain a production entitlement. The signer is the stdlib test-lane signer
business_ai_gateway.phase2.ed25519 (not audited, not constant-time). The ledger verifies the same bytes with
change_ledger.ed25519_verify (migration 014) through change_ledger.signature_ok (migration 015).
"""
import hashlib
from functools import lru_cache

from business_ai_gateway.phase2 import ed25519


def seed_of(label: str) -> bytes:
    """TEST lane seed: sha256 of the label."""
    return hashlib.sha256(label.encode()).digest()


@lru_cache(maxsize=None)
def pub_hex(label: str) -> str:
    """Lowercase hex of the 32-byte public key: the key_material of an ED25519 verifier key."""
    return ed25519.public_key_from_seed(seed_of(label)).hex()


def sign_hex(label: str, payload_text: str) -> str:
    """128 lowercase hex characters: the Ed25519 signature over the UTF-8 bytes of the payload text."""
    return ed25519.sign(seed_of(label), payload_text.encode("utf-8")).hex()
