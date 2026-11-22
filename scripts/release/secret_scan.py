"""Secret scan for the release tree (no gitleaks/trufflehog installed).

Scans tracked + untracked-not-ignored files (the packaging allowlist) and the
production build output. Reports only the file path and the secret *type* —
never the value.

Exit code 0 when no finding, 1 when any finding.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key-block",
        # A real key has a base64 body and an END marker; detection patterns in
        # redaction code only contain the label.
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]{40,8000}?"
            r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
        ),
    ),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("stripe-live-key", re.compile(r"\bsk_live_[0-9A-Za-z]{16,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}\b")),
    (
        "assigned-credential",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token|refresh[_-]?token)\b"
            r"\s*[=:]\s*['\"]([A-Za-z0-9_\-./+=:]{16,})['\"]"
        ),
    ),
    (
        "database-url-with-password",
        re.compile(r"(?i)postgres(?:ql)?(?:\+psycopg)?://[^:\s/]+:([^@\s]{6,})@"),
    ),
]

PLACEHOLDERS = (
    "change-me",
    "changeme",
    "placeholder",
    "your-",
    "example",
    "dummy",
    "test-secret",
    "test-only",
    "ci-only",
    "not-a-real",
    "mock",
    "dev-secret",
    "<",
    "redacted",
    "xxxx",
    "${",
)

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "playwright-report",
    "test-results",
    "final-release-evidence",
}
EXCLUDE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".dump", ".gz", ".pyc"}


def allowlist() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout
    files = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        p = REPO / raw.decode()
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(REPO).parts):
            continue
        if p.suffix.lower() in EXCLUDE_EXT:
            continue
        files.append(p)
    return files


def scan_file(path: Path) -> list[tuple[str, int]]:
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return []
    hits = []
    for name, pattern in PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(0)
            if any(ph in value.lower() for ph in PLACEHOLDERS):
                continue
            line = text.count("\n", 0, m.start()) + 1
            hits.append((name, line))
            break  # one hit per type per file is enough for the report
    return hits


def walk_tree(root: Path) -> list[Path]:
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in EXCLUDE_EXT:
            continue
        files.append(p)
    return files


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if target is not None:
        roots = walk_tree(target)
        findings = []
        for path in roots:
            for name, line in scan_file(path):
                findings.append({"file": str(path.relative_to(target)), "type": name, "line": line})
        for f in findings:
            print(f"FINDING {f['type']} {f['file']}:{f['line']}")
        print(f"SCANNED {len(roots)} files; FINDINGS {len(findings)}")
        return 1 if findings else 0
    roots = allowlist()
    build = REPO / "dist"
    if build.exists():
        roots += [p for p in build.rglob("*") if p.is_file() and p.suffix in (".js", ".html", ".css")]
    findings = []
    for path in roots:
        for name, line in scan_file(path):
            findings.append({"file": str(path.relative_to(REPO)), "type": name, "line": line})
    for f in findings:
        print(f"FINDING {f['type']} {f['file']}:{f['line']}")
    print(f"SCANNED {len(roots)} files; FINDINGS {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
