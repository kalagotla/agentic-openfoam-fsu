#!/usr/bin/env bash
#
# Run a step-by-step plan on the local model and report the result.
#
#   scripts/local-worker.sh <plan.md> [max-nudges]
#
# The plan is a list of exact tool calls (see docs/local-plan-format.md),
# usually written by a frontier model from the scenario and the corpus
# entry. Kilo's `cfd-local-plan` agent executes it on `ollama/cfd-local`.
# A local model sometimes ends its turn early; the script then says
# "continue" (up to max-nudges, default 6) until the report is finalized.
# It prints the verdict banner and the narrated steps, so the caller (a
# person or a frontier agent) can judge the run.
#
set -uo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
PLAN=${1:?usage: $0 <plan.md> [max-nudges]}
MAX=${2:-6}
[[ -f $PLAN ]] || { echo "No such plan: $PLAN" >&2; exit 2; }
command -v kilo >/dev/null || { echo "kilo is not installed (./setup.sh)" >&2; exit 2; }

# The case the plan works on: the first cases/work/<name> it mentions.
CASE=$(grep -o 'cases/work/[A-Za-z0-9._-]*' "$PLAN" | head -1)
[[ -n $CASE ]] || { echo "The plan names no cases/work/<name> directory." >&2; exit 2; }
LOG=$(mktemp -t local-worker.XXXX.jsonl)
finished() { grep -q 'BEGIN SUMMARY' "$CASE/REPORT.md" 2>/dev/null; }

t0=$(date +%s)
kilo run --agent cfd-local-plan --auto --format json "$(cat "$PLAN")" >"$LOG" 2>&1
sid=$(grep -o '"sessionID":"[^"]*"' "$LOG" | head -1 | cut -d'"' -f4)
n=0
while ! finished && (( n < MAX )) && [[ -n $sid ]]; do
    n=$((n + 1))
    kilo run --session "$sid" --agent cfd-local-plan --auto --format json \
        "Continue with the next numbered step of the plan." >>"$LOG" 2>&1
done

echo "local worker: $CASE, $(( $(date +%s) - t0 )) s, $n nudge(s), log $LOG"
if finished; then
    sed -n '/BEGIN SUMMARY/,/END SUMMARY/p' "$CASE/REPORT.md" | grep -v SUMMARY
else
    echo "Not finished: no verdict in $CASE/REPORT.md."
fi
echo "Steps:"
grep '^## \[' "$CASE/REPORT.md" 2>/dev/null | sed -E 's/^## \[[0-9:]+\] /  /'
python3 - "$LOG" <<'PY'
import json, sys
fails = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line.startswith("{"):
        continue
    part = json.loads(line).get("part", {})
    if part.get("type") == "tool":
        st = part.get("state", {})
        out = str(st.get("output", ""))
        if st.get("status") != "completed" or '"success":false' in out.replace(" ", ""):
            fails.append(f"{part.get('tool')}: {(str(st.get('error') or '') or out)[:160]}")
print(f"Failed tool calls: {len(fails)}")
for f in fails[-5:]:
    print("  " + f)
PY
finished
