"""Phase 2 simulation program (offline, pure Python, TEST lane only).

Deterministic in-memory stand-ins used by simulation scenarios: ``clone_1c`` (a simulated 1C test clone for the
supplier-document use case), ``attestation`` (a synthetic Ed25519 attestor) and ``synthetic_data`` (a seeded
generator of synthetic organizations, counterparties, contracts, items and payloads). Nothing here touches a
database, a network or a real 1C base; every record is synthetic and carries ``lane='TEST'``.
"""
from __future__ import annotations
