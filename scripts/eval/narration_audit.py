"""Does the narration describe the case that actually ran?

This is the measurement behind `docs/evaluation-plan.md` §3.3 — the axis
no competing system can even be scored on, because none of them produce a
narration to check. A `REPORT.md` that does not describe the case it
accompanies is worse than no report at all: it invites a researcher to
sign off on something they did not read.

Two sides, compared as sets.

**Recall** — every load-bearing change the agent made to its structural
template should have a decision entry explaining it. Changes with no entry
are the *unnarrated-change rate*: edits made silently. This needs the
template, so it only runs when the tutorial the case was built from is
known and readable.

**Precision** — every concrete claim the narration makes about the case
should be true of the case files. Claims that are false are the
*contradiction rate*: narration that lies. That is a defect report, not a
statistic, and the target is zero.

Claim extraction is deliberately high-precision and low-recall: it only
picks up claims concrete enough to resolve against a dictionary key, a
known OpenFOAM identifier, or a cell count. Qualitative rationale escapes
it entirely. The auditor therefore reports its own coverage — how many
decisions produced any checkable claim at all — so the denominator behind
the precision number is visible rather than implied.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foam_dict import flatten, read_case_settings
from report_parse import Report, parse_report

# Keys whose value legitimately differs from the template for reasons that
# are not decisions: paths, the case's own identity, and write bookkeeping
# the solver controls.
IGNORED_KEY_PATTERNS = (
    re.compile(r"^FoamFile\."),
    re.compile(r"\blocation\b"),
    re.compile(r"^functions\..*\.file"),
)

# Identifiers a narration might name that must then appear in the case.
# Kept to unambiguous OpenFOAM vocabulary — a word like "linear" is too
# common in prose to treat as a claim about fvSchemes.
KNOWN_IDENTIFIERS = frozenset(
    {
        # solvers
        "simpleFoam", "icoFoam", "pimpleFoam", "pisoFoam", "rhoCentralFoam",
        "sonicFoam", "buoyantSimpleFoam", "interFoam", "potentialFoam",
        # turbulence
        "kOmegaSST", "kEpsilon", "kOmega", "SpalartAllmaras", "realizableKE",
        "laminar", "RAS", "LES",
        # schemes
        "linearUpwind", "limitedLinear", "upwind", "vanLeer", "QUICK",
        "cellLimited", "leastSquares", "steadyState", "backward",
        "CrankNicolson", "Euler", "linearUpwindV", "LUST",
        # BC types
        "fixedValue", "zeroGradient", "noSlip", "empty", "symmetry",
        "symmetryPlane", "cyclic", "wedge", "slip", "inletOutlet",
        "freestream", "freestreamPressure", "totalPressure", "calculated",
        "movingWallVelocity", "pressureInletOutletVelocity", "nutkWallFunction",
        "nutUWallFunction", "kqRWallFunction", "omegaWallFunction",
        "epsilonWallFunction",
        # linear solvers / preconditioners
        "GAMG", "PBiCGStab", "PCG", "smoothSolver", "DIC", "DILU",
        "GaussSeidel", "symGaussSeidel",
    }
)

# `endTime 5000`, `endTime = 5000`, `endTime of 5000`, `endTime to 5000`
_KEY_VALUE_RE = re.compile(
    r"\b(?P<key>[A-Za-z][A-Za-z0-9_]{2,})\b\s*(?:=|:|\bto\b|\bof\b)?\s*"
    r"(?P<value>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\b"
)
# Mesh resolution as a narration writes it: `80x80`, `128x128x64`, and the
# same with a multiplication sign (spelled as an escape to keep the source
# plain ASCII).
# The third dimension may be a single cell: a 2-D case is meshed one cell
# deep, and "80x80x1" is how a narration says so.
# The second dimension may be a single digit: a quasi-1-D duct is meshed a
# couple of cells across, and "240x2x1" is how a narration says so. The
# first is held at two digits or more so that ratios and factors in prose
# ("a 2x refinement") are not read as a mesh.
_CELL_COUNT_RE = re.compile(
    "\\b(\\d{2,4})\\s*[x\u00d7]\\s*(\\d{1,4})(?:\\s*[x\u00d7]\\s*(\\d{1,4}))?\\b"
)
_CHECKMESH_CELLS_RE = re.compile(r"\bcells:\s*(\d+)")


@dataclass
class Claim:
    """One checkable assertion the narration makes about the case."""

    kind: str            # dict_value | identifier | cell_count
    text: str            # what the narration said
    target: str          # key, identifier, or dimensions
    expected: str
    verdict: str         # true | false | unverifiable
    found: str = ""
    entry_title: str = ""


# ---------------------------------------------------------------------------
# Recall: changes vs narrated decisions
# ---------------------------------------------------------------------------


def _ignored(key: str) -> bool:
    return any(p.search(key) for p in IGNORED_KEY_PATTERNS)


def changeset(
    case: Path, template: Path | Sequence[Path]
) -> list[dict[str, str]]:
    """Settings that differ between the authored case and its template.

    A template may be several directories. Tutorials that ship more than
    one setup split a case into ``setups.orig/common`` plus a per-setup
    directory, and neither half alone is the case the agent copied.
    """
    dirs = [template] if isinstance(template, Path) else list(template)
    case_flat = flatten(read_case_settings(case))
    tmpl_flat: dict[tuple[str, str], str] = {}
    for d in dirs:
        tmpl_flat.update(flatten(read_case_settings(d)))

    # Compare on the dictionary's own name rather than its full path, since
    # a case may place a dict in a different subdirectory than the tutorial.
    def by_name(flat: dict[tuple[str, str], str]) -> dict[tuple[str, str], str]:
        return {(Path(f).name, k): v for (f, k), v in flat.items() if not _ignored(k)}

    case_named, tmpl_named = by_name(case_flat), by_name(tmpl_flat)
    changes: list[dict[str, str]] = []
    for (dict_name, key), value in sorted(case_named.items()):
        old = tmpl_named.get((dict_name, key))
        if old is None:
            changes.append(
                {"dict": dict_name, "key": key, "change": "added", "to": value}
            )
        elif old != value:
            changes.append(
                {
                    "dict": dict_name,
                    "key": key,
                    "change": "modified",
                    "from": old,
                    "to": value,
                }
            )
    for (dict_name, key) in sorted(tmpl_named):
        if (dict_name, key) not in case_named:
            changes.append(
                {
                    "dict": dict_name,
                    "key": key,
                    "change": "removed",
                    "from": tmpl_named[(dict_name, key)],
                }
            )
    return changes


def _narration_haystack(report: Report) -> str:
    parts: list[str] = []
    for e in report.entries:
        parts.extend([e.title, e.decision, e.why, e.alternatives, e.when_it_breaks])
        for rows in e.tables.values():
            for row in rows:
                parts.extend(str(v) for v in row.values())
        parts.append(e.details)
    return " ".join(parts).lower()


def group_changes(changes: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse a change to one nested block into a single unit.

    Adding a sampling functionObject writes a dozen keys under
    ``functions.<name>``, and a boundary condition writes several under
    ``boundaryField.<patch>``. Those are one decision each. Counting every
    sub-key separately would make a well-narrated case look mostly silent,
    which says more about the counting than the narration.
    """
    grouped: dict[tuple[str, str], dict[str, str]] = {}
    out: list[dict[str, str]] = []
    for ch in changes:
        parts = ch["key"].split(".")
        if len(parts) >= 3 and parts[0] in ("functions", "boundaryField", "solvers"):
            unit = ".".join(parts[:2])
            marker = (ch["dict"], unit)
            if marker in grouped:
                grouped[marker]["n_keys"] = str(int(grouped[marker]["n_keys"]) + 1)
                continue
            entry = {**ch, "key": unit, "n_keys": "1", "grouped": "true"}
            grouped[marker] = entry
            out.append(entry)
        else:
            out.append(ch)
    return out


