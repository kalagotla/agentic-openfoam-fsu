"""Turn many scored runs into tables that can survive being read closely.

Aggregation is where a benchmark usually starts lying. Six models get one
number each, the numbers are sorted, and a leaderboard appears — with no
interval, no correction for having made twenty comparisons, and no hint
that the spread between cases is larger than the spread between models.
This module refuses each of those in turn:

- every rate carries a Wilson interval, so ``9/9`` reads as ``[0.70, 1.00]``;
- detection recall never appears without its false-alarm rate, because an
  assessor that flags everything scores perfectly;
- model-versus-model comparisons are paired (McNemar over the same probes)
  and Holm-corrected across the family, since a wide benchmark generates
  significance by accident;
- differences carry an effect size, because a p-value says a gap is
  unlikely to be chance and nothing about whether it matters;
- and the variance is decomposed, so a table whose spread comes from which
  cases were chosen rather than which model ran says so out loud.

Usage:

    uv run python scripts/eval/aggregate.py --probes scripts/eval/results/probes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stats import (
    cluster_adjusted_wilson,
    cohens_h,
    cohens_kappa,
    holm_bonferroni,
    mcnemar,
    probability_better,
    variance_components,
    wilson,
)

# The arm every model arm is compared against: the consultant's assessors.
TOOL_ARM = "tool"


def load_probe_results(directory: Path) -> dict[str, dict[str, Any]]:
    """Read one probe-run JSON per arm, keyed by arm name."""
    arms: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "outcomes" not in data:
            continue
        arms[path.stem] = data
    return arms


def _outcome_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {o["probe_id"]: o for o in data.get("outcomes", [])}


def _ran(outcome: dict[str, Any]) -> bool:
    return "not run" not in (outcome.get("detail") or "")


def _answered(outcome: dict[str, Any]) -> bool:
    """Did the arm actually return a usable verdict on this probe?

    An arm that errored, or replied in a form the contract does not admit,
    did not judge the artefact. Counting that as "saw no problem" would
    turn an unreachable endpoint or a model that ignores the output format
    into a model that never notices anything — the same score, an entirely
    different fact.
    """
    return "UNPARSEABLE" not in (outcome.get("detail") or "")


def _clustered_recall(faulty: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Recall widened by how strongly outcomes cluster within fault class."""
    if not faulty:
        return None
    groups: dict[str, list[bool]] = {}
    for o in faulty:
        groups.setdefault(o["fault_class"], []).append(bool(o["detected"]))
    clusters = [(sum(hits), len(hits)) for hits in groups.values()]
    result = cluster_adjusted_wilson(clusters)
    adjusted = result["adjusted"]
    if adjusted is None:
        return None
    return {
        "point": adjusted.point,
        "low": adjusted.low,
        "high": adjusted.high,
        "effective_n": result["effective_n"],
        "design_effect": round(result["design_effect"], 3),
        "n_clusters": len(clusters),
    }


