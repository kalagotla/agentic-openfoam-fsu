"""Score one run: a case directory in, a structured record out.

This is the measuring instrument for `docs/evaluation-plan.md`. It reads
only artefacts a run leaves behind — `REPORT.md`, the solver and checkMesh
logs, `postProcessing/analysis/metrics.json` — and never re-derives a
verdict of its own. Where a tested tool already owns a judgement, the
scorer calls that tool instead of re-parsing the log:

- mesh quality → `consultant.assess_mesh_quality`
- convergence → `consultant.assess_residuals`
- citation integrity → `consultant.flag_uncited_claims`
- validation pass/fail → the `metrics.json` the case's own analysis script
  wrote through `compare_profiles`

Anything the scorer cannot establish is ``None``, never ``False``. "Not
measured" and "measured as failing" are different findings, and collapsing
them would let an absent artefact read as a defeat.

Usage:

    uv run python scripts/eval/score_report.py cases/work/lid-cavity \\
        --suite scripts/eval/suite.yaml --case-key lid-cavity \\
        -o record.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics as m
from narration_audit import audit as narration_audit
from report_parse import parse_report
from suite import load_suite

# Verdicts assess_mesh_quality can return that a run should proceed on.
ACCEPTABLE_MESH_VERDICTS = {"good", "acceptable"}

_TIME_DIR_RE = re.compile(r"^\d+(\.\d+)?$")
_APPLICATION_RE = re.compile(r"^\s*application\s+(\w+)\s*;", re.MULTILINE)

# Provenance keys `analysis/validate.py` should stamp into metrics.json so a
# later re-run compares against an attributed baseline (CLAUDE.md's replay
# requirement).
PROVENANCE_KEYS = (
    "numpy_version",
    "matplotlib_version",
    "git_commit",
    "sample_time",
    "reference_dataset",
)


def detect_run_kind(case: Path) -> str:
    """Tell a live run from an archived one.

    ``archive_case`` copies inputs, REPORT.md, the analysis script, and the
    carved-out analysis plots, but deliberately skips the mesh, the time
    directories, and the logs — replay is re-mesh + re-solve, not a rerun of
    the analysis alone. Scoring an archive as a run that failed to mesh
    would turn an intentional omission into a false failure, so capability
    fields that depend on the skipped artefacts are reported as unmeasured.
    """
    has_logs = any(case.glob("log.*"))
    has_mesh = (case / "constant" / "polyMesh").is_dir()
    has_metrics = (case / "postProcessing" / "analysis" / "metrics.json").is_file()
    if has_logs or has_mesh:
        return "live"
    if has_metrics or (case / "REPORT.md").is_file():
        return "archive"
    return "unknown"


def _repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / ".git").exists() and (p / "CLAUDE.md").exists():
            return p
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Capability (plan §3.1)
# ---------------------------------------------------------------------------


def _time_directories(case: Path) -> list[str]:
    return sorted(
        d.name
        for d in case.iterdir()
        if d.is_dir() and _TIME_DIR_RE.match(d.name) and d.name != "0"
    )


def authoring_stats(case: Path) -> dict[str, Any]:
    """Did the agent produce a structurally complete case?"""
    required = {
        "system/controlDict": case / "system" / "controlDict",
        "system/fvSchemes": case / "system" / "fvSchemes",
        "system/fvSolution": case / "system" / "fvSolution",
    }
    present = {k: p.is_file() for k, p in required.items()}
    control = required["system/controlDict"]
    application = None
    if control.is_file():
        mtch = _APPLICATION_RE.search(control.read_text(errors="replace"))
        application = mtch.group(1) if mtch else None
    return {
        "case_authored": all(present.values()),
        "required_dicts": present,
        "application": application,
        "has_analysis_script": (case / "analysis" / "validate.py").is_file(),
        "has_report": (case / "REPORT.md").is_file(),
    }


def mesh_stats(case: Path) -> dict[str, Any]:
    """Mesh existence plus the consultant's per-metric quality verdicts."""
    poly = case / "constant" / "polyMesh"
    meshed = (poly / "owner").is_file() or (poly / "points").is_file()
    out: dict[str, Any] = {
        "meshed": meshed,
        "mesh_pass": None,
        "overall_verdict": None,
        "metrics": None,
        "reason": None,
    }
    try:
        from consultant_mcp import tools as consultant
    except ImportError:  # pragma: no cover - consultant is a workspace dep
        out["reason"] = "consultant_unavailable"
        return out

    assessed = consultant.assess_mesh_quality(str(case))
    if not assessed.get("success"):
        out["reason"] = assessed.get("reason")
        return out
    verdict = assessed.get("overall_verdict")
    out["overall_verdict"] = verdict
    out["mesh_pass"] = verdict in ACCEPTABLE_MESH_VERDICTS
    out["metrics"] = [
        {k: mm.get(k) for k in ("metric", "value", "verdict")}
        for mm in assessed.get("metrics", [])
    ]
    return out


