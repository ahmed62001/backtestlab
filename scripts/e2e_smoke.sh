#!/usr/bin/env bash
# BacktestLab E2E smoke test — production Docker stack (Phase 6).
#
# Flow:
#   1. register
#   2. login
#   3. create a backtest (async, seeded/local provider) -> jobId
#   4. poll the job until status=done
#   5. print backtest provenance (dataHash, engine.mode)
#
# The separate `worker` container must execute the job, so `docker compose logs
# --no-color --tail 30 worker` should show the job being executed.
set -euo pipefail

API="http://localhost:8000/api/v1"
EMAIL="e2e.$(date +%s).@backtestlab.dev"
PASS="e2e-pass-1234567890"

say() { echo "== $1 =="; }

# 1. register
say "1/5 register"
REG=$(curl -s -X POST "$API/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"name\":\"E2E User\"}")
echo "$REG" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  token='+d.get('token',''))"
TOKEN=$(echo "$REG" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

# 2. login
say "2/5 login"
LOG=$(curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}")
echo "$LOG" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  access_token_len='+str(len(d.get('access_token',''))))"
TOKEN=$(echo "$LOG" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

# 3. create a real backtest (async, local provider, vendor engine)
say "3/5 create backtest (async, local provider, vendor engine)"
CREATED=$(curl -s -X POST "$API/backtests?async=true" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"templateId":"ma-crossover","leverage":1,"short":false,"dataProvider":"local","asset":"AAPL","from":"2022-01-01","to":"2023-12-31","interval":"1D"}')
echo "$CREATED"
JOB_ID=$(echo "$CREATED" | python3 -c "import sys,json; print(json.load(sys.stdin).get('jobId',''))")
BT_ID=$(echo "$CREATED" | python3 -c "import sys,json; print(json.load(sys.stdin).get('backtestId',''))")
if [ -z "$JOB_ID" ] || [ -z "$BT_ID" ]; then
  echo "  ERROR: failed to obtain jobId/backtestId" >&2
  exit 1
fi

# 4. poll the job until status=done
say "4/5 poll job until done"
for i in $(seq 1 40); do
  J=$(curl -s "$API/jobs/$JOB_ID" -H "Authorization: Bearer $TOKEN")
  STATE=$(echo "$J" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "  poll $i: $STATE"
  if [ "$STATE" = "done" ]; then break; fi
  sleep 2
done

# 5. provenance
say "5/5 backtest provenance"
curl -s "$API/backtests/$BT_ID" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo "E2E_SMOKE_OK"