def arm_summary(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Recall, false-alarm rate, and localisation for one arm."""
    attempted = [o for o in data.get("outcomes", []) if _ran(o)]
    outcomes = [o for o in attempted if _answered(o)]
    faulty = [o for o in outcomes if o["fault_present"]]
    clean = [o for o in outcomes if not o["fault_present"]]
    n_unanswered = len(attempted) - len(outcomes)

    def rate(hits: int, n: int) -> dict[str, Any] | None:
        ci = wilson(hits, n)
        return (
            {"point": ci.point, "low": ci.low, "high": ci.high, "n": ci.n}
            if ci
            else None
        )

    recall = rate(sum(1 for o in faulty if o["detected"]), len(faulty))
    far = rate(sum(1 for o in clean if o["detected"]), len(clean))
    return {
        "arm": name,
        "n_faulty": len(faulty),
        "n_clean": len(clean),
        "recall": recall,
        "false_alarm_rate": far,
        "localisation_rate": rate(
            sum(1 for o in faulty if o["localised"]), len(faulty)
        ),
        # Detection is only meaningful net of false alarms. Youden's J is
        # the simplest honest single number: recall minus false-alarm rate,
        # zero for an assessor that answers at random.
        "youden_j": (
            round(recall["point"] - far["point"], 4)
            if recall and far
            else None
        ),
        "n_attempted": len(attempted),
        "unparseable": n_unanswered,
        # Probes are not independent: several share an injector, so a model
        # that understands one non-orthogonality probe likely gets them all.
        # The design effect turns nine such probes into the evidence they
        # actually carry.
        "recall_clustered": _clustered_recall(faulty),
        # Scores are computed over answered probes only, so this says how
        # much of the arm's run those scores actually rest on.
        "answer_rate": (
            len(outcomes) / len(attempted) if attempted else None
        ),
        "scoreable": bool(outcomes),
        "tool_share_recall": rate(
            sum(1 for o in faulty if o["tool_detectable"] and o["detected"]),
            sum(1 for o in faulty if o["tool_detectable"]),
        ),
        "reasoning_share_recall": rate(
            sum(1 for o in faulty if not o["tool_detectable"] and o["detected"]),
            sum(1 for o in faulty if not o["tool_detectable"]),
        ),
    }


def paired_against_tool(
    arms: dict[str, dict[str, Any]], baseline: str = TOOL_ARM
) -> dict[str, Any]:
    """Compare each model arm against the tool arm on the probes both ran.

    Paired on probe id: the arms see identical artefacts, so pairing
    removes probe difficulty entirely and is worth far more per probe than
    adding probes to an unpaired test.
    """
    if baseline not in arms:
        return {"baseline": baseline, "available": False, "comparisons": {}}

    base = _outcome_map(arms[baseline])
    comparisons: dict[str, Any] = {}
    p_values: dict[str, float] = {}

    for name, data in arms.items():
        if name == baseline:
            continue
        other = _outcome_map(data)
        shared = [
            pid
            for pid in base
            if pid in other
            and _ran(base[pid])
            and _ran(other[pid])
            and _answered(base[pid])
            and _answered(other[pid])
        ]
        faulty = [pid for pid in shared if base[pid]["fault_present"]]
        if not faulty:
            continue
        base_hits = [bool(base[pid]["detected"]) for pid in faulty]
        other_hits = [bool(other[pid]["detected"]) for pid in faulty]
        test = mcnemar(base_hits, other_hits)
        base_rate = sum(base_hits) / len(base_hits)
        other_rate = sum(other_hits) / len(other_hits)
        comparisons[name] = {
            "n_paired": len(faulty),
            "baseline_recall": round(base_rate, 4),
            "arm_recall": round(other_rate, 4),
            "difference": round(other_rate - base_rate, 4),
            "effect_size_h": round(cohens_h(other_rate, base_rate), 4),
            "only_baseline_caught": test.only_a,
            "only_arm_caught": test.only_b,
            "discordant": test.discordant,
            "p_value": round(test.p_value, 6),
            # At this corpus size a corrected p-value mostly reports that
            # the corpus is small. The posterior answers the question a
            # reader actually has.
            "p_baseline_better": round(
                probability_better(
                    sum(base_hits), len(base_hits), sum(other_hits), len(other_hits)
                ),
                4,
            ),
            # Agreement over every shared probe, clean ones included: two
            # assessors can match on recall and disagree about which
            # specific artefacts are faulty.
            "kappa_vs_baseline": round(
                cohens_kappa(
                    [bool(base[p]["detected"]) for p in shared],
                    [bool(other[p]["detected"]) for p in shared],
                ).kappa,
                4,
            ),
        }
        p_values[name] = test.p_value

    return {
        "baseline": baseline,
        "available": True,
        "comparisons": comparisons,
        "multiplicity": holm_bonferroni(p_values),
    }


def variance_by_fault_class(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """How much of the spread is the fault class rather than the arm."""
    observations: list[tuple[str, str, float]] = []
    for name, data in arms.items():
        by_class: dict[str, list[bool]] = {}
        for outcome in data.get("outcomes", []):
            if (
                not outcome["fault_present"]
                or not _ran(outcome)
                or not _answered(outcome)
            ):
                continue
            by_class.setdefault(outcome["fault_class"], []).append(
                bool(outcome["detected"])
            )
        for fault_class, hits in by_class.items():
            observations.append((fault_class, name, sum(hits) / len(hits)))
    return variance_components(observations)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def load_run_records(directory: Path) -> list[dict[str, Any]]:
    """Every scored run under a results directory."""
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*/record.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def run_table(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per run, carrying how far it got alongside what it scored."""
    rows: list[dict[str, Any]] = []
    for r in records:
        run = r.get("run", {})
        cap = r.get("capability", {})
        trust = r.get("trust") or {}
        cost = run.get("cost") or {}
        coverage = trust.get("decision_coverage") or {}
        citations = trust.get("citations") or {}
        narration = r.get("narration") or {}
        # The suite key names the benchmark case; case_name is the directory
        # the artefacts were moved into, which is the same word for every run.
        suite_key = (r.get("suite") or {}).get("key")
        rows.append(
            {
                "case": suite_key or run.get("case_key") or run.get("case_name"),
                "model": run.get("model"),
                # Empty for the ordinary arm. A populated list means the run
                # could not reach those servers, so its numbers answer a
                # different question and must not be pooled with the rest.
                "ablated": tuple(run.get("ablated_servers") or ()),
                "reached": run.get("phase_reached"),
                "validated": cap.get("validated"),
                "mesh_pass": cap.get("mesh_pass"),
                "converged": cap.get("converged"),
                "retries": cap.get("n_retries"),
                "decision_coverage": coverage.get("decision_coverage"),
                "complete_run": coverage.get("complete_run"),
                "citation_resolution": citations.get("citation_resolution_rate"),
                "turns": cost.get("iterations"),
                "tool_calls": cost.get("tool_calls"),
                "cost_equiv": cost.get("cost_usd_equivalent"),
                "narration_precision": narration.get("precision"),
                "contradiction_rate": narration.get("contradiction_rate"),
                "narration_recall": narration.get("recall"),
                # `gate_hook_disabled` is what older records carry; it named
                # an intent the hook never honoured. `gate_off` is what the
                # arm actually was.
                "gate_off": run.get("gate_off", run.get("gate_hook_disabled")),
            }
        )
    return rows


def split_arms(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Ordinary runs, and each ablation arm keyed by what it withheld.

    Pooling an ablated run into the headline rate would answer "how well
    does the tool do" with runs where part of the tool was absent.
    """
    ordinary = [r for r in rows if not r.get("ablated")]
    arms: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("ablated"):
            arms.setdefault("no-" + "-".join(r["ablated"]), []).append(r)
    return ordinary, arms


def ablation_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Each ablation arm against the ordinary arm, on the cases both ran.

    Paired on case *and model*, because the arms are only comparable where
    the same case was attempted both ways by the same model. Pairing on
    case alone let a cost column compare an arm holding two models against
    one holding a single cheaper model, and report the difference as the
    ablation's.
    """
    ordinary, arms = split_arms(rows)
    if not arms:
        return {"arms": {}}

    def by_case(subset: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
        out: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for r in subset:
            out.setdefault((str(r.get("case")), str(r.get("model"))), []).append(r)
        return out

    base = by_case(ordinary)
    out: dict[str, Any] = {}
    for name, subset in arms.items():
        arm = by_case(subset)
        shared = sorted(set(base) & set(arm))
        cases = []
        for case in shared:
            def rate(rs: list[dict[str, Any]], key: str) -> float | None:
                scored = [r for r in rs if r.get(key) is not None]
                return (
                    sum(1 for r in scored if r[key]) / len(scored)
                    if scored
                    else None
                )

            def mean(rs: list[dict[str, Any]], key: str) -> float | None:
                vals = [r[key] for r in rs if r.get(key) is not None]
                return (sum(vals) / len(vals)) if vals else None

            cases.append(
                {
                    "case": case[0],
                    "model": case[1],
                    "n_ordinary": len(base[case]),
                    "n_ablated": len(arm[case]),
                    "validated_ordinary": rate(base[case], "validated"),
                    "validated_ablated": rate(arm[case], "validated"),
                    "citations_ordinary": mean(base[case], "citation_resolution"),
                    "citations_ablated": mean(arm[case], "citation_resolution"),
                    "coverage_ordinary": mean(base[case], "decision_coverage"),
                    "coverage_ablated": mean(arm[case], "decision_coverage"),
                    "cost_ordinary": mean(base[case], "cost_equiv"),
                    "cost_ablated": mean(arm[case], "cost_equiv"),
                }
            )
        out[name] = {"n_cases": len(shared), "cases": cases}
    return {"arms": out}


def capability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rates over runs, counting only runs that could have produced them.

    A run that stopped after authoring never had the chance to validate, so
    including it in a validation rate would report a benchmark failure where
    there was an early stop. Rates are taken over runs that reached the
    relevant phase, and the denominators are reported.
    """
    def rate(key: str, eligible: list[dict[str, Any]]) -> dict[str, Any] | None:
        scored = [r for r in eligible if r.get(key) is not None]
        if not scored:
            return None
        ci = wilson(sum(1 for r in scored if r[key]), len(scored))
        return (
            {"point": ci.point, "low": ci.low, "high": ci.high, "n": ci.n}
            if ci
            else None
        )

    def clustered(key: str, eligible: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The same rate, widened for repeats of one case.

        Four seeds of the lid cavity are four observations of one case, not
        four independent points on the benchmark. A plain interval over
        them claims precision the design does not have, and the more the
        repeats agree the worse the overstatement.
        """
        scored = [r for r in eligible if r.get(key) is not None]
        if not scored:
            return None
        by_case: dict[str, list[bool]] = {}
        for r in scored:
            by_case.setdefault(str(r.get("case")), []).append(bool(r[key]))
        if len(by_case) < 2:
            return None
        return cluster_adjusted_wilson(
            [(sum(v), len(v)) for v in by_case.values()]
        )

    complete = [r for r in rows if r.get("complete_run")]
    return {
        "n_runs": len(rows),
        "n_cases": len({r.get("case") for r in rows}),
        "n_complete": len(complete),
        "reached": {
            phase: sum(1 for r in rows if r.get("reached") == phase)
            for phase in ("nothing", "authored", "meshed", "solved", "validated")
        },
        "mesh_pass": rate("mesh_pass", rows),
        "converged": rate("converged", rows),
        "validated": rate("validated", rows),
        "mesh_pass_clustered": clustered("mesh_pass", rows),
        "converged_clustered": clustered("converged", rows),
        "validated_clustered": clustered("validated", rows),
        "median_cost_equiv": _median(
            [r["cost_equiv"] for r in rows if r.get("cost_equiv") is not None]
        ),
        "median_turns": _median(
            [r["turns"] for r in rows if r.get("turns") is not None]
        ),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def render_runs_markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = ["# Runs", ""]
    # The model column appears only when the matrix carries more than one.
    # With a single model it is the same word on every line, which is noise;
    # with two it is the thing a reader is comparing.
    multi_model = len({r.get("model") for r in rows if r.get("model")}) > 1
    model_head = "Model | " if multi_model else ""
    model_rule = "---|" if multi_model else ""
    lines.append(
        f"| Case | {model_head}Reached | Validated | Mesh | Conv. | Coverage "
        "| Cites | Narr. prec. | Contra. | Narr. recall | Turns | Cost eq. |"
    )
    lines.append(f"|---|{model_rule}---|---|---|---|---|---|---|---|---|---|---|")

    def flag(v: Any) -> str:
        return "—" if v is None else ("yes" if v else "no")

    def pct(v: Any) -> str:
        return "—" if v is None else f"{v:.2f}"

    def money(v: Any) -> str:
        return "—" if not v else f"${v:.2f}"

    for row in sorted(rows, key=lambda r: str(r["case"])):
        model_cell = (
            f"{(row.get('model') or '—').replace('claude-', '')} | "
            if multi_model
            else ""
        )
        lines.append(
            f"| `{row['case']}` | {model_cell}{row['reached'] or '—'} "
            f"| {flag(row['validated'])} "
            f"| {flag(row['mesh_pass'])} | {flag(row['converged'])} "
            f"| {pct(row['decision_coverage'])} | {pct(row['citation_resolution'])} "
            f"| {pct(row['narration_precision'])} | {pct(row['contradiction_rate'])} "
            f"| {pct(row['narration_recall'])} "
            f"| {row['turns'] or '—'} | "
            f"{money(row['cost_equiv'])} |"
        )

    reached = summary["reached"]
    lines += [
        "",
        f"{summary['n_runs']} run(s) over {summary['n_cases']} case(s), "
        f"{summary['n_complete']} complete. Furthest phase reached: "
        + ", ".join(f"{k} {v}" for k, v in reached.items() if v),
        "",
        "> Rates below are taken over runs that reached the phase in question. "
        "A run that stopped after authoring never had the chance to validate, "
        "and counting it as a validation failure would report an early stop as "
        "a benchmark result.",
        "",
    ]
    for name in ("mesh_pass", "converged", "validated"):
        ci = summary[name]
        if not ci:
            lines.append(f"- **{name}**: not measured — no run reached it")
            continue
        line = (
            f"- **{name}**: {ci['point']:.3f} "
            f"[{ci['low']:.2f}, {ci['high']:.2f}] over n={ci['n']}"
        )
        # Repeats of one case are not independent observations of the
        # benchmark, so where the matrix carries them the interval widened
        # for that clustering is the one to read.
        adj = summary.get(f"{name}_clustered")
        if adj and adj.get("design_effect", 1.0) > 1.0:
            a = adj["adjusted"]
            line += (
                f" (clustered by case: {a.point:.2f} "
                f"[{a.low:.2f}, {a.high:.2f}], eff n={a.n})"
            )
        lines.append(line)
    if summary["median_cost_equiv"] is not None:
        lines += [
            "",
            f"Median cost equivalent ${summary['median_cost_equiv']:.2f}, "
            f"median {summary['median_turns']} turns. On a subscription nothing "
            "is charged per run; this is what the same tokens would have cost "
            "through the API.",
        ]
    return "\n".join(lines) + "\n"


def render_ablations_markdown(report: dict[str, Any]) -> str:
    """Each ablation against the ordinary arm, case by case."""
    lines = ["# Ablations", ""]
    for name, arm in report["arms"].items():
        lines += [
            f"## `{name}` — that server withheld",
            "",
            "| Case | Model | n | Validated | Citations resolved "
            "| Decision coverage | Cost eq. |",
            "|---|---|---|---|---|---|---|",
        ]

        def cell(a: Any, b: Any, money: bool = False) -> str:
            def one(v: Any) -> str:
                if v is None:
                    return "—"
                return f"${v:.2f}" if money else f"{v:.2f}"

            return f"{one(a)} → {one(b)}"

        for c in arm["cases"]:
            lines.append(
                f"| `{c['case']}` | {c['model'].replace('claude-', '')} "
                f"| {c['n_ordinary']} → {c['n_ablated']} "
                f"| {cell(c['validated_ordinary'], c['validated_ablated'])} "
                f"| {cell(c['citations_ordinary'], c['citations_ablated'])} "
                f"| {cell(c['coverage_ordinary'], c['coverage_ablated'])} "
                f"| {cell(c['cost_ordinary'], c['cost_ablated'], money=True)} |"
            )
        lines += [
            "",
            "> Each cell reads ordinary → ablated, paired on case and model "
            "because the arms are only comparable where the same case was "
            "attempted both ways by the same model. At these sample sizes a "
            "difference is a direction, not a result.",
            "",
        ]
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    """A table a reader can check rather than a leaderboard."""
    lines = ["# Detection arms", ""]
    lines.append(
        "| Arm | Recall | False alarms | Youden J | Localisation | Answered |"
    )
    lines.append("|---|---|---|---|---|---|")

    def fmt(ci: dict[str, Any] | None) -> str:
        if not ci:
            return "—"
        return f"{ci['point']:.3f} [{ci['low']:.2f}, {ci['high']:.2f}] n={ci['n']}"

    # Ordered by Youden's J, not recall: recall alone rewards flagging
    # everything, and a sort key that rewards it would too.
    for summary in sorted(
        report["arms"],
        key=lambda s: (s["youden_j"] is None, -(s["youden_j"] or 0)),
    ):
        clustered = summary.get("recall_clustered")
        cluster_note = (
            f" (clustered: {clustered['point']:.2f} "
            f"[{clustered['low']:.2f}, {clustered['high']:.2f}], "
            f"eff n={clustered['effective_n']})"
            if clustered and clustered["design_effect"] > 1.05
            else ""
        )
        lines.append(
            f"| `{summary['arm']}` | {fmt(summary['recall'])}{cluster_note} | "
            f"{fmt(summary['false_alarm_rate'])} | "
            f"{summary['youden_j'] if summary['youden_j'] is not None else '—'} | "
            f"{fmt(summary['localisation_rate'])} | "
            f"{summary['n_attempted'] - summary['unparseable']}"
            f"/{summary['n_attempted']} |"
        )

    silent = [s for s in report["arms"] if not s["scoreable"]]
    if silent:
        lines += [
            "",
            "> Not scored: "
            + ", ".join(f"`{s['arm']}`" for s in silent)
            + " — no probe returned a usable verdict, so these arms have no "
            "measured recall. An unreachable endpoint and a model that "
            "ignores the output format both land here, and neither is a "
            "detection result.",
        ]

    paired = report.get("paired_against_tool", {})
    if paired.get("comparisons"):
        lines += [
            "",
            "## Against the tool arm (paired, Holm-corrected)",
            "",
            "| Arm | Recall Δ | Effect h | P(tool better) | Discordant | p | Holm sig. | κ |",
            "|---|---|---|---|---|---|---|---|",
        ]
        holm = paired["multiplicity"]["results"]
        for name, c in sorted(
            paired["comparisons"].items(), key=lambda kv: -kv[1]["difference"]
        ):
            sig = holm.get(name, {}).get("significant")
            lines.append(
                f"| `{name}` | {c['difference']:+.3f} | {c['effect_size_h']:.2f} | "
                f"{c['p_baseline_better']:.2f} | "
                f"{c['discordant']} | {c['p_value']:.4f} | "
                f"{'yes' if sig else 'no'} | {c['kappa_vs_baseline']:+.2f} |"
            )

    v = report.get("variance", {})
    if v.get("n"):
        lines += ["", "## Where the spread comes from", ""]
        if v.get("case_share") is None:
            # Zero total variance: every arm scored every fault class the
            # same. There is nothing to decompose, and printing 0% for each
            # component would imply a measurement that was never made.
            lines.append(
                "- no variation to attribute — all arms scored every fault "
                "class identically"
            )
        else:
            lines += [
                f"- fault class: **{v['case_share']:.0%}**",
                f"- arm: **{v['model_share']:.0%}**",
                f"- residual: **{v['residual_share']:.0%}**",
            ]
        if v.get("dominated_by_case_choice"):
            lines += [
                "",
                "> Spread is dominated by which faults are in the corpus rather "
                "than by which arm judged them. Read the arm ordering as "
                "provisional until the corpus is broader.",
            ]
    return "\n".join(lines) + "\n"


def build_report(probes_dir: Path) -> dict[str, Any]:
    arms = load_probe_results(probes_dir)
    return {
        "n_arms": len(arms),
        "arms": [arm_summary(name, data) for name, data in arms.items()],
        "paired_against_tool": paired_against_tool(arms),
        "variance": variance_by_fault_class(arms),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probes", type=Path, help="Directory of probe JSONs")
    ap.add_argument("--runs", type=Path, help="Directory of scored run records")
    ap.add_argument("-o", "--output", type=Path, help="Write the markdown here")
    ap.add_argument("--json", type=Path, help="Write the structured report here")
    args = ap.parse_args(argv)

    if not args.probes and not args.runs:
        ap.error("pass --probes, --runs, or both")

    sections: list[str] = []
    report: dict[str, Any] = {}
    if args.probes:
        report = build_report(args.probes)
        sections.append(render_markdown(report))
    if args.runs:
        rows = run_table(load_run_records(args.runs))
        # Headline rates describe the tool as shipped, so they are taken over
        # the ordinary arm; the ablations are reported as their own comparison.
        ordinary, _arms = split_arms(rows)
        summary = capability_summary(ordinary)
        report["runs"] = {"rows": rows, "summary": summary}
        sections.append(render_runs_markdown(rows, summary))
        ablations = ablation_comparison(rows)
        if ablations["arms"]:
            report["ablations"] = ablations
            sections.append(render_ablations_markdown(ablations))
    markdown = "\n\n".join(sections)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