def convergence_stats(case: Path) -> dict[str, Any]:
    """Per-field residual classification from the consultant."""
    out: dict[str, Any] = {
        "solved": bool(_time_directories(case)),
        "time_directories": _time_directories(case),
        "converged": None,
        "fields": None,
        "reason": None,
    }
    try:
        from consultant_mcp import tools as consultant
    except ImportError:  # pragma: no cover
        out["reason"] = "consultant_unavailable"
        return out

    assessed = consultant.assess_residuals(str(case))
    if not assessed.get("success"):
        out["reason"] = assessed.get("reason")
        return out
    fields = assessed.get("fields", [])
    # Two different judgements live in each field dict: `pattern` is the
    # convergence classification (converged / stalled / oscillating /
    # diverging) and `verdict` is the quality band (good / marginal / ...).
    # Convergence is the pattern; reading `verdict` here would call a
    # converged run unconverged because its band is spelled "good".
    out["fields"] = [
        {k: f.get(k) for k in ("field", "pattern", "verdict", "last_value")}
        for f in fields
    ]
    out["converged"] = bool(fields) and all(
        f.get("pattern") == "converged" for f in fields
    )
    out["patterns"] = sorted({str(f.get("pattern")) for f in fields})
    return out


def validation_stats(case: Path) -> dict[str, Any]:
    """Pass/fail from the case's own `metrics.json`.

    The analysis script is agent-authored and its metric names are
    case-specific by design, so the file's shape varies between runs. Three
    forms carry the same evidence and are all read:

    - a ``checks`` list whose entries carry ``within_tolerance``;
    - the same per-quantity dicts keyed by name at the top level, which is
      what a script writing ``{"u_centerline": compare_profiles(...)}``
      produces;
    - a top-level ``verdict`` string.

    The first two are the same thing in different containers — both are
    `compare_profiles` output verbatim — so reading only the list form
    would report a validated run as unscoreable purely over how its script
    happened to collect the results. A file carrying none of the three is
    reported as nonconforming: an unscoreable metrics.json is a finding
    about the run, not a crash, and never a pass.
    """
    path = case / "postProcessing" / "analysis" / "metrics.json"
    out: dict[str, Any] = {
        "metrics_json_present": path.is_file(),
        "validated": None,
        "schema": None,
        "checks": None,
        "verdict": None,
        "provenance_present": None,
        "provenance_missing": None,
        "plots": [],
    }
    data = _read_json(path)
    if not isinstance(data, dict):
        out["schema"] = "missing" if data is None else "not_an_object"
        return out

    out["verdict"] = data.get("verdict")
    checks = data.get("checks")
    if isinstance(checks, list) and checks:
        flags = [c.get("within_tolerance") for c in checks if isinstance(c, dict)]
        if flags and all(isinstance(f, bool) for f in flags):
            out["schema"] = "checks"
            out["validated"] = all(flags)
        out["checks"] = [
            {
                k: c.get(k)
                for k in (
                    "quantity",
                    "reference_dataset",
                    "l2_error",
                    "linf_error",
                    "tolerance_threshold",
                    "within_tolerance",
                )
            }
            for c in checks
            if isinstance(c, dict)
        ]
    if out["validated"] is None:
        # Per-quantity results keyed by name, rather than gathered in a list.
        keyed = [
            (name, value)
            for name, value in data.items()
            if isinstance(value, dict) and isinstance(value.get("within_tolerance"), bool)
        ]
        if keyed:
            out["schema"] = "checks_by_name"
            out["validated"] = all(v["within_tolerance"] for _n, v in keyed)
            out["checks"] = [
                {
                    "quantity": name,
                    "reference_dataset": value.get("reference_dataset"),
                    "l2_error": value.get("l2_error"),
                    "linf_error": value.get("linf_error"),
                    "tolerance_threshold": value.get("tolerance_threshold"),
                    "within_tolerance": value.get("within_tolerance"),
                }
                for name, value in keyed
            ]

    if out["validated"] is None and isinstance(out["verdict"], str):
        out["schema"] = "verdict_only"
        out["validated"] = out["verdict"].strip().upper() == "PASS"
    if out["schema"] is None:
        out["schema"] = "nonconforming"

    prov = data.get("provenance")
    if isinstance(prov, dict):
        out["provenance_present"] = sorted(k for k in PROVENANCE_KEYS if prov.get(k))
        out["provenance_missing"] = sorted(
            k for k in PROVENANCE_KEYS if not prov.get(k)
        )
    else:
        out["provenance_present"] = []
        out["provenance_missing"] = sorted(PROVENANCE_KEYS)

    plot_dir = case / "postProcessing" / "analysis"
    out["plots"] = sorted(p.name for p in plot_dir.glob("*.png")) if plot_dir.is_dir() else []
    return out


