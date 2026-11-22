"""Phase 13 — vendored code hygiene gates.

The vendored Vibe-Trading engine is a pinned, untracked-by-upstream snapshot.
These tests keep the contract honest: license/attribution survive, the pin is
consistent across the repo, the tree is committed as regular files (no nested
git repo), caches/large binaries are absent, and tooling excludes it sensibly.
"""

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VENDOR = BASE / "vendor"
VIBE = VENDOR / "Vibe-Trading"
COMMIT = "c546e877274e7d36056c042808e1a875d9081eb9"


def test_vendor_readme_records_origin_commit_and_update_procedure():
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")

    assert "https://github.com/HKUDS/Vibe-Trading" in readme
    assert COMMIT in readme
    assert "MIT" in readme
    assert "How to update" in readme
    assert "VENDOR_COMMIT" in readme


def test_license_and_notice_are_preserved():
    license_text = (VIBE / "LICENSE").read_text(encoding="utf-8")
    notice_text = (VIBE / "NOTICE").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License")
    assert "Vibe-Trading Contributors" in license_text
    assert "Microsoft Qlib" in notice_text
    assert "Apache 2.0" in notice_text
    # Attribution files referenced by upstream NOTICE that we keep on purpose.
    assert (VIBE / "agent/src/factors/zoo/qlib158/NOTICE").is_file()
    assert (VIBE / "frontend/public/fonts/LICENSE").is_file()
    assert (VIBE / "agent/src/shadow_account/assets/OFL.txt").is_file()


def test_vendor_commit_pin_is_consistent():
    from app.adapter import VENDOR_COMMIT

    third_party = (BASE.parent / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    verification = (BASE.parent / "docs" / "ENGINE_VERIFICATION.md").read_text(encoding="utf-8")

    assert VENDOR_COMMIT == COMMIT
    assert COMMIT in third_party
    assert COMMIT in verification


def test_vendor_tree_has_no_nested_git_and_caches_are_ignored():
    assert not (VIBE / ".git").exists()

    # Importing the vendor engine creates __pycache__ at runtime; the repo must
    # ignore those instead of committing them.
    gitignore = (BASE.parent / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in gitignore
    assert ".ruff_cache/" in gitignore
    assert "*.pyc" in gitignore

    tracked_caches = [
        line
        for line in _git_tracked_vendor_files()
        if "__pycache__" in line or line.endswith(".pyc") or ".ruff_cache" in line
    ]
    assert tracked_caches == []


def _git_tracked_vendor_files() -> list[str]:
    """Paths tracked under backend/vendor (empty if git is unavailable in CI)."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files", "backend/vendor"],
            cwd=BASE.parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return out.stdout.splitlines()


def test_vendor_tree_has_no_large_binaries():
    # The snapshot keeps source + attribution only; demo media and desktop/frontend
    # apps were pruned. Guard against accidentally re-adding them.
    large = [
        path.relative_to(VIBE).as_posix()
        for path in VIBE.rglob("*")
        if path.is_file() and path.stat().st_size > 25 * 1024 * 1024
    ]
    assert large == []


def test_tooling_excludes_vendor():
    pyproject = (BASE / "pyproject.toml").read_text(encoding="utf-8")
    pytest_ini = (BASE.parent / "pytest.ini").read_text(encoding="utf-8")
    dockerignore = (BASE / ".dockerignore").read_text(encoding="utf-8")
    dockerfile = (BASE / "Dockerfile").read_text(encoding="utf-8")

    assert '"vendor"' in pyproject or "'vendor'" in pyproject
    assert "norecursedirs = backend/vendor" in pytest_ini
    assert "COPY vendor ./vendor" in dockerfile
    assert "__pycache__/" in dockerignore