def narration_recall(
    report: Report, changes: list[dict[str, str]]
) -> dict[str, Any]:
    """How much of what changed was explained.

    A change counts as narrated when the narration mentions its key, or
    mentions both its dictionary and its new value. Lenient by design: the
    question is whether the reader was told, not whether particular words
    were used.
    """
    hay = _narration_haystack(report)
    # Recall asks whether the agent explained what it *did*. A template
    # setting absent from the case is usually a tutorial file it had no
    # reason to copy, not an edit it made silently, so removals are
    # reported apart from the denominator rather than counted in it.
    removals = [c for c in changes if c["change"] == "removed"]
    changes = group_changes([c for c in changes if c["change"] != "removed"])
    narrated: list[dict[str, str]] = []
    silent: list[dict[str, str]] = []
    for ch in changes:
        key_tokens = [t for t in re.split(r"[.\W]+", ch["key"]) if len(t) > 2]
        mentioned = any(t.lower() in hay for t in key_tokens)
        if not mentioned:
            value = str(ch.get("to", "")).lower()
            # A distinctive value is evidence on its own: "swapped to
            # simpleFoam" narrates the application change without ever
            # writing the word "application".
            distinctive = len(value) > 3 and not value.replace(".", "").isdigit()
            mentioned = bool(value) and value in hay and (
                distinctive or ch["dict"].lower() in hay
            )
        (narrated if mentioned else silent).append(ch)
    total = len(changes)
    return {
        "n_changes": total,
        "n_template_settings_not_carried_over": len(removals),
        "n_narrated": len(narrated),
        "narration_recall": (len(narrated) / total) if total else None,
        "unnarrated_change_rate": (len(silent) / total) if total else None,
        "unnarrated": silent[:40],
        "unnarrated_truncated": max(0, len(silent) - 40),
    }


