"""Run detection probes and score the result.

The assessment-only arm of `docs/evaluation-plan.md` §2.5. Each probe is a
small directory of artefacts with a known fault (or known to be clean);
the assessor reads it and either raises a concern or does not. Because no
solve is involved, a probe costs milliseconds, which is what lets the
detection arm carry enough N to say something with confidence.

What is scored, in order of increasing demand:

- **detected** — the assessor flagged a problem at all
- **localised** — it named the right metric or field

and, on the clean controls, whether it flagged anything at all. Recall is
always reported with the false-alarm rate beside it: an assessor that
flags everything scores perfect recall and is worthless, and the pair is
the only honest summary.

Recall is also split by whether a dedicated tool exists for the fault.
That separates the share of detection the engineering provides from the
share the model provides — and only the second moves when the model
changes.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from faults.injectors import ALL_PROBES, Probe
from reasoning_probe import ChatModel, OpenAICompatibleModel, run_reasoning_probe
from stats import wilson

# Verdicts that mean "this mesh should not be solved on as-is".
CONCERNING_MESH_VERDICTS = frozenset({"marginal", "poor"})
# Residual patterns that mean the solve has not reached a steady answer.
CONCERNING_PATTERNS = frozenset({"stalled", "oscillating", "diverging"})

# "acceptable" is deliberately absent: kOmegaSST at y+ 2 is a working mesh,
# and treating it as a fault would make the detector's false-alarm rate a
# measure of its strictness rather than its accuracy.
CONCERNING_Y_PLUS_VERDICTS = frozenset({"marginal", "poor"})


@dataclass
class ProbeOutcome:
    probe_id: str
    fault_class: str
    fault_present: bool
    expected_detector: str
    tool_detectable: bool
    detected: bool
    localised: bool
    detail: str = ""


def _assess_mesh(case: Path) -> tuple[bool, str, str]:
    from consultant_mcp import tools as consultant

    result = consultant.assess_mesh_quality(str(case))
    if not result.get("success"):
        return False, "", f"tool failed: {result.get('reason')}"
    verdict = str(result.get("overall_verdict", ""))
    flagged = [
        str(m.get("metric"))
        for m in result.get("metrics", [])
        if str(m.get("verdict")) in CONCERNING_MESH_VERDICTS
    ]
    return verdict in CONCERNING_MESH_VERDICTS, ",".join(flagged), verdict


def _assess_residuals(case: Path) -> tuple[bool, str, str]:
    from consultant_mcp import tools as consultant

    result = consultant.assess_residuals(str(case))
    if not result.get("success"):
        return False, "", f"tool failed: {result.get('reason')}"
    flagged = [
        str(f.get("field"))
        for f in result.get("fields", [])
        if str(f.get("pattern")) in CONCERNING_PATTERNS
    ]
    patterns = sorted({str(f.get("pattern")) for f in result.get("fields", [])})
    return bool(flagged), ",".join(flagged), ",".join(patterns)


def _assess_y_plus(case: Path) -> tuple[bool, str, str]:
    from consultant_mcp import tools as consultant

    result = consultant.assess_y_plus(str(case))
    if not result.get("success"):
        return False, "", f"tool failed: {result.get('reason')}"
    flagged = [
        str(p.get("patch"))
        for p in result.get("patches", [])
        if str(p.get("verdict")) in CONCERNING_Y_PLUS_VERDICTS
    ]
    verdict = str(result.get("overall_verdict", ""))
    return bool(flagged), ",".join(flagged), verdict


ASSESSORS = {
    "assess_mesh_quality": _assess_mesh,
    "assess_residuals": _assess_residuals,
    "assess_y_plus": _assess_y_plus,
}


def run_probe(
    probe: Probe, workdir: Path, model: ChatModel | None = None
) -> ProbeOutcome:
    """Materialise one probe and let the assessor look at it.

    With a model supplied, *every* probe also goes to the model — including
    the ones a tool can catch. That is the comparison H3 asks for: the same
    faults, judged by the tool and by the model, so the two shares of
    detection can be told apart instead of assumed.
    """
    case = workdir / probe.probe_id
    probe.write(case)

    if model is not None:
        answer = run_reasoning_probe(probe, model, workdir)
        return ProbeOutcome(
            probe_id=probe.probe_id,
            fault_class=probe.fault_class,
            fault_present=probe.fault_present,
            expected_detector=probe.expected_detector,
            tool_detectable=probe.tool_detectable,
            detected=answer["detected"],
            localised=answer["localised"],
            detail=(
                f"model: {answer['target']} | {answer['reason'][:80]}"
                + ("" if answer["parsed"] else " | UNPARSEABLE")
            ),
        )

    assessor = ASSESSORS.get(probe.expected_detector)
    if assessor is None:
        # Reasoning-only probes need a model in the loop; they are carried
        # in the catalogue and reported as not-yet-run rather than dropped,
        # so the coverage gap stays visible.
        return ProbeOutcome(
            probe_id=probe.probe_id,
            fault_class=probe.fault_class,
            fault_present=probe.fault_present,
            expected_detector=probe.expected_detector,
            tool_detectable=False,
            detected=False,
            localised=False,
            detail="requires a model in the loop; not run in the tool-only arm",
        )

    detected, flagged, detail = assessor(case)
    localised = bool(
        detected and probe.localization and probe.localization in flagged
    )
    return ProbeOutcome(
        probe_id=probe.probe_id,
        fault_class=probe.fault_class,
        fault_present=probe.fault_present,
        expected_detector=probe.expected_detector,
        tool_detectable=probe.tool_detectable,
        detected=detected,
        localised=localised,
        detail=f"{detail} | flagged: {flagged or 'nothing'}",
    )


def score(outcomes: list[ProbeOutcome]) -> dict[str, Any]:
    """Recall, false-alarm rate, and localisation, with intervals."""
    ran = [o for o in outcomes if "not run" not in o.detail]
    faulty = [o for o in ran if o.fault_present]
    clean = [o for o in ran if not o.fault_present]

    n_detected = sum(1 for o in faulty if o.detected)
    n_false_alarms = sum(1 for o in clean if o.detected)
    n_localised = sum(1 for o in faulty if o.localised)

    recall = wilson(n_detected, len(faulty))
    far = wilson(n_false_alarms, len(clean))
    localisation = wilson(n_localised, len(faulty))

    by_class: dict[str, Any] = {}
    for cls in sorted({o.fault_class for o in faulty}):
        subset = [o for o in faulty if o.fault_class == cls]
        ci = wilson(sum(1 for o in subset if o.detected), len(subset))
        by_class[cls] = {"n": len(subset), "recall": ci.point if ci else None}

    def as_dict(ci: Any) -> dict[str, Any] | None:
        return (
            {"point": ci.point, "low": ci.low, "high": ci.high, "n": ci.n}
            if ci
            else None
        )

    return {
        "n_probes": len(outcomes),
        "n_run": len(ran),
        "n_not_run": len(outcomes) - len(ran),
        "n_faulty": len(faulty),
        "n_clean": len(clean),
        # Always as a pair: recall alone rewards an assessor that flags
        # everything.
        "recall": as_dict(recall),
        "false_alarm_rate": as_dict(far),
        "localisation_rate": as_dict(localisation),
        "recall_by_class": by_class,
        "missed": [o.probe_id for o in faulty if not o.detected],
        "false_alarms": [o.probe_id for o in clean if o.detected],
    }


def run_all(
    workdir: Path | None = None, model: ChatModel | None = None
) -> dict[str, Any]:
    tmp = None
    if workdir is None:
        tmp = tempfile.TemporaryDirectory()
        workdir = Path(tmp.name)
    try:
        outcomes = [run_probe(p, workdir, model) for p in ALL_PROBES]
        return {
            "arm": "model" if model is not None else "tool",
            "summary": score(outcomes),
            "outcomes": [asdict(o) for o in outcomes],
        }
    finally:
        if tmp is not None:
            tmp.cleanup()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--workdir", type=Path, help="Keep the probe cases here")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--base-url",
        help=(
            "Score with a model instead of the tools: any OpenAI-compatible "
            "endpoint. This is the arm that measures judgement rather than "
            "thresholds."
        ),
    )
    ap.add_argument("--model", help="Model name at --base-url")
    ap.add_argument("--api-key", default="local")
    args = ap.parse_args(argv)

    model: ChatModel | None = None
    if args.base_url:
        if not args.model:
            ap.error("--base-url needs --model")
        model = OpenAICompatibleModel(
            base_url=args.base_url, model=args.model, api_key=args.api_key
        )

    result = run_all(args.workdir, model)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    if not args.quiet:
        s = result["summary"]
        print(
            f"arm: {result['arm']} | probes: {s['n_run']} run, "
            f"{s['n_not_run']} need a model in the loop"
        )
        for name in ("recall", "false_alarm_rate", "localisation_rate"):
            ci = s[name]
            if ci:
                print(
                    f"  {name:20} {ci['point']:.3f} "
                    f"[{ci['low']:.3f}, {ci['high']:.3f}] (n={ci['n']})"
                )
        if s["missed"]:
            print(f"  missed: {', '.join(s['missed'])}")
        if s["false_alarms"]:
            print(f"  false alarms: {', '.join(s['false_alarms'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
