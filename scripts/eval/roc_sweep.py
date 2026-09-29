"""Detection curve for the tool arm, from `docs/evaluation-plan.md` §3.4.

A single recall number describes one operating point. Comparing a tool
against a model at whatever operating points they happen to sit on
compares strictness as much as accuracy — a detector that flags everything
scores perfect recall and is useless. The curve fixes that: it sweeps the
tool's thresholds, and reports what its recall is *at the model's
false-alarm rate*, which is the comparison H3 actually asks for.

The sweep moves `MeshThresholds` and calls the same `assess_mesh_quality`
an agent calls. Re-deriving the verdicts here with a copy of the band
logic would measure the copy, which is the failure the repo's trust rule
exists to prevent.

Two detectors are swept, and their knobs are not the same shape. The mesh
bands all point the same way, so one multiplier moves them together. The
residual cuts do not — lowering the oscillation cut flags more, lowering
the stall cut flags less — so those move on a `sensitivity` parameter that
is defined to raise detection in every branch at once. Both produce an
ordered family of operating points, which is all a curve needs.

y+ is not swept. Its bands are per turbulence-model-class rather than a
single scale, so it sits at its shipped operating point and is reported as
such rather than folded in silently.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "servers" / "consultant" / "src"))

from consultant_mcp.assessments import (
    DEFAULT_MESH_THRESHOLDS,
    DEFAULT_RESIDUAL_THRESHOLDS,
)
from faults.injectors import ALL_PROBES, Probe
from stats import wilson

CONCERNING = frozenset({"marginal", "poor"})
CONCERNING_PATTERNS = frozenset({"stalled", "oscillating", "diverging"})
# Strict to permissive. 1.0 is what the tool ships with, so the shipped
# operating point is always on the curve rather than being approximated by
# the nearest sampled one.
DEFAULT_FACTORS = (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0)


def _ci(interval: Any) -> tuple[float, float] | None:
    """The Wilson bounds as a plain pair, or None when n is zero."""
    return (interval.low, interval.high) if interval is not None else None


def probes_for(detector: str) -> list[Probe]:
    """Probes whose verdict the named detector actually governs."""
    return [p for p in ALL_PROBES if p.expected_detector == detector]


def mesh_probes() -> list[Probe]:
    """Probes whose detector the mesh thresholds govern."""
    return probes_for("assess_mesh_quality")


def residual_probes() -> list[Probe]:
    """Probes whose detector the residual cuts govern."""
    return probes_for("assess_residuals")


def _mesh_flags(case: Path, factor: float) -> list[str] | None:
    from consultant_mcp.tools import assess_mesh_quality

    result = assess_mesh_quality(
        str(case), DEFAULT_MESH_THRESHOLDS.scaled(factor)
    )
    if not result.get("success"):
        return None
    return [
        str(m.get("metric"))
        for m in result.get("metrics", [])
        if str(m.get("verdict")) in CONCERNING
    ]


def _residual_flags(case: Path, factor: float) -> list[str] | None:
    from consultant_mcp.tools import assess_residuals

    result = assess_residuals(
        str(case), bands=DEFAULT_RESIDUAL_THRESHOLDS.at_sensitivity(factor)
    )
    if not result.get("success"):
        return None
    return [
        str(f.get("field"))
        for f in result.get("fields", [])
        if str(f.get("pattern")) in CONCERNING_PATTERNS
    ]


DETECTORS = {
    "assess_mesh_quality": _mesh_flags,
    "assess_residuals": _residual_flags,
}


def operating_point(
    probes: list[Probe],
    factor: float,
    workdir: Path,
    detector: str = "assess_mesh_quality",
) -> dict[str, Any]:
    """Recall and false-alarm rate at one point on the detector's curve."""
    flags_at = DETECTORS[detector]
    hits = alarms = n_faulty = n_clean = 0
    localised = 0
    for probe in probes:
        case = workdir / f"{detector}-f{factor}" / probe.probe_id
        probe.write(case)
        flagged = flags_at(case, factor)
        if flagged is None:
            continue
        detected = bool(flagged)
        if probe.fault_present:
            n_faulty += 1
            hits += detected
            localised += detected and probe.localization in flagged
        else:
            n_clean += 1
            alarms += detected
    return {
        "factor": factor,
        "detector": detector,
        "n_faulty": n_faulty,
        "n_clean": n_clean,
        "recall": (hits / n_faulty) if n_faulty else None,
        "recall_ci": _ci(wilson(hits, n_faulty)),
        "false_alarm_rate": (alarms / n_clean) if n_clean else None,
        "false_alarm_ci": _ci(wilson(alarms, n_clean)),
        "localisation_rate": (localised / n_faulty) if n_faulty else None,
        "youden_j": (
            (hits / n_faulty) - (alarms / n_clean)
            if n_faulty and n_clean
            else None
        ),
    }