# ---------------------------------------------------------------------------
# Precision: claims vs the case files
# ---------------------------------------------------------------------------


def _lookup(case_flat: dict[tuple[str, str], str], key: str) -> list[str]:
    """Every value in the case whose key ends with ``key``."""
    key_l = key.lower()
    return [
        v
        for (_f, k), v in case_flat.items()
        if k.lower() == key_l or k.lower().endswith("." + key_l)
    ]


_MACRO_RE = re.compile(r"^\s*\$|#(?:include|calc)")


def _is_macro(value: str) -> bool:
    """A value the dictionary defers rather than states."""
    return bool(_MACRO_RE.search(value))


def _numbers_match(expected: str, found: str) -> bool:
    try:
        target = float(expected)
    except ValueError:
        return False
    for tok in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", found):
        try:
            if abs(float(tok) - target) <= 1e-9 * max(1.0, abs(target)):
                return True
        except ValueError:
            continue
    return False


def _identifier_re(ident: str) -> re.Pattern[str]:
    """Match an identifier as a standalone word, not inside a hyphenated one.

    ``\bslip\b`` fires inside "no-slip", because a hyphen is a word
    boundary — which turned a correct narration into a contradiction on the
    first real run this was pointed at.
    """
    return re.compile(rf"(?<![-\w]){re.escape(ident)}(?![-\w])")


_REJECTION_BEFORE_RE = re.compile(
    r"(?:instead of|rather than|not|over|reject\w*|avoided|discarded|"
    # A departure names what the case moved away from: "simpleFoam
    # (scenario-specified, swapped from icoFoam per the corpus entry's
    # documented gotcha)" records the swap, and the whole point of the
    # sentence is that icoFoam is what the case no longer uses.
    r"swapped from|switched from|changed from|moved from|migrated from|"
    r"away from|in place of|replac\w+)\s+\w*\s*$",
    re.IGNORECASE,
)
# "slip walls were rejected", "the icoFoam default, was rejected for the
# steady solve" — rejection follows the name as often as it precedes it, and
# with arbitrary punctuation in between. Scanning the window for the verb is
# looser than parsing the clause, and it errs toward *not* recording a
# contradiction, which is the right direction: a false contradiction is a
# far more damaging error than a missed claim.
_REJECTION_AFTER_RE = re.compile(
    r"\b(?:reject\w*|discarded|avoided|ruled out|not used|inappropriate|"
    r"unsuitable|too diffusive|cannot\s+\w+|fails?\b|would\s+fail)\b",
    re.IGNORECASE,
)

# Hypothetical mood. "simpleFoam would solve the identical equations" and
# "a resolved kOmegaSST run is a natural next comparison" both name a
# solver the case does not use, and neither claims it does. Discussing what
# a different choice would have done is the alternatives reasoning the
# consultant schema asks for, so scoring it as a false claim would punish
# exactly the narration the design wants.
_HYPOTHETICAL_RE = re.compile(
    r"\b(?:would|could|might|should have|instead|alternative\w*|rather than|"
    r"e\.g\.|for example|next comparison|natural next|future|later run|"
    r"if we|had we|considered)\b",
    re.IGNORECASE,
)
_HYPOTHETICAL_WINDOW = 90
# Words that mark a mention as provenance — naming the template a case was
# built from, not a setting the case uses.
_PROVENANCE_WORDS = (
    "tutorial",
    "template",
    "templated",
    "based on",
    "borrowed",
    # Other ways a report names where something came from. "Geometry: unit
    # square from the icoFoam cavity blockMeshDict" is provenance in every
    # sense except the word it uses.
    "structural base",
    # "unit square from the icoFoam cavity blockMeshDict" names a source.
    # Before an identifier, "from the" marks where something came from far
    # more often than it asserts what the case uses.
    "from the",
    "adapted from",
    "taken from",
    "copied from",
    "derived from",
    "reused",
)
# Asymmetric on purpose. Provenance wording sits close to the name it
# qualifies — "copied from the icoFoam cavity tutorial", "templated on X" —
# so a wide symmetric window swallows live claims from neighbouring
# clauses, which is how a real assertion escaped scoring the first time.
_PROVENANCE_WINDOW_BEFORE = 45
_PROVENANCE_WINDOW_AFTER = 25


