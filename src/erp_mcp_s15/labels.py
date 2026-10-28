"""Fixed labels attached to every S15 output (no production-readiness claim is ever made)."""
from __future__ import annotations

__all__ = ["LABEL_MACHINE_READ", "LABEL_MACHINE_VERIFIED"]

LABEL_MACHINE_VERIFIED = "machine verified, not accountant attested"
LABEL_MACHINE_READ = "machine-read agreement, not native 1C PASS"
