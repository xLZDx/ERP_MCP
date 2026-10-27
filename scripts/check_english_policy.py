#!/usr/bin/env python3
"""Report Cyrillic, allowing only documented path/line/hash exceptions."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "governance" / "ENGLISH_POLICY_ALLOWLIST.json"
SCANNED_SUFFIXES = {
    ".bat", ".c", ".cc", ".cfg", ".cmd", ".conf", ".cpp", ".cs", ".css", ".csv",
    ".dart", ".diff", ".go", ".graphql", ".h", ".hcl", ".hpp", ".html", ".ini",
    ".ipynb", ".java", ".js", ".json", ".jsonc", ".jsx", ".kt", ".lock", ".lua",
    ".m", ".md", ".mdx", ".mjs", ".mm", ".nix", ".patch", ".php", ".pl", ".properties",
    ".proto", ".ps1", ".psm1", ".py", ".r", ".rb", ".rst", ".rs", ".sass", ".scss",
    ".sh", ".sql", ".swift", ".tf", ".toml", ".ts", ".tsx", ".txt", ".tsv", ".vue",
    ".xml", ".yaml", ".yml",
}
SCANNED_NAMES = {
    ".dockerignore", ".editorconfig", ".gitattributes", ".gitignore", ".npmrc",
    ".prettierrc", "Containerfile", "Dockerfile", "Justfile", "LICENSE", "Makefile",
    "NOTICE", "Procfile", "Vagrantfile",
}
CYRILLIC = re.compile(r"[\u0400-\u04ff]")


def main() -> int:
    raw_entries = subprocess.run(
        ["git", "ls-files", "--stage", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    tracked: list[Path] = []
    for entry in raw_entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0]
        if mode == b"120000":
            continue
        tracked.append(Path(raw_path.decode("utf-8")))
    tracked = sorted(set(tracked), key=lambda path: path.as_posix())
    exceptions = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    valid_entries = all(
        isinstance(path, str)
        and (
            (isinstance(rule, str) and bool(rule))
            or (
                isinstance(rule, dict)
                and isinstance(rule.get("reason"), str)
                and bool(rule["reason"])
                and isinstance(rule.get("allowed_lines"), list)
                and all(
                    isinstance(item, dict)
                    and isinstance(item.get("line"), int)
                    and not isinstance(item.get("line"), bool)
                    and item["line"] > 0
                    and isinstance(item.get("sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                    for item in rule["allowed_lines"]
                )
            )
        )
        for path, rule in exceptions.items()
    ) if isinstance(exceptions, dict) else False
    if not valid_entries:
        print(f"Invalid allowlist: {ALLOWLIST.relative_to(ROOT).as_posix()}", file=sys.stderr)
        return 2

    tracked_names = {path.as_posix() for path in tracked}
    stale = sorted(set(exceptions) - tracked_names)
    stale_lines: list[tuple[str, int, str]] = []
    violations: list[tuple[str, int, str]] = []
    read_errors: list[tuple[str, str]] = []
    for relative_path in tracked:
        path_text = relative_path.as_posix()
        if relative_path.suffix not in SCANNED_SUFFIXES and relative_path.name not in SCANNED_NAMES:
            continue
        full_path = ROOT / relative_path
        try:
            if not stat.S_ISREG(full_path.lstat().st_mode):
                continue
            raw_content = full_path.read_bytes()
        except OSError as error:
            read_errors.append((path_text, error.__class__.__name__))
            continue
        try:
            if raw_content.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
                read_errors.append((path_text, "unsupported UTF-32 BOM in a text-suffix file"))
                continue
            if raw_content.startswith((b"\xff\xfe", b"\xfe\xff")):
                content = raw_content.decode("utf-16")
            else:
                if b"\0" in raw_content:
                    read_errors.append((path_text, "NUL byte in a text-suffix file"))
                    continue
                content = raw_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            read_errors.append((path_text, "invalid BOM-marked UTF-16 or UTF-8 text"))
            continue
        if "\0" in content:
            read_errors.append((path_text, "NUL character in decoded text"))
            continue
        rule = exceptions.get(path_text)
        if isinstance(rule, str):
            continue
        allowed_lines = {
            (item["line"], item["sha256"])
            for item in rule.get("allowed_lines", [])
        } if rule else set()
        seen_lines: set[tuple[int, str]] = set()
        for line_number, line in enumerate(content.splitlines(), 1):
            if not CYRILLIC.search(line):
                continue
            digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
            line_key = (line_number, digest)
            seen_lines.add(line_key)
            if line_key not in allowed_lines:
                violations.append((path_text, line_number, digest))
        stale_lines.extend(
            (path_text, line_number, digest)
            for line_number, digest in sorted(allowed_lines - seen_lines)
        )

    for path, rule in sorted(exceptions.items()):
        if path in stale:
            reason = rule if isinstance(rule, str) else rule["reason"]
            print(f"STALE_ALLOWLIST {path}: {reason}")
    for path, line_number, digest in violations:
        print(f"CYRILLIC {path}:{line_number}: sha256={digest}")
    for path, line_number, digest in stale_lines:
        print(f"STALE_ALLOWLIST_LINE {path}:{line_number}: sha256={digest}")
    for path, reason in read_errors:
        print(f"UNREADABLE {path}: {reason}")
    print(
        f"tracked files: {len(tracked)}; violations: {len(violations)}; "
        f"stale allowlist entries: {len(stale)}; stale line exceptions: {len(stale_lines)}; "
        f"unreadable text files: {len(read_errors)}"
    )
    return 2 if read_errors else (1 if violations or stale or stale_lines else 0)


if __name__ == "__main__":
    raise SystemExit(main())