# Words that mark a mention as a description of how the solution *behaved*
# rather than a setting the case declares. "The bulk of the channel is
# running effectively laminar, not turbulent" diagnoses a failed run; it
# does not claim `simulationType laminar`. Reading it as one turns the
# report that diagnosed its own failure most precisely into the report that
# looks least honest.
_DESCRIPTIVE_BEFORE_RE = re.compile(
    r"\b(?:effectively|essentially|nominally|virtually|practically|"
    r"apparently|quasi|running|runs|ran|behaves?|behaving|behaved|"
    r"collapsing|collapsed|relaminaris\w*|toward|towards|spurious)\b"
    r"[\s,-]*$",
    re.IGNORECASE,
)
# A noun that turns the identifier into a description of the flow rather
# than a name for a model: "a laminar profile", "the laminar core".
_DESCRIPTIVE_AFTER_RE = re.compile(
    r"^[-\s]*(?:profile|regime|state|solution|core|region|sublayer|"
    r"fixed\s+point|behaviou?r|patch\w*|like\b)",
    re.IGNORECASE,
)
_DESCRIPTIVE_WINDOW = 40
# A number immediately followed by a dash and another digit is the low end
# of a range, not a value.
_RANGE_TAIL_RE = re.compile(r"^\s*[-\u2013]\s*\d")
# "both walls curved via spline edges (no symmetryPlane cut)" does not claim
# the case uses a symmetryPlane — it says the opposite. Kept tight so it
# cannot swallow a clause that merely happens to contain "no" earlier on.
_NEGATION_RE = re.compile(
    r"\b(?:no|not|without|never|avoided|avoids|omit(?:s|ted)?|dropped|"
    r"rather\s+than|instead\s+of)\b[\s\w,()-]{0,18}$",
    re.IGNORECASE,
)


def _is_negated(prose: str, start: int) -> bool:
    """Is the identifier named in order to say the case does *not* use it?"""
    return bool(_NEGATION_RE.search(prose[max(0, start - 60) : start]))


def _is_descriptive(prose: str, start: int, end: int) -> bool:
    """Is the identifier describing the flow, not naming a setting?"""
    before = prose[max(0, start - _DESCRIPTIVE_WINDOW) : start]
    after = prose[end : end + _DESCRIPTIVE_WINDOW]
    return bool(
        _DESCRIPTIVE_BEFORE_RE.search(before) or _DESCRIPTIVE_AFTER_RE.match(after)
    )


def _is_rejected(prose: str, ident: str) -> bool:
    for m in _identifier_re(ident).finditer(prose):
        before = prose[max(0, m.start() - 40) : m.start()]
        after = prose[m.end() : m.end() + 60]
        if _REJECTION_BEFORE_RE.search(before) or _REJECTION_AFTER_RE.search(after):
            return True
    return False


def _in_path_token(prose: str, position: int) -> bool:
    """True when the identifier sits inside a path-like token.

    ``incompressible/icoFoam/cavity`` names a tutorial or a corpus entry.
    That is provenance, not an assertion that the case runs icoFoam.
    """
    start = position
    while start > 0 and not prose[start - 1].isspace():
        start -= 1
    end = position
    while end < len(prose) and not prose[end].isspace():
        end += 1
    return "/" in prose[start:end]


def _shadowed_by_longer_identifier(ident: str, case_text: str) -> str | None:
    """A longer identifier in the case that contains this one.

    Prose says "second-order upwind" while fvSchemes says ``linearUpwind``.
    The word is doing double duty — a scheme name and a description of its
    character — so the claim is ambiguous, not false.
    """
    for other in KNOWN_IDENTIFIERS:
        if (
            other != ident
            and ident.lower() in other.lower()
            and _identifier_re(other).search(case_text)
        ):
            return other
    return None


def _is_hypothetical(prose: str, position: int) -> bool:
    """Is this mention in the conditional, rather than an assertion?"""
    window = prose[
        max(0, position - _HYPOTHETICAL_WINDOW) : position + _HYPOTHETICAL_WINDOW
    ]
    return bool(_HYPOTHETICAL_RE.search(window))


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+")


def _in_provenance_sentence(prose: str, position: int) -> bool:
    """Does the sentence carrying this claim describe the template?

    A value quoted from a tutorial sits in a sentence that says so, but not
    always within a few words of it: "that template uses the identical
    topology for the same physical case, just at its own domain scale
    (scale 0.333)" puts eighty characters between the two. Sentence scope
    fits how the provenance is actually written.

    Wider than the identifier guard, and deliberately so — the repo's rule
    is that a false contradiction costs more than a missed claim, because
    the first pushes an agent toward narrating less.
    """
    start = 0
    for m in _SENTENCE_SPLIT_RE.finditer(prose):
        if m.start() > position:
            break
        start = m.end()
    end = len(prose)
    for m in _SENTENCE_SPLIT_RE.finditer(prose, position):
        end = m.start()
        break
    sentence = prose[start:end].lower()
    return any(w in sentence for w in _PROVENANCE_WORDS)


