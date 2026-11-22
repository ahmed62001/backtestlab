#!/usr/bin/env python3
"""Verify the vendored Vibe-Trading snapshot against its checksum manifest.

The vendor tree is committed as plain files (no submodule/subtree), so the only
cheap way to detect an accidental local edit or a truncated copy is a manifest.
Run after changing anything under ``backend/vendor`` and regenerate the file:

    cd backend/vendor/Vibe-Trading
    find . -type f ! -name SHA256SUMS -printf '%P\\0' | sort -z | xargs -0 sha256sum > SHA256SUMS
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "Vibe-Trading"
MANIFEST = VENDOR_DIR / "SHA256SUMS"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not MANIFEST.is_file():
        print(f"FAIL: missing manifest {MANIFEST}", file=sys.stderr)
        return 2
    expected: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, rel = line.partition("  ")
        if not rel:
            print(f"FAIL: malformed manifest line: {line!r}", file=sys.stderr)
            return 2
        expected[rel] = digest

    actual = {
        str(path.relative_to(VENDOR_DIR))
        for path in VENDOR_DIR.rglob("*")
        if path.is_file() and path != MANIFEST
    }
    missing = sorted(set(expected) - actual)
    unexpected = sorted(actual - set(expected))
    changed = sorted(
        rel for rel in set(expected) & actual if _sha256(VENDOR_DIR / rel) != expected[rel]
    )

    if missing or unexpected or changed:
        for rel in missing:
            print(f"MISSING   {rel}", file=sys.stderr)
        for rel in unexpected:
            print(f"UNTRACKED {rel}", file=sys.stderr)
        for rel in changed:
            print(f"CHANGED   {rel}", file=sys.stderr)
        print(
            f"FAIL: vendor integrity violated "
            f"({len(missing)} missing, {len(unexpected)} untracked, {len(changed)} changed)",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {len(expected)} vendor files match {MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
