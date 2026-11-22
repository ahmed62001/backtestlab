#!/usr/bin/env bash
#
# start.sh — run & review the whole BacktestLab app with one command.
#
#   ./start.sh                      # Vite dev server, reachable on the LAN
#   ./start.sh --build              # production preview (vite build + preview)
#   ./start.sh --skip-verify        # skip `npm run verify`
#   ./start.sh --port 6173          # custom port
#
set -euo pipefail

# ── project root = directory of this script ────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# App name (single source of truth: src/routes/manifest.ts + src/lib/constants.ts).
APP_NAME="BacktestLab"

# Returns 0 (true) if $PORT is free to bind, 1 otherwise.
port_free() {
  node -e "
    const net = require('net');
    const s = net.createConnection($PORT, () => {
      s.destroy();
      process.exit(1); // connection succeeded -> something is already listening
    });
    s.on('error', () => process.exit(0)); // connection refused -> port is free
  " 2>/dev/null
}

PORT="${PORT:-5173}"
SKIP_VERIFY=false
BUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-verify) SKIP_VERIFY=true; shift ;;
    --build)       BUILD=true;       shift ;;
    --port)        PORT="${2:-5173}"; shift 2 ;;
    *)             shift ;;
  esac
done

# The route-tool uses this as the base URL for "full URLs" in the table.
export DEV_URL="http://localhost:${PORT}"

# ── 1. Node >= 18 + npm present ─────────────────────────────────────────────
if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: Node.js is not installed or not on PATH." >&2
  exit 1
fi
NODE_MAJOR="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
if (( NODE_MAJOR < 18 )); then
  echo "ERROR: Node.js >= 18 is required (found v$(node -v))." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is not installed or not on PATH." >&2
  exit 1
fi
npm --version >/dev/null 2>&1 || {
  echo "ERROR: npm is not installed or is broken." >&2
  exit 1
}

# ── 2. npm install if node_modules is missing ───────────────────────────────
if [[ ! -d node_modules ]]; then
  echo "> node_modules missing — running npm install ..."
  npm install
fi

# ── 3. .env from .env.example if missing ────────────────────────────────────
if [[ ! -f .env ]]; then
  echo "> .env missing — creating from .env.example (VITE_USE_MOCK=true) ..."
  cp .env.example .env
  # Guarantee the mock flag is on (already in .env.example — guard for safety).
  if ! grep -q '^VITE_USE_MOCK=' .env 2>/dev/null; then
    echo 'VITE_USE_MOCK=true' >> .env
  fi
fi

# ── 4. npm run verify ───────────────────────────────────────────────────────
if [[ "$SKIP_VERIFY" == true ]]; then
  echo "> Skipping `npm run verify` (--skip-verify)."
else
  echo "> Running `npm run verify` ..."
  if ! npm run verify; then
    echo "ERROR: npm run verify failed — see errors above." >&2
    exit 1
  fi
fi

# ── 5. Route map + demo credentials + LAN URL (before starting) ─────────────
echo
echo "════════ ${APP_NAME} route map ════════"
node scripts/print-routes.mjs
echo

# ── 6. Start (dev or production preview) ────────────────────────────────────
if [[ "$BUILD" == true ]]; then
  echo "════════ Building for production preview ════════"
  npm run build
  echo
  echo "Production preview is ready at http://localhost:${PORT}"
  echo "Mobile: http://$(node scripts/print-routes.mjs --lan-ip):${PORT}"
  echo
  npm run preview -- --host --port "${PORT}"
else
  echo "════════ Starting Vite dev server (--host) ════════"
  echo
  echo "Open:   http://localhost:${PORT}"
  echo "Phone:  http://$(node scripts/print-routes.mjs --lan-ip):${PORT}"
  echo
  echo "Manual test hints:"
  echo "  • Switch language: tap the EN/عربي button in the header."
  echo "  • Switch theme:   tap the sun/moon button in the header."
  echo "  • Resize to 360px: open the app in a 360px-wide viewport."
  echo "  • Open /404:      navigate to /404 (or any unknown path)."
  echo
  if ! port_free; then
    echo "ERROR: Port $PORT is already in use." >&2
    echo "       Stop the process using it, or pass another port (e.g. --port 6173)." >&2
    exit 1
  fi
  if [[ "${1:-}" == "backend" ]]; then
    cd backend && pip install -q -r requirements.txt && python -m uvicorn app.main:app --host --port 8000
  elif [[ "${1:-}" == "test" ]]; then
    python -m pytest backend/tests/ -q && npm run verify --skip-verify 2>/dev/null || npm run verify
  else
    npm run dev -- --host --port "${PORT}"
  fi
fi