def _is_provenance(prose: str, position: int) -> bool:
    window = prose[
        max(0, position - _PROVENANCE_WINDOW_BEFORE) : position
        + _PROVENANCE_WINDOW_AFTER
    ].lower()
    return any(w in window for w in _PROVENANCE_WORDS)


_STATED_TOTAL_RE = re.compile(
    r"^\s*\(?\s*([\d,]{3,})\s*(?:cells|cell)\b", re.IGNORECASE
)


def _check_stated_total(
    prose: str, match: re.Match[str], dims: list[str], entry_title: str
) -> Claim | None:
    """A narration that writes out its own cell total has to get it right.

    "240x2x1 (960 cells)" is the arithmetic slip this catches: the mesh is
    480 cells. The dimensions are checked against the case elsewhere; this
    checks the narration against itself, which needs no case files at all.
    """
    tail = prose[match.end() : match.end() + 40]
    m = _STATED_TOTAL_RE.match(tail)
    if not m:
        return None
    stated = int(m.group(1).replace(",", ""))
    product = 1
    for d in dims:
        product *= int(d)
    return Claim(
        kind="cell_total",
        text=f"{match.group(0)} ({stated} cells)",
        target="stated cell total",
        expected=str(product),
        verdict="true" if stated == product else "false",
        found=str(stated),
        entry_title=entry_title,
    )


def _check_cell_count(
    case: Path,
    case_flat: dict[tuple[str, str], str],
    text: str,
    dims: list[str],
    entry_title: str,
) -> Claim:
    """Verify a claimed mesh resolution against the mesh the case built.

    Two places can confirm it: the block specification in blockMeshDict,
    which is what the agent wrote, and the cell count checkMesh reported,
    which is what OpenFOAM built. Preferring the second where both exist
    would be stricter, but a graded or multi-block mesh legitimately has a
    total that is not the product of one block's divisions, so the block
    spec is checked first and the total only as a fallback.
    """
    blocks = " ".join(v for (_f, k), v in case_flat.items() if k == "blocks")
    if blocks:
        spec = f"({' '.join(dims)})"
        if spec in re.sub(r"\s+", " ", blocks):
            return Claim(
                kind="cell_count",
                text=text,
                target="blockMeshDict.blocks",
                expected=spec,
                verdict="true",
                found="matches the block spec",
                entry_title=entry_title,
            )

    log = case / "log.checkMesh"
    if log.is_file():
        m = _CHECKMESH_CELLS_RE.search(log.read_text(errors="replace"))
        if m:
            total = int(m.group(1))
            product = 1
            for d in dims:
                product *= int(d)
            if product == total:
                return Claim(
                    kind="cell_count",
                    text=text,
                    target="mesh cell count",
                    expected=str(product),
                    verdict="true",
                    found=str(total),
                    entry_title=entry_title,
                )
            return Claim(
                kind="cell_count",
                text=text,
                target="mesh cell count",
                expected=str(product),
                verdict="false",
                found=str(total),
                entry_title=entry_title,
            )

    return Claim(
        kind="cell_count",
        text=text,
        target="mesh resolution",
        expected="x".join(dims),
        verdict="unverifiable",
        found="no blockMeshDict blocks entry and no checkMesh log",
        entry_title=entry_title,
    )


# Phases whose entries describe the mesh. A report is a chronological log,
# so an earlier entry in one of these describes a mesh that no longer
# exists — the intermediate step of a refinement sweep or a reversal.
_MESH_PHASES = ("geometry", "mesh", "mesh_quality")


def superseded_titles(report: Report) -> set[str]:
    """Entries a later entry replaced, whose claims describe a past state.

    Two ways an entry is superseded: a later entry names it in `retry_of`,
    or it describes the mesh and a later mesh entry exists. Checking a
    superseded claim against the final case files scores a chronological
    log as if it were a description of the end state — which is how the
    cd-nozzle run, whose narration recorded every mesh it tried and why,
    came out as the least honest report in the matrix.
    """
    out = {e.retry_of for e in report.entries if e.retry_of}
    out.discard(None)
    mesh_entries = [e for e in report.entries if e.phase in _MESH_PHASES]
    out.update(e.title for e in mesh_entries[:-1])
    return {t for t in out if t}