# ---------------------------------------------------------------------------
# Integrity (plan §3.2, the part the consultant already owns)
# ---------------------------------------------------------------------------


def uncited_claim_stats(case: Path, n_decisions: int) -> dict[str, Any]:
    """`flag_uncited_claims` output, normalised per 10 decisions."""
    out: dict[str, Any] = {
        "n_flags": None,
        "uncited_claim_density": None,
        "orphan_citations": None,
        "verdict": None,
        "reason": None,
    }
    try:
        from consultant_mcp import tools as consultant
    except ImportError:  # pragma: no cover
        out["reason"] = "consultant_unavailable"
        return out

    flagged = consultant.flag_uncited_claims(str(case))
    if not flagged.get("success"):
        out["reason"] = flagged.get("reason")
        return out
    n_flags = int(flagged.get("n_flags") or 0)
    out["n_flags"] = n_flags
    out["verdict"] = flagged.get("verdict")
    out["orphan_citations"] = flagged.get("orphan_citations")
    if n_decisions:
        out["uncited_claim_density"] = 10.0 * n_flags / n_decisions
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


# The order a case moves through. A run that stopped early cannot have
# narrated decisions it never reached, so the furthest phase it got to is
# what makes decision coverage readable.
PHASE_ORDER = ("authored", "meshed", "solved", "validated")


def phase_reached(
    authoring: dict[str, Any], mesh: dict[str, Any], convergence: dict[str, Any],
    validation: dict[str, Any]
) -> str:
    """How far through the pipeline the run actually got."""
    if validation.get("validated") is not None:
        return "validated"
    if convergence.get("solved"):
        return "solved"
    if mesh.get("meshed"):
        return "meshed"
    if authoring.get("case_authored"):
        return "authored"
    return "nothing"


