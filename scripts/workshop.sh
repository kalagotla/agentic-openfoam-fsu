#!/usr/bin/env bash
#
# Helpers for the two-step persistent-knowledge demo (workshop/README.md).
#
#   ./scripts/workshop.sh status     what the corpus and work dirs hold now
#   ./scripts/workshop.sh promote    review + promote the draft corpus entry (Step 1 -> Step 2)
#   ./scripts/workshop.sh demote     turn the entry back into a draft (show a run without it)
#   ./scripts/workshop.sh fork <scenario> <tag> [--auto]
#                                    copy a scenario under a new name (its own case folder),
#                                    so two agents can run it side by side; --auto = no pauses
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
    rm -rf cases/work/lid-cavity cases/work/lid-cavity-re1000 cases/work/lid-cavity*--*
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

fork() {
    local base=${1:?usage: workshop.sh fork <scenario> <tag> [--auto]} tag=${2:?usage: workshop.sh fork <scenario> <tag> [--auto]}
    base=${base%.yaml}; base=${base##*/}
    local src=cases/scenarios/$base.yaml dst=cases/scenarios/$base--$tag.yaml
    [[ -f $src ]] || { echo "No scenario $src"; exit 1; }
    sed -e "s/^name: .*/name: $base--$tag/" "$src" >"$dst"
    if [[ ${3:-} == --auto ]]; then
        if grep -q '^automation_level:' "$dst"; then
            sed -i 's/^automation_level: .*/automation_level: 5/' "$dst"
        else
            sed -i "/^name: /a automation_level: 5" "$dst"
        fi
    fi
    echo "Wrote $dst (case folder cases/work/$base--$tag$([[ ${3:-} == --auto ]] && echo ', runs without pauses'))."
    echo "Run it with: Set up and run $dst"
}

case "${1:-status}" in
    status)    status ;;
    promote)   promote ;;
    demote)    demote ;;
    fork)      shift; fork "$@" ;;
    reset)     reset_work ;;
    reset-all) reset_work; rm -f "$ENTRY" "$DRAFT" cases/scenarios/*--*.yaml; echo "Removed $ENTRY — the corpus is empty again (Step 1)." ;;
    -h|--help) sed -n '2,9p' "$0" ;;
    *) echo "unknown command: $1 (see --help)" >&2; exit 2 ;;
esac