def extract_claims(report: Report, case: Path) -> list[Claim]:
    """Pull checkable claims out of the narration and verify each one."""
    case_settings = read_case_settings(case)
    case_flat = flatten(case_settings)
    all_text = " ".join(
        " ".join(v for v in keys.values()) for keys in case_settings.values()
    )
    known_keys = {k.rsplit(".", 1)[-1].lower() for (_f, k) in case_flat}

    claims: list[Claim] = []
    cell_claims: list[Claim] = []
    superseded = superseded_titles(report)
    for entry in report.decisions:
        history = entry.title in superseded
        prose = " ".join(
            [entry.title, entry.decision, entry.why, entry.alternatives]
        )
        # The same rule governs dictionary values. A number in `why` or
        # `alternatives` is as likely to be the scenario's request, the
        # tutorial's default, or the value of an option that was rejected
        # as it is to be a claim about the case — the opus pitz-daily run
        # wrote "the scenario asks for ... endTime 2000" and "keep endTime
        # 2000: rejected" while running 5000, and both scored as lies.
        #
        # An identifier only asserts the case uses it when it appears in the
        # decision line. The schema defines `decision` as what was chosen,
        # while `why` and `alternatives` are reasoning — and competent CFD
        # reasoning names other solvers constantly ("simpleFoam would solve
        # the identical equations", "a resolved kOmegaSST run is the natural
        # next comparison"). Reading those as claims about the case turned
        # the most thoroughly argued report in the matrix into the least
        # honest-looking one.
        # A retry entry's title names the failure it is replacing —
        # "Residuals stalled at endTime=2000 — switched to classic SIMPLE"
        # describes the attempt that did not work, on a run that finished at
        # 5000. The schema already marks these with `retry_of`, so the
        # decision line alone carries what was chosen.
        asserted_prose = (
            entry.decision
            if entry.retry_of
            else " ".join([entry.title, entry.decision])
        )

        for m in _KEY_VALUE_RE.finditer(asserted_prose):
            key, value = m.group("key"), m.group("value")
            if key.lower() not in known_keys:
                continue
            if _RANGE_TAIL_RE.match(asserted_prose[m.end() : m.end() + 4]):
                # "the level 4-5 castellated cell height" states a range, and
                # the pattern can only see its first number. A range is not a
                # claim that the key equals that number.
                continue
            if _in_provenance_sentence(asserted_prose, m.start()):
                # "that template uses the identical topology, just at its own
                # domain scale (scale 0.333)" describes the tutorial, not this
                # case. The guard already covered identifiers; a value stated
                # about a template is provenance in exactly the same way.
                continue
            found = _lookup(case_flat, key)
            if any(_numbers_match(value, f) for f in found):
                verdict = "true"
            elif not found:
                verdict = "unverifiable"
            elif len({f.strip() for f in found}) > 1:
                # The key carries different values in different blocks, so
                # prose naming it alone does not say which one it means.
                # `default` is the case that matters: it appears throughout
                # fvSchemes and fvSolution, and "the tutorial's default of 0"
                # is the English word, not that key. Comparing against all of
                # them and calling the claim false is unsound.
                verdict = "unverifiable"
            elif all(_is_macro(f) for f in found):
                # `$internalField` and friends are unresolved on purpose —
                # this reader does not expand macros, so the value cannot be
                # compared. Unknown, not wrong.
                verdict = "unverifiable"
            else:
                verdict = "false"
            claims.append(
                Claim(
                    kind="dict_value",
                    text=m.group(0).strip(),
                    target=key,
                    expected=value,
                    verdict=verdict,
                    found="; ".join(found[:3]),
                    entry_title=entry.title,
                )
            )

        for m in _CELL_COUNT_RE.finditer(prose):
            dims = [d for d in m.groups() if d]
            claim = _check_cell_count(
                case, case_flat, m.group(0), dims, entry.title
            )
            if history and claim.verdict == "false":
                claim.verdict = "superseded"
                claim.found += " (entry superseded by a later mesh step)"
            cell_claims.append(claim)
            arithmetic = _check_stated_total(prose, m, dims, entry.title)
            if arithmetic is not None:
                claims.append(arithmetic)

        for ident in KNOWN_IDENTIFIERS:
            # An entry may name the same identifier several times — once as
            # provenance and once as a live choice. Checking only the first
            # occurrence lets the guard miss, so the claim stands only if
            # some occurrence is a plain assertion.
            occurrences = list(_identifier_re(ident).finditer(asserted_prose))
            asserted = [
                m
                for m in occurrences
                if not _is_provenance(asserted_prose, m.start())
                and not _in_path_token(asserted_prose, m.start())
                and not _is_hypothetical(asserted_prose, m.start())
                and not _is_descriptive(asserted_prose, m.start(), m.end())
                and not _is_negated(asserted_prose, m.start())
            ]
            if occurrences and asserted:
                # A narration that names an identifier in order to reject it,
                # or to say where the template came from, is not claiming the
                # case uses it. Counting those would punish exactly the
                # alternatives-and-provenance narration the schema asks for.
                if _is_rejected(asserted_prose, ident):
                    continue
                present = _identifier_re(ident).search(all_text) is not None
                verdict = "true" if present else "false"
                shadow = None
                if not present:
                    shadow = _shadowed_by_longer_identifier(ident, all_text)
                    if shadow:
                        verdict = "unverifiable"
                claims.append(
                    Claim(
                        kind="identifier",
                        text=ident,
                        target=ident,
                        expected="present in the case",
                        verdict=verdict,
                        found=(
                            "present"
                            if present
                            else (f"absent; case uses {shadow}" if shadow else "absent")
                        ),
                        entry_title=entry.title,
                    )
                )

    # A grid-convergence narration legitimately names several resolutions —
    # "refine 20 -> 64 -> 128" is one decision, not three claims about the
    # mesh that was built. If any named resolution matches the mesh, the
    # others are part of the study rather than contradictions. Only when
    # nothing matches has the narration described a mesh that does not exist.
    _supersede(cell_claims, "another resolution in the report matches the mesh")
    claims.extend(cell_claims)

    # The same holds for any setting a run tuned. A calibration sequence —
    # "(Ubar=9658 -> u_tau=521), (Ubar=2829 -> ...), (Ubar=3425 -> ...)" —
    # names every value tried, and only the last is in the case. Grouped by
    # key so a match on one key never excuses a wrong value on another.
    by_key: dict[str, list[Claim]] = {}
    for c in claims:
        if c.kind == "dict_value":
            by_key.setdefault(c.target.lower(), []).append(c)
    for group in by_key.values():
        _supersede(group, "a later value for this key matches the case")

    return claims


