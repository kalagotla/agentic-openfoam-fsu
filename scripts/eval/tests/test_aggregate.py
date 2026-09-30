"""Tests for aggregation.

Aggregation is where a benchmark usually starts lying — a sorted column of
single numbers with no interval, no multiplicity correction, and no hint
that the spread comes from the cases rather than the arms. These tests pin
the refusals that stop that happening.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aggregate import (
    arm_summary,
    build_report,
    load_probe_results,
    paired_against_tool,
    render_markdown,
    variance_by_fault_class,
)


def outcome(
    probe_id: str,
    fault: bool,
    detected: bool,
    *,
    localised: bool = False,
    tool_detectable: bool = True,
    fault_class: str = "mesh",
    detail: str = "ok",
) -> dict:
    return {
        "probe_id": probe_id,
        "fault_class": fault_class if fault else "none",
        "fault_present": fault,
        "expected_detector": "assess_mesh_quality",
        "tool_detectable": tool_detectable,
        "detected": detected,
        "localised": localised,
        "detail": detail,
    }


def arm(*outcomes: dict) -> dict:
    return {"arm": "test", "outcomes": list(outcomes)}


# ---------------------------------------------------------------------------
# One arm
# ---------------------------------------------------------------------------


def test_rates_carry_intervals() -> None:
    s = arm_summary("x", arm(outcome("a", True, True), outcome("b", False, False)))
    assert s["recall"]["low"] < s["recall"]["point"]
    assert s["false_alarm_rate"] is not None


def test_youden_j_is_zero_for_an_assessor_that_flags_everything() -> None:
    s = arm_summary(
        "yes-to-all",
        arm(
            outcome("a", True, True),
            outcome("b", True, True),
            outcome("c", False, True),
            outcome("d", False, True),
        ),
    )
    # Perfect recall, and worthless. A summary number has to say so.
    assert s["recall"]["point"] == 1.0
    assert s["youden_j"] == 0.0


def test_youden_j_rewards_discrimination() -> None:
    s = arm_summary(
        "good",
        arm(
            outcome("a", True, True),
            outcome("b", True, True),
            outcome("c", False, False),
            outcome("d", False, False),
        ),
    )
    assert s["youden_j"] == 1.0


def test_the_two_shares_of_detection_are_reported_apart() -> None:
    s = arm_summary(
        "x",
        arm(
            outcome("tool-catchable", True, True, tool_detectable=True),
            outcome("judgement", True, False, tool_detectable=False),
        ),
    )
    # Engineering-attributable and model-attributable recall move for
    # different reasons and are never averaged together.
    assert s["tool_share_recall"]["point"] == 1.0
    assert s["reasoning_share_recall"]["point"] == 0.0


def test_probes_an_arm_did_not_run_are_excluded() -> None:
    s = arm_summary(
        "x",
        arm(
            outcome("a", True, True),
            outcome("skipped", True, False, detail="not run in this arm"),
        ),
    )
    # A probe never put to the arm must not depress its recall.
    assert s["recall"]["n"] == 1


def test_unparseable_replies_are_surfaced() -> None:
    s = arm_summary(
        "x", arm(outcome("a", True, False, detail="model: none | UNPARSEABLE"))
    )
    # A model that cannot answer in the required form is failing in a
    # specific way worth separating from a model that answered wrongly.
    assert s["unparseable"] == 1


# ---------------------------------------------------------------------------
# Paired comparison
# ---------------------------------------------------------------------------


def two_arms() -> dict[str, dict]:
    tool = arm(*[outcome(f"p{i}", True, True) for i in range(9)])
    weak = arm(*[outcome(f"p{i}", True, i < 3) for i in range(9)])
    return {"tool": tool, "weak-model": weak}


def test_comparisons_are_paired_on_probe_id() -> None:
    result = paired_against_tool(two_arms())
    c = result["comparisons"]["weak-model"]
    assert c["n_paired"] == 9
    assert c["difference"] == pytest.approx(3 / 9 - 1.0, abs=1e-4)
    assert c["only_baseline_caught"] == 6


def test_differences_carry_an_effect_size() -> None:
    c = paired_against_tool(two_arms())["comparisons"]["weak-model"]
    # A p-value says a gap is unlikely to be chance; it says nothing about
    # whether the gap matters.
    assert c["effect_size_h"] > 0.8


def test_the_family_of_comparisons_is_holm_corrected() -> None:
    arms = two_arms()
    arms["also-weak"] = arm(*[outcome(f"p{i}", True, i < 4) for i in range(9)])
    result = paired_against_tool(arms)
    assert result["multiplicity"]["n_tests"] == 2
    for name in ("weak-model", "also-weak"):
        assert name in result["multiplicity"]["results"]


def test_a_missing_baseline_is_reported_not_assumed() -> None:
    result = paired_against_tool({"only-a-model": arm(outcome("a", True, True))})
    assert result["available"] is False


def test_agreement_is_measured_over_clean_probes_too() -> None:
    # Two arms can match on recall and still disagree about which specific
    # artefacts are faulty.
    tool = arm(outcome("a", True, True), outcome("b", False, False))
    other = arm(outcome("a", True, True), outcome("b", False, True))
    c = paired_against_tool({"tool": tool, "other": other})["comparisons"]["other"]
    assert c["kappa_vs_baseline"] < 1.0


# ---------------------------------------------------------------------------
# Variance
# ---------------------------------------------------------------------------


def test_variance_flags_a_corpus_driven_table() -> None:
    easy = [outcome(f"m{i}", True, True, fault_class="mesh") for i in range(3)]
    hard = [outcome(f"n{i}", True, False, fault_class="numerics") for i in range(3)]
    arms = {"a": arm(*easy, *hard), "b": arm(*easy, *hard)}
    v = variance_by_fault_class(arms)
    # Both arms behave identically; all the spread is which faults were
    # chosen. A leaderboard here would be reporting the corpus.
    assert v["dominated_by_case_choice"] is True


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_markdown_orders_by_discrimination_not_recall(tmp_path: Path) -> None:
    (tmp_path / "tool.json").write_text(
        json.dumps(arm(outcome("a", True, True), outcome("b", False, False)))
    )
    (tmp_path / "flagger.json").write_text(
        json.dumps(arm(outcome("a", True, True), outcome("b", False, True)))
    )
    report = build_report(tmp_path)
    text = render_markdown(report)
    # Sorting by recall would put the flag-everything arm first.
    assert text.index("`tool`") < text.index("`flagger`")


def test_every_rendered_rate_shows_its_interval(tmp_path: Path) -> None:
    (tmp_path / "tool.json").write_text(json.dumps(arm(outcome("a", True, True))))
    text = render_markdown(build_report(tmp_path))
    assert "[0." in text and "n=1" in text


def test_files_that_are_not_probe_results_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "tool.json").write_text(json.dumps(arm(outcome("a", True, True))))
    (tmp_path / "notes.json").write_text(json.dumps({"something": "else"}))
    assert set(load_probe_results(tmp_path)) == {"tool"}


def test_unreadable_files_do_not_stop_aggregation(tmp_path: Path) -> None:
    (tmp_path / "tool.json").write_text(json.dumps(arm(outcome("a", True, True))))
    (tmp_path / "broken.json").write_text("{ not json")
    assert set(load_probe_results(tmp_path)) == {"tool"}


# ---------------------------------------------------------------------------
# An arm that did not answer has no score
# ---------------------------------------------------------------------------


def unanswered(probe_id: str, fault: bool) -> dict:
    return outcome(
        probe_id, fault, False, detail="model: None | ConnectionError | UNPARSEABLE"
    )


def test_an_arm_that_never_answered_is_not_scored_as_zero() -> None:
    s = arm_summary(
        "unreachable",
        arm(unanswered("a", True), unanswered("b", True), unanswered("c", False)),
    )
    # An unreachable endpoint and a model that never notices anything would
    # otherwise share a score of 0.000 recall, which are entirely different
    # facts.
    assert s["scoreable"] is False
    assert s["recall"] is None
    assert s["answer_rate"] == 0.0


def test_scores_rest_only_on_answered_probes() -> None:
    s = arm_summary(
        "partial",
        arm(
            outcome("a", True, True),
            outcome("b", True, True),
            unanswered("c", True),
            unanswered("d", True),
        ),
    )
    # Two of four answered, both caught. Counting the silences as misses
    # would report 0.5 for an arm that never got 0.5 wrong.
    assert s["recall"]["point"] == 1.0
    assert s["recall"]["n"] == 2
    assert s["answer_rate"] == 0.5


def test_the_answer_rate_is_shown_so_the_denominator_is_visible() -> None:
    s = arm_summary("partial", arm(outcome("a", True, True), unanswered("b", True)))
    assert s["n_attempted"] == 2
    assert s["unparseable"] == 1


def test_unscoreable_arms_are_called_out_in_the_table(tmp_path: Path) -> None:
    (tmp_path / "tool.json").write_text(json.dumps(arm(outcome("a", True, True))))
    (tmp_path / "silent.json").write_text(json.dumps(arm(unanswered("a", True))))
    text = render_markdown(build_report(tmp_path))
    assert "Not scored" in text
    assert "`silent`" in text


def test_paired_comparison_skips_probes_an_arm_did_not_answer() -> None:
    tool = arm(outcome("a", True, True), outcome("b", True, True))
    partial = arm(outcome("a", True, False), unanswered("b", True))
    c = paired_against_tool({"tool": tool, "partial": partial})["comparisons"]["partial"]
    # Only probe "a" was judged by both, so only it can be paired.
    assert c["n_paired"] == 1


# ---------------------------------------------------------------------------
# Run-level aggregation
# ---------------------------------------------------------------------------


def a_record(
    key: str,
    *,
    reached: str = "validated",
    validated: bool | None = True,
    mesh: bool | None = True,
    converged: bool | None = True,
    coverage: float | None = 1.0,
    complete: bool = True,
    turns: int | None = 40,
    cost: float | None = 1.0,
) -> dict:
    return {
        "run": {
            "case_name": "case",
            "phase_reached": reached,
            "cost": {"iterations": turns, "cost_usd_equivalent": cost},
        },
        "suite": {"key": key},
        "capability": {
            "validated": validated,
            "mesh_pass": mesh,
            "converged": converged,
            "n_retries": 0,
        },
        "trust": {
            "decision_coverage": {
                "decision_coverage": coverage,
                "complete_run": complete,
            },
            "citations": {"citation_resolution_rate": 0.9},
        },
    }


def test_rows_are_named_by_the_benchmark_case() -> None:
    from aggregate import run_table

    rows = run_table([a_record("pitz-daily"), a_record("naca-0012")])
    # Every run's artefacts land in a directory called "case", so the
    # directory name identifies nothing.
    assert {r["case"] for r in rows} == {"pitz-daily", "naca-0012"}


def test_rates_exclude_runs_that_never_reached_the_phase() -> None:
    from aggregate import capability_summary, run_table

    rows = run_table(
        [
            a_record("a"),
            a_record(
                "b",
                reached="authored",
                validated=None,
                mesh=None,
                converged=None,
                complete=False,
            ),
        ]
    )
    summary = capability_summary(rows)
    # One run validated, one stopped before it could. Counting the early
    # stop as a validation failure would report a stop as a benchmark result.
    assert summary["validated"]["n"] == 1
    assert summary["validated"]["point"] == 1.0
    assert summary["n_complete"] == 1


def test_a_phase_no_run_reached_is_not_measured() -> None:
    from aggregate import capability_summary, run_table

    rows = run_table(
        [a_record("a", reached="authored", validated=None, mesh=None, converged=None)]
    )
    summary = capability_summary(rows)
    assert summary["validated"] is None


def test_the_reached_histogram_shows_where_runs_stopped() -> None:
    from aggregate import capability_summary, run_table

    rows = run_table(
        [
            a_record("a"),
            a_record("b", reached="authored", validated=None),
            a_record("c", reached="authored", validated=None),
        ]
    )
    reached = capability_summary(rows)["reached"]
    assert reached["authored"] == 2
    assert reached["validated"] == 1


def test_cost_is_reported_as_a_median_not_a_mean() -> None:
    from aggregate import capability_summary, run_table

    rows = run_table(
        [a_record("a", cost=1.0), a_record("b", cost=1.0), a_record("c", cost=50.0)]
    )
    # One heavy 3-D case should not set the headline cost for a suite of
    # light ones.
    assert capability_summary(rows)["median_cost_equiv"] == 1.0


def test_run_records_are_loaded_from_a_results_tree(tmp_path: Path) -> None:
    from aggregate import load_run_records

    for key in ("a", "b"):
        d = tmp_path / f"{key}__model__seeded__r1"
        d.mkdir()
        (d / "record.json").write_text(json.dumps(a_record(key)))
    (tmp_path / "empty").mkdir()
    assert len(load_run_records(tmp_path)) == 2


# ---------------------------------------------------------------------------
# Clustering and posteriors in the table
# ---------------------------------------------------------------------------


def test_clustered_recall_is_reported_when_outcomes_cluster() -> None:
    # Two fault classes answered as blocks: far less evidence than six
    # independent probes.
    s = arm_summary(
        "blocky",
        arm(
            *[outcome(f"m{i}", True, True, fault_class="mesh") for i in range(3)],
            *[outcome(f"n{i}", True, False, fault_class="numerics") for i in range(3)],
        ),
    )
    clustered = s["recall_clustered"]
    assert clustered is not None
    assert clustered["effective_n"] < 6
    assert clustered["design_effect"] > 1.0


def test_evenly_split_classes_carry_their_full_weight() -> None:
    s = arm_summary(
        "even",
        arm(
            outcome("m1", True, True, fault_class="mesh"),
            outcome("m2", True, False, fault_class="mesh"),
            outcome("n1", True, True, fault_class="numerics"),
            outcome("n2", True, False, fault_class="numerics"),
        ),
    )
    # Cluster membership predicts nothing, so nothing is discounted.
    assert s["recall_clustered"]["design_effect"] == pytest.approx(1.0, abs=0.3)


def test_the_paired_table_carries_a_posterior_beside_the_p_value() -> None:
    tool = arm(*[outcome(f"p{i}", True, True) for i in range(9)])
    weak = arm(*[outcome(f"p{i}", True, i < 5) for i in range(9)])
    c = paired_against_tool({"tool": tool, "weak": weak})["comparisons"]["weak"]
    # A corrected p-value at this size mostly reports that the corpus is
    # small; the posterior answers the question a reader actually has.
    assert 0.5 < c["p_baseline_better"] <= 1.0
    assert "p_value" in c


def test_the_posterior_is_near_even_for_matched_arms() -> None:
    tool = arm(*[outcome(f"p{i}", True, i < 5) for i in range(10)])
    same = arm(*[outcome(f"p{i}", True, i < 5) for i in range(10)])
    c = paired_against_tool({"tool": tool, "same": same})["comparisons"]["same"]
    assert c["p_baseline_better"] == pytest.approx(0.5, abs=0.08)


def test_repeats_of_one_case_do_not_buy_confidence() -> None:
    from aggregate import capability_summary

    """Four seeds of one case are not four points on the benchmark.

    A plain interval over them claims precision the design does not have,
    and the more the repeats agree the worse the overstatement — perfect
    agreement within a case carries no information about the next case.
    """
    rows = [
        {"case": "lid-cavity", "validated": True, "reached": "validated"}
        for _ in range(4)
    ] + [
        {"case": "pitz-daily", "validated": False, "reached": "validated"}
        for _ in range(4)
    ]
    summary = capability_summary(rows)
    naive = summary["validated"]
    clustered = summary["validated_clustered"]["adjusted"]

    assert naive["n"] == 8
    assert clustered.n < naive["n"]
    assert (clustered.high - clustered.low) > (naive["high"] - naive["low"])


def test_a_single_case_has_nothing_to_cluster() -> None:
    from aggregate import capability_summary

    # One cluster carries no between-case information, so there is no
    # adjustment to make and none is claimed.
    rows = [
        {"case": "lid-cavity", "validated": True, "reached": "validated"}
        for _ in range(4)
    ]
    assert capability_summary(rows)["validated_clustered"] is None


def test_the_case_count_is_reported_beside_the_run_count() -> None:
    from aggregate import capability_summary

    rows = [
        {"case": "lid-cavity", "validated": True, "reached": "validated"},
        {"case": "lid-cavity", "validated": True, "reached": "validated"},
        {"case": "pitz-daily", "validated": False, "reached": "validated"},
    ]
    summary = capability_summary(rows)
    assert summary["n_runs"] == 3
    assert summary["n_cases"] == 2


def test_an_ablated_run_stays_out_of_the_headline_rate() -> None:
    """Pooling the arms would answer the wrong question.

    "How well does the tool do" cannot be measured partly with runs where
    part of the tool was absent.
    """
    from aggregate import capability_summary, split_arms

    rows = [
        {"case": "lid-cavity", "validated": True, "ablated": ()},
        {"case": "lid-cavity", "validated": True, "ablated": ()},
        {"case": "lid-cavity", "validated": False, "ablated": ("consultant",)},
    ]
    ordinary, arms = split_arms(rows)
    assert len(ordinary) == 2
    assert set(arms) == {"no-consultant"}
    assert capability_summary(ordinary)["validated"]["point"] == 1.0


def test_the_ablation_is_paired_on_case() -> None:
    # A case only one arm ran is not a comparison, so it is left out rather
    # than compared against nothing.
    from aggregate import ablation_comparison

    rows = [
        {"case": "lid-cavity", "model": "sonnet", "validated": True,
         "citation_resolution": 1.0, "decision_coverage": 1.0,
         "cost_equiv": 2.0, "ablated": ()},
        {"case": "lid-cavity", "model": "sonnet", "validated": False,
         "citation_resolution": 0.5, "decision_coverage": 0.8,
         "cost_equiv": 3.0, "ablated": ("consultant",)},
        {"case": "flat-plate", "model": "sonnet", "validated": True,
         "citation_resolution": 0.9, "decision_coverage": 1.0,
         "cost_equiv": 4.0, "ablated": ()},
    ]
    arm = ablation_comparison(rows)["arms"]["no-consultant"]
    assert arm["n_cases"] == 1
    case = arm["cases"][0]
    assert case["case"] == "lid-cavity"
    assert case["validated_ordinary"] == 1.0
    assert case["validated_ablated"] == 0.0
    assert case["citations_ablated"] == 0.5


def test_the_ablation_does_not_compare_across_models() -> None:
    """Pairing on case alone let a model difference read as an ablation.

    The ordinary arm holds two models and the ablated arm one, so a cost
    column paired on case compared an average that included the expensive
    model against one that did not, and attributed the gap to the missing
    server.
    """
    from aggregate import ablation_comparison

    rows = [
        {"case": "pitz-daily", "model": "opus", "validated": True,
         "cost_equiv": 20.0, "ablated": ()},
        {"case": "pitz-daily", "model": "sonnet", "validated": True,
         "cost_equiv": 2.0, "ablated": ()},
        {"case": "pitz-daily", "model": "sonnet", "validated": True,
         "cost_equiv": 2.1, "ablated": ("consultant",)},
    ]
    cases = ablation_comparison(rows)["arms"]["no-consultant"]["cases"]
    assert len(cases) == 1
    # Only the sonnet pair is compared; the opus run has no ablated partner.
    assert cases[0]["model"] == "sonnet"
    assert cases[0]["cost_ordinary"] == 2.0
    assert cases[0]["cost_ablated"] == 2.1


def test_no_ablation_produces_no_ablation_section() -> None:
    from aggregate import ablation_comparison

    rows = [{"case": "lid-cavity", "validated": True, "ablated": ()}]
    assert ablation_comparison(rows)["arms"] == {}
