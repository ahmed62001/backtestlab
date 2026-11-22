# Vendored third-party code

This directory contains a pinned, unmodified snapshot of the upstream
**Vibe-Trading** backtesting engine. It is used in-process as the real
backtest engine; it is not installed with `pip` and is not a git submodule.

## Origin

| Field | Value |
|---|---|
| Upstream | https://github.com/HKUDS/Vibe-Trading |
| Pinned commit | `c546e877274e7d36056c042808e1a875d9081eb9` |
| Ref / version | `main` (shallow clone, 2026-10-18). Upstream publishes no semver tag for this commit. |
| License | MIT — see [`Vibe-Trading/LICENSE`](Vibe-Trading/LICENSE) |
| Attribution | [`Vibe-Trading/NOTICE`](Vibe-Trading/NOTICE) (includes Microsoft Qlib factor definitions under Apache-2.0 and the factor-formula sources) |
| Vendored on | 2026-10-18 |
| Runtime pin | `backend/app/adapter.py::VENDOR_COMMIT` |

`VIBE_TRADING_VERSION` is the upstream license text copied at vendoring time;
the authoritative pin is the commit above, repeated in
`backend/app/adapter.py`, `docs/ENGINE_VERIFICATION.md` and
`THIRD_PARTY_NOTICES.md`.

## How it is used

- `backend/app/adapter.py::load_vendor_engine()` inserts
  `vendor/Vibe-Trading/agent` into `sys.path` lazily and imports
  `backtest.engines.global_equity.GlobalEquityEngine`.
- `backend/app/data_providers/vendor_shim.py` reuses the upstream data loaders
  under `agent/backtest/loaders/` through a thin adapter.
- Missing/broken vendor code surfaces as a per-request `503 ENGINE_UNAVAILABLE`
  (`VendorUnavailableError`); it never falls back silently to the synthetic
  engine. See `docs/ENGINE_VERIFICATION.md`.

No file in `Vibe-Trading/` is edited by BacktestLab. Changes are limited to
removing non-runtime content from the snapshot (see below), never modifying
vendored source.

## What is kept and what is pruned

Kept: upstream `LICENSE`, `NOTICE`, `README.md`, `CHANGELOG.md`, contribution
and security docs, dependency manifests/pins, and the complete Python source of
the engine (`agent/backtest/` plus `agent/src/`, `agent/cli/`, etc.).

Pruned from this snapshot (not needed by BacktestLab, and large binaries):

| Path | Reason |
|---|---|
| `agent/tests/` | upstream test suite; BacktestLab has its own tests |
| `assets/`, `wiki/` | demo videos/screenshots and documentation site |
| `frontend/`, `desktop/`, `pixel-office/`, `zimaos/` | upstream standalone apps |
| `.github/`, `.devcontainer/`, `tools/`, `scripts/` | upstream CI/dev tooling |
| `agent/src/shadow_account/assets/VibeCJK-Regular.ttf` | 20 MB CJK font used only by upstream PDF reports (license files kept) |
| translated `README_*.md`, `Dockerfile`, `docker-compose.yml` | packaging/docs for the upstream standalone app |

Removed size: ~157 MB of the original ~176 MB snapshot (including caches).
The retained tree is ~19 MB. Cache directories (`__pycache__/`, `.ruff_cache/`,
`*.pyc`) are never committed and are also excluded by `.gitignore`.

## How to update

1. Clone the new upstream commit outside the repo:

   ```bash
   git clone --depth 1 https://github.com/HKUDS/Vibe-Trading /tmp/vibe-trading
   cd /tmp/vibe-trading && git rev-parse HEAD
   ```

2. Copy the retained layout (adjust the commit if upstream moved files):

   ```bash
   cd /tmp/vibe-trading
   rsync -a \
     --exclude '__pycache__/' --exclude '.ruff_cache/' --exclude '*.pyc' \
     --exclude 'agent/tests/' --exclude 'assets/' --exclude 'wiki/' \
     --exclude 'frontend/' --exclude 'desktop/' --exclude 'pixel-office/' \
     --exclude 'zimaos/' --exclude '.github/' --exclude '.devcontainer/' \
     --exclude 'tools/' --exclude 'scripts/' \
     --exclude 'README_*.md' \
     ./ <repo-root>/backend/vendor/Vibe-Trading/
   ```

3. Restore the small attribution files if the rsync exclusions dropped them:

   ```bash
   mkdir -p backend/vendor/Vibe-Trading/frontend/public/fonts
   # copy frontend/public/fonts/LICENSE and agent/src/shadow_account/assets/{OFL.txt,README.md}
   ```

4. Update the commit in `backend/app/adapter.py::VENDOR_COMMIT`,
   `docs/ENGINE_VERIFICATION.md`, `THIRD_PARTY_NOTICES.md` and this README.

5. Re-run the gates:

   ```bash
   cd backend
   python -m pytest tests/test_phase1_runtime.py tests/test_vendor_hygiene.py -q
   python -m pytest tests/ -q --cov=app --cov-fail-under=70
   ```

## Tooling scope

- **Lint:** excluded via `[tool.ruff] extend-exclude = ["vendor", ...]`.
- **Types:** `mypy` only targets `app/data_providers` + `app/data_store`, and
  `[tool.mypy] exclude = ["vendor/"]`.
- **Tests:** root `pytest.ini` sets `norecursedirs = backend/vendor`; coverage
  is `--cov=app`, so vendored code is never counted.
- **Docker:** `backend/Dockerfile` copies only this (pruned) directory, so the
  image does not carry upstream demo media, frontend, desktop apps or tests.
- **Git:** files are committed as regular files, not a gitlink/submodule, so a
  fresh clone contains a runnable engine. `backend/vendor/Vibe-Trading/.git`
  must not exist.