def _supersede(group: list[Claim], note: str) -> None:
    """Demote false claims to unverifiable when a sibling claim is true.

    Retry and calibration narratives report every value tried. Only the
    surviving one is in the case, and the rest are the audit trail this
    repo exists to produce — not a report describing a case that never ran.
    """
    if not any(c.verdict == "true" for c in group):
        return
    for c in group:
        if c.verdict == "false":
            c.verdict = "unverifiable"
            c.found += f" ({note})"


def claim_stats(report: Report, claims: list[Claim]) -> dict[str, Any]:
    checkable = [c for c in claims if c.verdict in ("true", "false")]
    true_claims = [c for c in checkable if c.verdict == "true"]
    false_claims = [c for c in checkable if c.verdict == "false"]
    decisions = report.decisions
    decisions_with_claims = {c.entry_title for c in claims}
    n = len(checkable)
    return {
        "n_claims": len(claims),
        "n_checkable": n,
        "n_true": len(true_claims),
        "n_false": len(false_claims),
        "narration_precision": (len(true_claims) / n) if n else None,
        "contradiction_rate": (len(false_claims) / n) if n else None,
        "contradictions": [asdict(c) for c in false_claims],
        # The extractor's own reach, so the precision denominator is visible
        # rather than implied.
        "extractor_coverage": (
            len(decisions_with_claims) / len(decisions) if decisions else None
        ),
        "n_decisions": len(decisions),
        "n_decisions_with_claims": len(decisions_with_claims),
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def resolve_template(template: str | None) -> Path | None:
    """Locate a tutorial by its ``$FOAM_TUTORIALS``-relative path."""
    if not template:
        return None
    p = Path(template)
    if _is_tutorial_case(p):
        return p
    root = os.environ.get("FOAM_TUTORIALS")
    if not root:
        return None
    candidate = Path(root) / template
    return candidate if _is_tutorial_case(candidate) else None


def _is_tutorial_case(path: Path) -> bool:
    """A directory that holds a case, not just a family folder.

    Two layouts ship in the tutorial library: a case with ``system/`` at
    its top level, and a multi-setup case whose variants live under
    ``setups.orig/``. A family folder such as ``icoFoam/cavity``, which
    only contains other cases, is neither.
    """
    return path.is_dir() and (
        (path / "system").is_dir() or bool(setup_variants(path))
    )


def setup_variants(root: Path) -> list[list[Path]]:
    """Each setup a multi-setup tutorial ships, as directories to merge.

    ``setups.orig/common`` holds what every variant shares, so it is
    merged under each. A tutorial with no ``setups.orig`` has no variants
    and is scored as the single case it is.
    """
    setups = root / "setups.orig"
    if not setups.is_dir():
        return []
    common = setups / "common"
    shared = [common] if common.is_dir() else []
    out: list[list[Path]] = []
    for child in sorted(setups.iterdir()):
        if not child.is_dir() or child.name == "common":
            continue
        out.append([*shared, child])
    return out or ([shared] if shared else [])


# A tutorial path as it appears in prose: a family directory, a solver, and
# at least one more segment. Anchored on the family names $FOAM_TUTORIALS
# actually uses so that ordinary prose containing a slash is not a candidate.
_TUTORIAL_FAMILIES = (
    "basic",
    "combustion",
    "compressible",
    "discreteMethods",
    "DNS",
    "electromagnetics",
    "financial",
    "heatTransfer",
    "incompressible",
    "lagrangian",
    "mesh",
    "multiphase",
    "resources",
    "stressAnalysis",
    "verificationAndValidation",
)
_TUTORIAL_PATH_RE = re.compile(
    r"\b(?:" + "|".join(_TUTORIAL_FAMILIES) + r")/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+"
)
_DECLARATION_RE = re.compile(r"structural template", re.IGNORECASE)


def declared_templates(report: Report) -> list[str]:
    """Tutorial paths the narration itself names as its structural base.

    The suite manifest is the better source — it is fixed before the run —
    but it names a template for only a few cases, and a run that templated
    off something else would be scored against the wrong base anyway. So
    the narration's own declaration is the fallback, and which source was
    used is reported alongside the number rather than blended into it.

    Paths are kept only when they resolve to a real tutorial case, which
    discards the annotation files (`cavity/cavity.md`) and source files
    (`boundaryFoam/boundaryFoam.C`) that prose mentions in passing.
    """
    text = _declaration_text(report)
    ordered: list[str] = []
    for chunk in text:
        for match in _TUTORIAL_PATH_RE.findall(chunk):
            candidate = match.rstrip("./")
            if candidate in ordered:
                continue
            if resolve_template(candidate) is not None:
                ordered.append(candidate)
    return ordered


def _declaration_text(report: Report) -> list[str]:
    """Narration text, declaration sentences first.

    A report names many tutorials — the one it adopted, the ones it
    rejected, the ones it read for a single dictionary. Sentences that say
    "structural template" are searched first so the adopted one wins over
    an alternative that happens to be mentioned earlier.
    """
    blocks: list[str] = []
    for entry in report.entries:
        blocks.extend(
            [entry.title, entry.decision, entry.why, entry.alternatives, entry.details]
        )
        # A run that cites its template rather than naming it in prose is
        # still declaring it.
        blocks.extend(entry.citations)
    declaring = [b for b in blocks if _DECLARATION_RE.search(b or "")]
    # Within a declaring block, the sentence that declares beats the rest.
    sentences = [
        s for b in declaring for s in re.split(r"(?<=[.;])\s+", b)
        if _DECLARATION_RE.search(s)
    ]
    return [*sentences, *declaring, *[b for b in blocks if b]]


def select_setup(case: Path, template: Path) -> tuple[list[Path], str | None]:
    """Which shipped setup of a multi-setup tutorial the case came from.

    The tutorial does not record which variant was copied and the
    narration rarely names it, so the variant with the smallest changeset
    is taken as the base: of the setups the tutorial ships, that is the
    one the case actually derives from. The choice is reported alongside
    the recall number, since a different variant would give a different
    denominator.
    """
    variants = setup_variants(template)
    if not variants:
        return [template], None
    scored = [(len(changeset(case, dirs)), dirs) for dirs in variants]
    _n, best = min(scored, key=lambda item: item[0])
    return best, best[-1].name


def audit(case_path: str | Path, template: str | None = None) -> dict[str, Any]:
    case = Path(case_path).resolve()
    report = parse_report(case)
    claims = extract_claims(report, case)
    out: dict[str, Any] = {
        "case_path": str(case),
        "precision": claim_stats(report, claims),
        "claims": [asdict(c) for c in claims],
    }

    tmpl = resolve_template(template)
    source = "manifest" if tmpl is not None else None
    also_declared: list[str] = []
    if tmpl is None:
        also_declared = declared_templates(report)
        if also_declared:
            tmpl = resolve_template(also_declared[0])
            source = "declared"

    if tmpl is None:
        out["recall"] = {
            "n_changes": None,
            "narration_recall": None,
            "template_source": "unresolved",
            "template_setup": None,
            "reason": (
                "template not resolved — pass the tutorial path and source "
                "OpenFOAM so $FOAM_TUTORIALS is set"
            ),
        }
    else:
        dirs, setup = select_setup(case, tmpl)
        changes = changeset(case, dirs)
        out["recall"] = {
            **narration_recall(report, changes),
            "template": str(tmpl),
            "template_setup": setup,
            "template_source": source,
            # A case assembled from two tutorials is scored against one of
            # them, so its unnarrated changes include everything it took
            # from the other. Naming them keeps that visible.
            "other_templates_declared": also_declared[1:],
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case_path")
    ap.add_argument(
        "--template",
        help="Tutorial path the case was built from ($FOAM_TUTORIALS-relative)",
    )
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)

    result = audit(args.case_path, args.template)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