def sweep(
    workdir: Path,
    factors: tuple[float, ...] = DEFAULT_FACTORS,
    detector: str = "assess_mesh_quality",
) -> dict[str, Any]:
    probes = probes_for(detector)
    points = [operating_point(probes, f, workdir, detector) for f in factors]
    return {
        "detector": detector,
        "n_probes": len(probes),
        "points": points,
        "shipped": next((p for p in points if p["factor"] == 1.0), None),
    }


def recall_at_false_alarm_rate(
    points: list[dict[str, Any]], target: float
) -> dict[str, Any] | None:
    """The strictest operating point that stays within a false-alarm budget.

    Strictest, not nearest: a comparison "at the same false-alarm rate" is
    only fair if the tool is not allowed to exceed the budget it is being
    held to.
    """
    within = [
        p
        for p in points
        if p["false_alarm_rate"] is not None and p["false_alarm_rate"] <= target
    ]
    if not within:
        return None
    return max(within, key=lambda p: (p["recall"] or 0.0))


def render(report: dict[str, Any]) -> str:
    label = {
        "assess_mesh_quality": ("mesh quality", "thresholds scaled together"),
        "assess_residuals": ("residual patterns", "cuts moved by sensitivity"),
    }.get(report["detector"], (report["detector"], "operating point moved"))
    lines = [
        f"# Detection curve — {label[0]}",
        "",
        f"{report['n_probes']} probes, {label[1]}. "
        "Factor 1.0 is the shipped operating point.",
        "",
        "| Factor | Recall | False alarms | Youden J | Localisation |",
        "|---|---|---|---|---|",
    ]
    for p in report["points"]:
        def ci(point: dict[str, Any], key: str, rate: str) -> str:
            v, c = point[rate], point[key]
            if v is None:
                return "—"
            return f"{v:.3f} [{c[0]:.2f}, {c[1]:.2f}]" if c else f"{v:.3f}"

        mark = " ←ships" if p["factor"] == 1.0 else ""
        lines.append(
            f"| {p['factor']:g}{mark} | {ci(p, 'recall_ci', 'recall')} | "
            f"{ci(p, 'false_alarm_ci', 'false_alarm_rate')} | "
            f"{p['youden_j']:.3f} | {p['localisation_rate']:.3f} |"
        )

    best = max(report["points"], key=lambda p: p["youden_j"] or -1)
    lines += [
        "",
        f"Best Youden J on this corpus: factor {best['factor']:g} "
        f"(J = {best['youden_j']:.3f}). The shipped point is "
        f"{report['shipped']['youden_j']:.3f}.",
    ]
    for target in (0.0, 0.1, 0.25):
        point = recall_at_false_alarm_rate(report["points"], target)
        if point is None:
            lines.append(
                f"- At a false-alarm budget of {target:.0%} the tool has no "
                "operating point: it cannot get that quiet at any threshold."
            )
        else:
            lines.append(
                f"- At a false-alarm budget of {target:.0%}: recall "
                f"{point['recall']:.3f} at factor {point['factor']:g} "
                f"(false alarms {point['false_alarm_rate']:.3f})."
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument(
        "--detector",
        default="all",
        choices=["all", *DETECTORS],
        help="Which detector to sweep (default: every one that can be)",
    )
    args = ap.parse_args(argv)

    wanted = list(DETECTORS) if args.detector == "all" else [args.detector]
    reports = [sweep(args.workdir, detector=d) for d in wanted]
    report = reports[0] if len(reports) == 1 else {"sweeps": reports}
    text = "\n\n".join(render(r) for r in reports)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