def score_case(
    case_path: str | Path,
    *,
    suite_entry: dict[str, Any] | None = None,
    run_meta: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Produce the full record for one run."""
    case = Path(case_path).resolve()
    repo_root = root or _repo_root(case)
    report = parse_report(case)
    index = m.ReferenceIndex.load(repo_root)
    expected = list((suite_entry or {}).get("expected_decisions", []))
    n_decisions = len(report.decisions)

    trust = {
        "citations": m.citation_stats(report, index),
        "decision_coverage": m.decision_coverage(report, expected),
        "field_completeness": m.field_completeness(report),
        "gaps": m.gap_stats(report),
        "origin_tags": m.origin_tag_stats(report),
        "retries": m.retry_stats(report),
        "hitl": m.hitl_stats(report),
        "phases": m.phase_stats(report),
        "uncited_claims": uncited_claim_stats(case, n_decisions),
    }

    authoring = authoring_stats(case)
    mesh = mesh_stats(case)
    convergence = convergence_stats(case)
    validation = validation_stats(case)

    validated = validation["validated"]
    run_kind = detect_run_kind(case)
    # On an archive the mesh and logs are absent by design, so a
    # mesh-dependent field is unmeasured rather than failed.
    setup_success: bool | None
    if run_kind == "archive":
        setup_success = None if not mesh["meshed"] else True
    else:
        setup_success = bool(authoring["case_authored"] and mesh["meshed"])
    capability = {
        "setup_success": setup_success,
        "mesh_pass": mesh["mesh_pass"],
        "converged": convergence["converged"],
        "validated": validated,
        # Only meaningful once we know the run validated at all.
        "first_try_validated": (
            None
            if validated is None
            else bool(validated and not report.retries)
        ),
        "n_retries": len(report.retries),
    }

    reached = phase_reached(authoring, mesh, convergence, validation)
    # Decision coverage is scored against the whole checklist, so a run that
    # stopped after authoring is missing entries for phases it never
    # reached. Saying how far it got keeps that from reading as an agent
    # that failed to narrate.
    trust["decision_coverage"]["phase_reached"] = reached
    trust["decision_coverage"]["complete_run"] = reached == "validated"

    return {
        "run": {
            "case_path": str(case),
            "case_name": case.name,
            "run_kind": run_kind,
            "phase_reached": reached,
            **(run_meta or {}),
        },
        "suite": {
            "key": (suite_entry or {}).get("key"),
            "tier": (suite_entry or {}).get("tier"),
            "novelty": (suite_entry or {}).get("novelty"),
        },
        "capability": capability,
        "authoring": authoring,
        "mesh": mesh,
        "convergence": convergence,
        "validation": validation,
        "trust": trust,
        "narration": narration_stats(case, suite_entry),
        "verdict": m.verdict_stats(report),
    }


def narration_stats(
    case: Path, suite_entry: dict[str, Any] | None
) -> dict[str, Any]:
    """Whether the narration describes the case that actually ran.

    Folded into the record rather than left to a separate pass, so a run's
    trust numbers and its narration numbers cannot drift apart. The recall
    half needs the tutorial the case was templated on; without it the
    precision half still stands, and recall reports why it is absent.
    """
    template = (suite_entry or {}).get("template_tutorial")
    try:
        result = narration_audit(case, template)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "precision": result["precision"]["narration_precision"],
        "contradiction_rate": result["precision"]["contradiction_rate"],
        "n_checkable_claims": result["precision"]["n_checkable"],
        "extractor_coverage": result["precision"]["extractor_coverage"],
        "recall": result["recall"].get("narration_recall"),
        # Recall against the template the run itself declared is a weaker
        # measurement than recall against a preregistered one, so the record
        # carries which it was rather than presenting one number for both.
        "template": result["recall"].get("template"),
        "template_source": result["recall"].get("template_source"),
        "template_setup": result["recall"].get("template_setup"),
        "n_change_units": result["recall"].get("n_changes"),
        "unnarrated": [c.get("key") for c in result["recall"].get("unnarrated", [])],
        "recall_unavailable": result["recall"].get("reason"),
        "contradictions": [
            {k: c[k] for k in ("kind", "text", "expected", "found")}
            for c in result["precision"]["contradictions"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case_path", help="Case directory to score")
    ap.add_argument("--suite", type=Path, help="Path to suite.yaml")
    ap.add_argument("--case-key", help="Key of the suite entry for this case")
    ap.add_argument("--run-meta", type=Path, help="JSON of run metadata to merge in")
    ap.add_argument("-o", "--output", type=Path, help="Write the record here")
    args = ap.parse_args(argv)

    suite_entry = None
    if args.suite and args.case_key:
        # Through the suite loader so spliced checklists arrive flattened.
        suite_entry = load_suite(args.suite).case(args.case_key).raw
    run_meta = _read_json(args.run_meta) if args.run_meta else None

    record = score_case(
        args.case_path,
        suite_entry=suite_entry,
        run_meta=run_meta if isinstance(run_meta, dict) else None,
    )
    text = json.dumps(record, indent=2, sort_keys=False)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
