#!/usr/bin/env bash
# Evidence runner: executes a command, stores raw+redacted log, appends to a JSONL ledger.
# Usage: run_evid.sh <phase-dir> <slug> <cwd> <cmd...>
set -uo pipefail
PHASE_DIR="$1"; shift
SLUG="$1"; shift
CWD="$1"; shift

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EVID="${EVID:-$REPO_ROOT/final-release-evidence}"
OUTDIR="$EVID/$PHASE_DIR"
mkdir -p "$OUTDIR/logs" "$OUTDIR/json"
LOG_REL="$PHASE_DIR/logs/${SLUG}.log"
LOG="$EVID/$LOG_REL"
LEDGER="$EVID/$PHASE_DIR/json/commands.jsonl"

START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
( cd "$CWD" && "$@" ) >"$LOG.raw" 2>&1
CODE=$?
END=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Redaction pass: mask credentials/tokens/emails (non-test).
python3 - "$LOG.raw" "$LOG" <<'PY'
import re,sys
src,dst=sys.argv[1],sys.argv[2]
s=open(src,'r',errors='replace').read()
s=re.sub(r'(?i)(authorization:\s*(bearer|token)\s+)\S+', r'\1<REDACTED>', s)
s=re.sub(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b','<REDACTED_JWT>',s)
s=re.sub(r'(?i)\b(api[_-]?key|apikey|secret|password|passwd|token)\b(\s*[=:]\s*)["\']?[^\s"\',;]{3,}', r'\1\2<REDACTED>', s)
s=re.sub(r'(?i)(postgres(?:ql)?://[^:\s]+:)[^@\s]+@', r'\1<REDACTED>@', s)
s=re.sub(r'(?i)(set-cookie:\s*)[^\n]+', r'\1<REDACTED>', s)
s=re.sub(r'\b[A-Za-z0-9._%+-]+@(?!example\.test)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b','<REDACTED_EMAIL>',s)
open(dst,'w').write(s)
PY
rm -f "$LOG.raw"

CMDSTR=$(printf '%q ' "$@")
python3 - "$LEDGER" "$CMDSTR" "$CWD" "$CODE" "$START" "$END" "$LOG_REL" <<'PY'
import json,sys,os
path,cmd,cwd,code,start,end,log=sys.argv[1:8]
rec={"cmd":cmd.strip(),"cwd":cwd,"exit_code":int(code),"started_at":start,"finished_at":end,"log":log}
with open(path,'a') as f: f.write(json.dumps(rec)+"\n")
PY
echo "exit=$CODE log=$LOG"
exit $CODE
