"""Separate, loopback-only development checkpoint anchor service.

This package is deliberately not mounted into the business gateway. Its SQLite history and
authority keys are a dev trust boundary outside PostgreSQL roles, not production retention
evidence or an S13 readiness implementation.
"""

from .service import (
    AnchorServiceError,
    DevAnchorConfig,
    DevAnchorSigner,
    KEY_AUTH_SIGNING_DOMAIN,
    LATESTNESS_SIGNING_DOMAIN,
    SQLiteAnchorStore,
    create_app,
)
from .runtime import load_dev_runtime

__all__ = [
    "AnchorServiceError",
    "DevAnchorConfig",
    "DevAnchorSigner",
    "KEY_AUTH_SIGNING_DOMAIN",
    "LATESTNESS_SIGNING_DOMAIN",
    "SQLiteAnchorStore",
    "create_app",
    "load_dev_runtime",
]
