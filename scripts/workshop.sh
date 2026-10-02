#!/usr/bin/env bash
#
# Helpers for the two-step persistent-knowledge demo (workshop/README.md).
#
#   ./scripts/workshop.sh status     what the corpus and work dirs hold now
#   ./scripts/workshop.sh promote    review + promote the draft corpus entry (Step 1 -> Step 2)
#   ./scripts/workshop.sh demote     turn the entry back into a draft (show a run without it)
#   ./scripts/workshop.sh reset      clear the work cases, keep the corpus (re-run Step 2)
#   ./scripts/workshop.sh reset-all  also forget the earned entry (start again at Step 1)
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

ENTRY=corpus/incompressible/icoFoam/cavity/cavity.md
DRAFT=corpus/incompressible/icoFoam/cavity/cavity.draft.md

bold() { printf '\033[1m%s\033[0m\n' "$*"; }

status() {
    bold "Corpus (what the consultant knows)"
    local entries
    entries=$(find corpus -name '*.md' -not -name README.md -not -name '*.draft.md' -not -path 'corpus/references/*' | sort)
    if [[ -n $entries ]]; then sed 's/^/  entry: /' <<<"$entries"; else echo "  (no entries — the next run starts from scratch)"; fi
    find corpus -name '*.draft.md' | sed 's/^/  draft awaiting review: /'
    bold "Work cases"
    local c
    for c in cases/work/*/; do
        [[ -d $c ]] || continue
        local verdict
        verdict=$(grep -m1 -oE 'PASS|FAIL|REVIEW|INCOMPLETE' "$c/REPORT.md" 2>/dev/null || true)
        printf '  %-32s %s\n' "$c" "${verdict:-(no verdict yet)}"
    done
    [[ -d cases/work ]] && compgen -G 'cases/work/*/' >/dev/null || echo "  (none)"
    bold "Local model"
    echo "  $("$REPO_DIR/scripts/local-model.sh" --show | head -1)"
}

promote() {
    if [[ -f $ENTRY && ! -f $DRAFT ]]; then
        echo "Already promoted: $ENTRY"; return
    fi
    if [[ ! -f $DRAFT ]]; then
        echo "No draft at $DRAFT."
        echo "Step 1 writes it at the end of the lid-cavity run (end_of_run.draft_corpus: true)."
        echo "Other drafts present:"; find corpus -name '*.draft.md' | sed 's/^/  /'
        exit 1
    fi
    bold "Draft entry — review it before it becomes the consultant's knowledge:"
    echo
    ${PAGER:-less} "$DRAFT" 2>/dev/null || cat "$DRAFT"
    echo
    grep -n '<fill in>' "$DRAFT" | sed 's/^/  unfilled: line /' || true
    read -r -p "Promote $DRAFT -> $ENTRY ? [y/N] " ans
    if [[ $ans == [yY]* ]]; then
        mv "$DRAFT" "$ENTRY"
        echo "Promoted. The next run that templates on icoFoam/cavity will cite it."
    else
        echo "Left as a draft. Edit it, then run this again."
    fi
}

reset_work() {
    rm -rf cases/work/lid-cavity cases/work/lid-cavity-re1000
    # archive_case output from Step 1 (end_of_run.archive_case: true).
    rm -rf cases/examples/lid-cavity
    echo "Cleared cases/work/lid-cavity*, cases/examples/lid-cavity."
}

demote() {
    # Back to a draft: the consultant stops returning it, the text is kept.
    # Use it to show a run without the knowledge, then promote again.
    if [[ ! -f $ENTRY ]]; then echo "No promoted entry at $ENTRY."; exit 1; fi
    mv "$ENTRY" "$DRAFT"
    echo "Demoted to $DRAFT: runs no longer see it. './scripts/workshop.sh promote' restores it."
}

case "${1:-status}" in
    status)    status ;;
    promote)   promote ;;
    demote)    demote ;;
    reset)     reset_work ;;
    reset-all) reset_work; rm -f "$ENTRY" "$DRAFT"; echo "Removed $ENTRY — the corpus is empty again (Step 1)." ;;
    -h|--help) sed -n '2,9p' "$0" ;;
    *) echo "unknown command: $1 (see --help)" >&2; exit 2 ;;
esac
