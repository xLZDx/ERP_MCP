"""Bind the current status snapshot to implementation content without self-referential commits."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOTS = ("src", "tests", "scripts", "testbed", "adapters", "deploy", ".github")
DEPENDENCIES = ("pyproject.toml", "uv.lock", "requirements-runtime.lock", "vendor/intake.json")
REPORTS = ("reports/IMPLEMENTATION_STATUS.md", "reports/DOD_STATUS.md", "reports/RISK_STATUS.md",
           "reports/EXECUTION_LOG.md", "ERP_MCP_ENGINEERING_COMMAND_CENTER.html",
           "docs/ERP_MCP_ENGINEERING_COMMAND_CENTER.html")
IGNORED = {"node_modules", ".pnpm", "__pycache__", ".pytest_cache", ".ruff_cache", ".git",
           "build", "dist", "var"}
TEXT = {".py", ".js", ".mjs", ".json", ".lock", ".toml", ".yaml", ".yml", ".md", ".txt", ".xml", ".html"}


def implementation_fingerprint(root: Path) -> str:
    paths = set()
    for directory in ROOTS:
        for path in (root / directory).rglob("*"):
            parts = path.relative_to(root).parts
            generated = any(part.endswith(".egg-info") for part in parts) or path.suffix == ".pyc"
            private_env = path.name.startswith(".env") and not path.name.endswith(".example")
            if path.is_file() and not generated and not private_env and not IGNORED.intersection(parts):
                paths.add(path)
    paths.update(root / name for name in DEPENDENCIES if (root / name).is_file())
    if not paths or len(paths) > 5000:
        raise ValueError("implementation inventory is empty or exceeds its bound")
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError("implementation inventory contains a symlink")
        content = path.read_bytes()
        # Any text file (known extension, Dockerfile, or no NUL byte, e.g. .ps1/.sh/.sql/.css) is hashed
        # with LF endings so a Windows CRLF checkout and a Linux checkout fingerprint the same Git content.
        if path.suffix in TEXT or path.name == "Dockerfile" or b"\0" not in content:
            content = content.replace(b"\r\n", b"\n")
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def check_checkpoint(root: Path) -> dict:
    checkpoint = json.loads((root / "reports/CURRENT_ENGINEERING_CHECKPOINT.json").read_text(encoding="utf-8"))
    if type(checkpoint.get("schema_version")) is not int or checkpoint.get("schema_version") != 1:
        raise ValueError("unsupported checkpoint schema")
    batch = checkpoint.get("batch_id", "")
    if not isinstance(batch, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,63}", batch):
        raise ValueError("invalid checkpoint batch ID")
    if checkpoint.get("implementation_sha256") != implementation_fingerprint(root):
        raise ValueError("stale engineering checkpoint: implementation content changed")
    if checkpoint.get("production_decision") != "NO-GO" or checkpoint.get("dod_status") != "PARTIAL":
        raise ValueError("frozen gates do not authorize engineering/production closure")
    if checkpoint.get("pr_number") != 11 or checkpoint.get("pr_state") != "DRAFT":
        raise ValueError("unexpected PR disposition")
    for report in REPORTS:
        content = (root / report).read_text(encoding="utf-8")
        if f"ENGINEERING_CHECKPOINT={batch}" not in content:
            raise ValueError("report is missing the current checkpoint marker")
        if f"ENGINEERING_IMPLEMENTATION={checkpoint['implementation_sha256']}" not in content:
            raise ValueError("report implementation fingerprint is stale")
    root_html = (root / REPORTS[-2]).read_text(encoding="utf-8")
    docs_html = (root / REPORTS[-1]).read_text(encoding="utf-8")
    if root_html != docs_html:
        raise ValueError("dashboard copies differ")
    return checkpoint
