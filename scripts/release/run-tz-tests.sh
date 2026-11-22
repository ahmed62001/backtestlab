#!/usr/bin/env bash
# Run the chart data-transform tests under several host timezones.
# Daily bars are formatted in UTC, so the assertions must be identical in all.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EVID=${EVID:-$REPO/final-release-evidence}
PHASE=${1:-phase-1}
OUT="$EVID/$PHASE/logs"
mkdir -p "$OUT"
rc=0
for tz in UTC Africa/Cairo America/New_York; do
  TZ="$tz" npx vitest run src/lib/chartData.test.ts --reporter=verbose > "$OUT/tz-${tz//\//_}.log" 2>&1
  code=$?
  echo "TZ=$tz exit=$code $(grep -E 'Tests +[0-9]+ (passed|failed)' "$OUT/tz-${tz//\//_}.log" | tail -1)"
  [ $code -ne 0 ] && rc=$code
done
exit $rc
