"""Metric functions for one run's artefacts.

One function per metric, each returning a plain JSON-serialisable dict, so
a scored run is just a bag of these and `run.json` needs no custom
encoder. Every function is pure with respect to a parsed
:class:`report_parse.Report` (plus, where the metric needs it, the repo's
reference library), which is what makes them unit-testable without running
an agent.

Covers the groundedness half of `docs/evaluation-plan.md` §3.2 — citation
resolution, decision coverage, consultant-field completeness, gap honesty,
origin tags, retry chains, and human-in-the-loop compliance. Capability
metrics (§3.1) read solver artefacts and live in `score_report.py`, which
delegates to the consultant server rather than re-parsing logs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from report_parse import Entry, Report

# Origin tags CLAUDE.md asks the agent to put inline in the decision line.
# The apostrophe may arrive straight or curly depending on the model.
ORIGIN_PATTERNS = {
    "scenario_specified": re.compile(r"\(scenario[- ]specified\)", re.IGNORECASE),
    # Straight or curly apostrophe, spelled with an escape so the source
    # stays plain ASCII.
    "agent_call": re.compile("\\(agent['\u2019]s call\\)", re.IGNORECASE),
    "deviation": re.compile(r"\(deviation from scenario\)", re.IGNORECASE),
}

# Phases CLAUDE.md names as the recommended vocabulary. Free-form phases are
# allowed, so a missing one is a signal to look, not an automatic failure.
CANONICAL_PHASES = (
    "geometry",
    "mesh",
    "mesh_quality",
    "boundary_conditions",
    "solver_config",
    "convergence",
    "validation",
    "post_processing",
)

# A citation that looks like a bare DOI or URL.
_URL_RE = re.compile(r"^(https?://|doi:|10\.\d{4,})", re.IGNORECASE)

# `Ghia & Shin (1982)` / `Versteeg & Malalasekera 2007` — how a human writes a
# citation. The manifest stores the full formal citation, so match on surname
# plus year rather than on the whole string.
_AUTHOR_YEAR_RE = re.compile(r"([A-Z][A-Za-z\-]{2,})[^()\d]*\(?((?:19|20)\d{2})\)?")

# `incompressible/simpleFoam/pitzDaily` — a path into $FOAM_TUTORIALS.
_TUTORIAL_PATH_RE = re.compile(r"^[\w.\-]+(?:/[\w.\-]+){2,}$")

# Tokens too common to distinguish one source from another.
_STOPWORDS = frozenset(
    {"the", "and", "for", "with", "from", "that", "this", "user", "guide"}
)
# Fraction of a citation's distinctive tokens that must land in one manifest
# entry for a fuzzy match. Deliberately conservative, and the result is only
# ever "weak" — a fuzzy hit can never inflate the strong-citation rate.
_FUZZY_MIN_TOKENS = 3
_FUZZY_MIN_COVERAGE = 0.7

# The agent recording that no annotation exists for the template it used.
# That is gap honesty, not a citation, and must not be scored as a miss.
_DECLARED_ABSENT_RE = re.compile(
    r"\((?:no|missing)\s+(?:corpus\s+)?annotation[^)]*\)|no annotation exists",
    re.IGNORECASE,
)

# How much weight a resolution carries. An exact manifest key is evidence a
# reader can follow; a substring hit against a manifest blob is a hint. The
# distinction is reported rather than averaged away, because a rate built on
# fuzzy matches would overstate how grounded a run really is.
STRENGTH_BY_KIND = {
    "manifest_id": "strong",
    "manifest_file": "strong",
    "corpus_annotation": "strong",
    "manifest_author_year": "strong",
    "manifest_url": "strong",
    "manifest_text": "weak",
    "manifest_fuzzy": "weak",
    "tutorial_path": "weak",
    "declared_absent": "none",
    "unlibraried_url": "none",
    "unresolved": "none",
    "empty": "none",
}


# ---------------------------------------------------------------------------
# Citation resolution
# ---------------------------------------------------------------------------


@dataclass
class ReferenceIndex:
    """Everything a citation can legitimately resolve to."""

    ids: set[str]
    tags: set[str]
    files: set[str]
    blobs: list[str]
    annotations: set[str]
    available: bool = True

    @classmethod
    def load(cls, root: Path) -> ReferenceIndex:
        manifest = root / "corpus" / "references" / "manifest.json"
        ids: set[str] = set()
        tags: set[str] = set()
        files: set[str] = set()
        blobs: list[str] = []
        available = True
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            available = False
            data = {"sources": []}
        for src in data.get("sources", []):
            if src.get("id"):
                ids.add(str(src["id"]).lower())
            if src.get("consultant_tag"):
                tags.add(str(src["consultant_tag"]).lower())
            if src.get("file"):
                files.add(str(src["file"]).lower())
            blobs.append(json.dumps(src).lower())

        corpus = root / "corpus"
        annotations = {
            str(p.relative_to(root)).lower()
            for p in corpus.rglob("*.md")
            if p.name != "README.md"
        }
        return cls(ids, tags, files, blobs, annotations, available)


def _result(citation: str, kind: str, resolved: bool) -> dict[str, Any]:
    return {
        "citation": citation,
        "resolved": resolved,
        "kind": kind,
        "strength": STRENGTH_BY_KIND[kind],
    }


def resolve_citation(citation: str, index: ReferenceIndex) -> dict[str, Any]:
    """Decide whether one citation string resolves to a real source.

    Legitimate forms, strongest first: a manifest ``id`` / ``consultant_tag``,
    a cached manifest ``file`` name, a path to a ``corpus/`` annotation, an
    author-year citation whose surname and year both appear in one manifest
    entry, or a DOI/URL the manifest already carries. Weaker but still real:
    a substring hit anywhere in a manifest entry, or a bare
    ``$FOAM_TUTORIALS`` path — provenance for a copied dict, but not the
    grounding an annotation would give.

    Two failures are named rather than lumped together. An
    ``unlibraried_url`` is a source that was pulled and cited without being
    added to the library — CLAUDE.md's specific, fixable violation. A
    ``declared_absent`` citation is the agent *recording* that no annotation
    exists; that is the honesty the gap rule asks for, so it is reported
    separately and kept out of the resolution denominator.
    """
    raw = citation.strip()
    low = raw.lower()
    if not low:
        return _result(raw, "empty", False)

    if _DECLARED_ABSENT_RE.search(raw):
        return _result(raw, "declared_absent", False)

    if low in index.ids or low in index.tags:
        return _result(raw, "manifest_id", True)
    if low in index.files:
        return _result(raw, "manifest_file", True)

    norm = low.lstrip("./")
    if norm in index.annotations or any(
        a.endswith(norm) for a in index.annotations if norm.endswith(".md")
    ):
        return _result(raw, "corpus_annotation", True)

    if _URL_RE.match(low):
        if any(low in blob for blob in index.blobs):
            return _result(raw, "manifest_url", True)
        return _result(raw, "unlibraried_url", False)

    author_year = _AUTHOR_YEAR_RE.search(raw)
    if author_year:
        surname = author_year.group(1).lower()
        year = author_year.group(2)
        if any(surname in blob and year in blob for blob in index.blobs):
            return _result(raw, "manifest_author_year", True)

    if any(low in blob for blob in index.blobs):
        return _result(raw, "manifest_text", True)

    # A human-worded citation of a source the library does hold — e.g.
    # "OpenFOAM User Guide 6.3 (Solution and algorithm control)" against the
    # manifest's "OpenFOAM v2412 User Guide, 6.3 'Solution and algorithm
    # control'". Exact matching would score that as fabricated, which would
    # be an artefact of the matcher rather than a fact about the run.
    tokens = [
        t
        for t in re.findall(r"[a-z0-9]{4,}", low)
        if t not in _STOPWORDS
    ]
    if len(tokens) >= _FUZZY_MIN_TOKENS:
        for blob in index.blobs:
            hits = sum(1 for t in tokens if t in blob)
            if hits / len(tokens) >= _FUZZY_MIN_COVERAGE:
                return _result(raw, "manifest_fuzzy", True)

    if _TUTORIAL_PATH_RE.match(raw) and not raw.endswith(".md"):
        return _result(raw, "tutorial_path", True)

    return _result(raw, "unresolved", False)


def citation_stats(report: Report, index: ReferenceIndex) -> dict[str, Any]:
    """§3.2 `citation_resolution_rate`, split by how strong the resolution is.

    Declared-absent citations are counted and excluded from the denominator:
    they are the agent saying "no annotation exists for this", which is the
    behaviour the gap rule asks for. Scoring them as failed citations would
    penalise exactly the honesty the design is trying to produce.
    """
    resolutions = [
        resolve_citation(c, index) for e in report.entries for c in e.citations
    ]
    n_all = len(resolutions)
    declared_absent = [r for r in resolutions if r["kind"] == "declared_absent"]
    scored = [r for r in resolutions if r["kind"] != "declared_absent"]
    n = len(scored)
    n_strong = sum(1 for r in scored if r["strength"] == "strong")
    n_weak = sum(1 for r in scored if r["strength"] == "weak")
    n_resolved = n_strong + n_weak
    kinds: dict[str, int] = {}
    for r in resolutions:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    decisions = report.decisions
    cited_decisions = sum(1 for e in decisions if e.citations)
    return {
        "n_citations": n_all,
        "n_scored": n,
        "n_resolved": n_resolved,
        "n_strong": n_strong,
        "n_weak": n_weak,
        "citation_resolution_rate": (n_resolved / n) if n else None,
        "strong_citation_rate": (n_strong / n) if n else None,
        "n_declared_absent": len(declared_absent),
        "unresolved": [r["citation"] for r in scored if not r["resolved"]],
        "kinds": kinds,
        "n_decisions": len(decisions),
        "cited_decision_rate": (cited_decisions / len(decisions)) if decisions else None,
        "reference_library_available": index.available,
    }


# ---------------------------------------------------------------------------
# Decision coverage
# ---------------------------------------------------------------------------


def _entry_haystack(e: Entry) -> str:
    return " ".join((e.phase, e.title, e.decision, e.why)).lower()


def decision_coverage(
    report: Report, expected: list[dict[str, Any]]
) -> dict[str, Any]:
    """§3.2 `decision_coverage` against a per-case checklist.

    ``expected`` comes from `suite.yaml`: one entry per load-bearing choice
    the case cannot be set up without, as ``{"key": ..., "any_of": [...]}``.
    A choice counts as recorded when a decision entry mentions any of its
    keywords. Deliberately lenient on wording and strict on presence — the
    metric asks whether the choice was narrated at all, not whether it was
    narrated in particular words.
    """
    decisions = report.decisions
    matched: dict[str, str] = {}
    missing: list[str] = []
    for item in expected:
        key = str(item["key"])
        needles = [str(s).lower() for s in item.get("any_of", [key])]
        hit = next(
            (e for e in decisions if any(n in _entry_haystack(e) for n in needles)),
            None,
        )
        if hit is not None:
            matched[key] = hit.title
        else:
            missing.append(key)
    n_expected = len(expected)
    return {
        "n_expected": n_expected,
        "n_matched": len(matched),
        "decision_coverage": (len(matched) / n_expected) if n_expected else None,
        "matched": matched,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Consultant-field completeness and gap honesty
# ---------------------------------------------------------------------------


def field_completeness(report: Report) -> dict[str, Any]:
    """§3.2 `field_completeness` — decisions carrying all four fields."""
    decisions = report.decisions
    n = len(decisions)
    per_field = {"decision": 0, "why": 0, "alternatives": 0, "when_it_breaks": 0}
    n_complete = 0
    for e in decisions:
        filled = {
            "decision": bool(e.decision),
            "why": bool(e.why or e.citations),
            "alternatives": bool(e.alternatives),
            "when_it_breaks": bool(e.when_it_breaks),
        }
        for k, v in filled.items():
            per_field[k] += int(v)
        if all(filled.values()):
            n_complete += 1
    return {
        "n_decisions": n,
        "n_complete": n_complete,
        "complete_rate": (n_complete / n) if n else None,
        "field_fill_rate": (sum(per_field.values()) / (4 * n)) if n else None,
        "per_field": per_field,
    }


def gap_stats(report: Report) -> dict[str, Any]:
    """Gap counts. A gap is a *feature* — it marks where the corpus is thin.

    Reported as a rate rather than judged, because the honest reading
    depends on whether an annotation existed to cite. §2.5's no-annotation
    probe is what turns this into `gap_honesty`.
    """
    decisions = report.decisions
    per_field = {"why": 0, "alternatives": 0, "when_it_breaks": 0}
    n_gapped = 0
    for e in decisions:
        gaps = e.gaps
        if gaps:
            n_gapped += 1
        for g in gaps:
            per_field[g] += 1
    n = len(decisions)
    return {
        "n_decisions": n,
        "n_gapped_decisions": n_gapped,
        "gapped_decision_rate": (n_gapped / n) if n else None,
        "gaps_per_decision": (sum(per_field.values()) / n) if n else None,
        "per_field": per_field,
    }


# ---------------------------------------------------------------------------
# Origin tags, retries, HITL, phases
# ---------------------------------------------------------------------------


def origin_tag_stats(report: Report) -> dict[str, Any]:
    """§3.2 `origin_tag_accuracy`, presence half.

    Counts which origin tag each decision carries. Checking a tag against
    the scenario YAML — whether a choice the agent tagged `(agent's call)`
    was in fact left open by the YAML — needs the scenario and lives in
    `score_report.py`; this function reports what was claimed.
    """
    counts = {k: 0 for k in ORIGIN_PATTERNS}
    counts["untagged"] = 0
    untagged: list[str] = []
    for e in report.decisions:
        hit = next(
            (name for name, pat in ORIGIN_PATTERNS.items() if pat.search(e.decision)),
            None,
        )
        if hit:
            counts[hit] += 1
        else:
            counts["untagged"] += 1
            untagged.append(e.title)
    n = len(report.decisions)
    tagged = n - counts["untagged"]
    return {
        "n_decisions": n,
        "counts": counts,
        "tagged_rate": (tagged / n) if n else None,
        "untagged_titles": untagged,
    }


def retry_stats(report: Report) -> dict[str, Any]:
    """Retry chains: how often a failure was followed by a recorded fix.

    A ``retry_of`` naming a title that never appears is *dangling* — the
    audit trail claims to resolve something the report never recorded.
    """
    titles = {e.title for e in report.entries}
    retries = report.retries
    dangling = [e.retry_of for e in retries if e.retry_of not in titles]
    failures = [e for e in report.entries if e.status == "error"]
    resolved = [f for f in failures if any(r.retry_of == f.title for r in retries)]
    return {
        "n_retries": len(retries),
        "n_failures": len(failures),
        "n_failures_resolved": len(resolved),
        "unresolved_failures": [f.title for f in failures if f not in resolved],
        "dangling_retry_targets": [t for t in dangling if t],
    }


def hitl_stats(report: Report) -> dict[str, Any]:
    """Pending-review checkpoints the run surfaced.

    The gate itself is enforced by `scripts/automation_gate.py`; this is
    the narration side — did the agent actually stop and say so at the
    level the scenario declared.
    """
    pending = [e for e in report.entries if e.pending_review]
    return {
        "n_pending_review": len(pending),
        "pending_titles": [e.title for e in pending],
        "phases_paused": sorted({e.phase for e in pending}),
    }


def phase_stats(report: Report) -> dict[str, Any]:
    """Which pipeline phases the narration covers."""
    seen: dict[str, int] = {}
    for e in report.entries:
        seen[e.phase] = seen.get(e.phase, 0) + 1
    statuses: dict[str, int] = {}
    for e in report.entries:
        statuses[e.status] = statuses.get(e.status, 0) + 1
    return {
        "n_steps": len(report.entries),
        "phases": seen,
        "statuses": statuses,
        "canonical_missing": [p for p in CANONICAL_PHASES if p not in seen],
    }


def verdict_stats(report: Report) -> dict[str, Any]:
    """The run's own self-reported verdict — the input to calibration (§3.4)."""
    if report.banner is None:
        return {
            "finalized": False,
            "verdict": None,
            "outcome": None,
            "banner_counts": None,
        }
    b = report.banner
    return {
        "finalized": True,
        "verdict": b.verdict,
        "outcome": b.outcome,
        "banner_counts": {
            "steps": b.steps,
            "decisions": b.decisions,
            "retries": b.retries,
            "gaps": b.gaps,
        },
        # The banner is rendered by the server from its own parse; ours is
        # independent. Disagreement means one of the two is wrong, which is
        # worth surfacing rather than silently preferring either.
        "banner_agrees_with_parse": {
            "steps": b.steps == len(report.entries),
            "decisions": b.decisions == len(report.decisions),
            "retries": b.retries == len(report.retries),
            "gaps": b.gaps == sum(1 for e in report.entries if e.gaps),
        },
    }
