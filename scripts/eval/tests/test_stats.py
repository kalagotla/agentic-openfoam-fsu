"""Tests for the statistics helpers.

Each is checked against a property that holds independently of the
implementation — symmetry, containment, monotonicity, or a hand-computable
case — rather than against a number this code produced.
"""

from __future__ import annotations

import pytest
from stats import (
    _beta_cdf,
    beta_posterior,
    bootstrap_diff,
    calibration,
    cluster_adjusted_wilson,
    cohens_h,
    cohens_kappa,
    detectable_difference,
    holm_bonferroni,
    mcnemar,
    probability_better,
    required_n,
    variance_components,
    wilson,
)

# ---------------------------------------------------------------------------
# Wilson interval
# ---------------------------------------------------------------------------


def test_interval_contains_the_point_estimate() -> None:
    ci = wilson(8, 10)
    assert ci is not None
    assert ci.low <= ci.point <= ci.high
    assert ci.point == 0.8


def test_more_observations_narrow_the_interval() -> None:
    small = wilson(8, 10)
    large = wilson(80, 100)
    assert small is not None and large is not None
    # Same rate, different evidence — the whole reason a bare percentage is
    # not enough.
    assert small.point == large.point
    assert (large.high - large.low) < (small.high - small.low)


def test_a_perfect_score_still_has_an_interval() -> None:
    ci = wilson(10, 10)
    assert ci is not None
    assert ci.point == 1.0
    # 10 for 10 is not proof of perfection.
    assert ci.low < 1.0
    assert ci.high == pytest.approx(1.0)


def test_zero_successes_stay_inside_the_unit_interval() -> None:
    ci = wilson(0, 20)
    assert ci is not None
    assert ci.low == 0.0
    assert 0.0 < ci.high < 1.0


def test_no_observations_is_absent_not_zero() -> None:
    # Reporting 0.0 here would read as a measured failure rate.
    assert wilson(0, 0) is None


def test_impossible_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        wilson(11, 10)


# ---------------------------------------------------------------------------
# McNemar
# ---------------------------------------------------------------------------


def test_identical_arms_are_indistinguishable() -> None:
    a = [True, False, True, True]
    result = mcnemar(a, list(a))
    assert result.discordant == 0
    assert result.p_value == 1.0


def test_only_discordant_pairs_count() -> None:
    # Two arms agreeing on eight items and differing on two: the agreements
    # carry no information about which arm is better.
    a = [True] * 8 + [True, False]
    b = [True] * 8 + [False, True]
    result = mcnemar(a, b)
    assert result.n_pairs == 10
    assert result.discordant == 2
    assert result.only_a == 1 and result.only_b == 1
    assert result.p_value == 1.0


def test_a_one_sided_sweep_is_significant() -> None:
    # Arm A catches ten faults arm B misses, and never the reverse.
    a = [True] * 10
    b = [False] * 10
    result = mcnemar(a, b)
    assert result.only_a == 10 and result.only_b == 0
    assert result.p_value < 0.01


def test_a_small_sweep_is_not_significant() -> None:
    a = [True, True, True]
    b = [False, False, False]
    # Three for three is suggestive, not conclusive — and the test says so.
    assert mcnemar(a, b).p_value > 0.05


def test_swapping_the_arms_preserves_the_p_value() -> None:
    a = [True, True, False, True, False]
    b = [False, True, False, False, False]
    assert mcnemar(a, b).p_value == pytest.approx(mcnemar(b, a).p_value)


def test_mismatched_arm_lengths_are_rejected() -> None:
    with pytest.raises(ValueError):
        mcnemar([True], [True, False])


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_brackets_a_real_difference() -> None:
    a = [1.0, 1.2, 0.9, 1.1, 1.0]
    b = [0.5, 0.6, 0.4, 0.5, 0.5]
    ci = bootstrap_diff(a, b, n_resamples=2000)
    assert ci.point == pytest.approx(0.54, abs=0.02)
    assert ci.low > 0.0  # the difference excludes zero


def test_bootstrap_on_noise_includes_zero() -> None:
    a = [1.0, -1.0, 0.5, -0.5, 0.0]
    b = [0.9, -1.1, 0.6, -0.4, 0.1]
    ci = bootstrap_diff(a, b, n_resamples=2000)
    assert ci.low <= 0.0 <= ci.high


def test_bootstrap_is_reproducible() -> None:
    a, b = [1.0, 2.0, 3.0], [0.5, 1.5, 2.0]
    first = bootstrap_diff(a, b, n_resamples=500)
    second = bootstrap_diff(a, b, n_resamples=500)
    # A reported interval has to be the same interval next time it is read.
    assert (first.low, first.high) == (second.low, second.high)


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------


def test_more_samples_detect_smaller_differences() -> None:
    assert detectable_difference(30, 0.5) > detectable_difference(120, 0.5)


def test_detectable_difference_is_a_sane_magnitude() -> None:
    # Around 120 paired probes the plan claims a ~0.12 detectable
    # difference; the helper should land in that neighbourhood rather than
    # implying far more sensitivity than the design has.
    assert 0.08 < detectable_difference(120, 0.5) < 0.20


# ---------------------------------------------------------------------------
# Multiplicity
# ---------------------------------------------------------------------------


def test_holm_is_stricter_than_uncorrected_alpha() -> None:
    # Three tests that would all pass at 0.05 uncorrected.
    corrected = holm_bonferroni({"a": 0.01, "b": 0.03, "c": 0.04})
    significant = [k for k, v in corrected["results"].items() if v["significant"]]
    assert significant == ["a"]


def test_holm_stops_at_the_first_failure() -> None:
    # Once a hypothesis survives, nothing weaker than it can be rejected —
    # that step-down property is what separates Holm from Bonferroni.
    corrected = holm_bonferroni({"a": 0.001, "b": 0.9, "c": 0.002})
    results = corrected["results"]
    assert results["a"]["significant"] is True
    assert results["c"]["significant"] is True
    assert results["b"]["significant"] is False


def test_holm_is_more_powerful_than_bonferroni() -> None:
    # Bonferroni would need p <= 0.05/3 = 0.0167 for every test; Holm's
    # largest threshold is 0.05 for the weakest surviving hypothesis.
    corrected = holm_bonferroni({"a": 0.001, "b": 0.002, "c": 0.003})
    assert all(v["significant"] for v in corrected["results"].values())
    assert max(v["threshold"] for v in corrected["results"].values()) == pytest.approx(0.05)


def test_a_single_test_is_uncorrected() -> None:
    corrected = holm_bonferroni({"only": 0.04})
    assert corrected["results"]["only"]["threshold"] == pytest.approx(0.05)


def test_no_tests_is_not_an_error() -> None:
    assert holm_bonferroni({})["n_tests"] == 0


# ---------------------------------------------------------------------------
# Effect size
# ---------------------------------------------------------------------------


def test_identical_proportions_have_no_effect() -> None:
    assert cohens_h(0.5, 0.5) == pytest.approx(0.0)


def test_the_same_gap_matters_more_near_the_extremes() -> None:
    middle = cohens_h(0.45, 0.50)
    edge = cohens_h(0.90, 0.95)
    # Five points is not five points: a raw difference hides that moving
    # from 0.90 to 0.95 halves the failure rate.
    assert edge > middle


def test_effect_size_is_symmetric() -> None:
    assert cohens_h(0.2, 0.6) == pytest.approx(cohens_h(0.6, 0.2))


def test_impossible_proportions_are_rejected() -> None:
    with pytest.raises(ValueError):
        cohens_h(0.5, 1.4)


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------


def test_perfect_agreement_gives_kappa_one() -> None:
    judgements = [True, False, True, True, False]
    assert cohens_kappa(judgements, list(judgements)).kappa == pytest.approx(1.0)


def test_agreement_by_chance_alone_gives_kappa_near_zero() -> None:
    # Two judges that both say "no" to almost everything agree on 90% of
    # items while sharing no actual judgement. Raw agreement would call
    # that excellent.
    a = [False] * 9 + [True]
    b = [False] * 8 + [True, False]
    result = cohens_kappa(a, b)
    assert result.observed >= 0.8
    assert result.kappa < 0.5


def test_systematic_disagreement_gives_negative_kappa() -> None:
    a = [True, True, False, False]
    b = [False, False, True, True]
    assert cohens_kappa(a, b).kappa < 0.0


def test_kappa_requires_matched_judges() -> None:
    with pytest.raises(ValueError):
        cohens_kappa([True], [True, False])


# ---------------------------------------------------------------------------
# Variance components
# ---------------------------------------------------------------------------


def test_variance_dominated_by_case_choice_is_flagged() -> None:
    # Every model does well on one case and badly on the other. A
    # leaderboard here reports which cases were chosen, not which model is
    # better.
    obs = [
        ("easy", "m1", 1.0), ("easy", "m2", 0.95), ("easy", "m3", 0.9),
        ("hard", "m1", 0.2), ("hard", "m2", 0.15), ("hard", "m3", 0.1),
    ]
    result = variance_components(obs)
    assert result["dominated_by_case_choice"] is True
    assert result["case_share"] > result["model_share"]


def test_variance_dominated_by_the_model_is_not_flagged() -> None:
    obs = [
        ("a", "good", 0.95), ("b", "good", 0.9), ("c", "good", 0.92),
        ("a", "poor", 0.2), ("b", "poor", 0.15), ("c", "poor", 0.25),
    ]
    result = variance_components(obs)
    assert result["dominated_by_case_choice"] is False
    assert result["model_share"] > result["case_share"]


def test_variance_shares_are_reported_as_fractions() -> None:
    obs = [("a", "m", 0.1), ("b", "m", 0.9), ("a", "n", 0.2), ("b", "n", 0.8)]
    result = variance_components(obs)
    total = result["case_share"] + result["model_share"] + result["residual_share"]
    assert total == pytest.approx(1.0, abs=1e-9)


def test_no_observations_is_not_an_error() -> None:
    assert variance_components([])["n"] == 0


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def test_required_n_and_detectable_difference_are_inverses() -> None:
    n = required_n(0.5, 0.12)
    # Round-tripping should land close to the difference asked for.
    assert detectable_difference(n, 0.5) == pytest.approx(0.12, rel=0.05)


def test_smaller_differences_need_more_samples() -> None:
    assert required_n(0.5, 0.05) > required_n(0.5, 0.20)


def test_planning_rejects_impossible_targets() -> None:
    with pytest.raises(ValueError):
        required_n(0.5, 0.0)


# ---------------------------------------------------------------------------
# Posteriors
# ---------------------------------------------------------------------------


def test_incomplete_beta_matches_a_closed_form() -> None:
    # Beta(10, 1) integrates to x^10 exactly. A series expansion got this
    # wrong by 0.13 at the 2.5% quantile, which would have shipped
    # over-confident credible intervals.
    for x in (0.3, 0.6, 0.691, 0.9):
        assert _beta_cdf(10, 1, x) == pytest.approx(x**10, abs=1e-6)


def test_a_perfect_score_gets_a_conservative_posterior() -> None:
    p = beta_posterior(9, 9)
    # Laplace's rule: nine for nine is 0.91, not 1.0, and the interval
    # reaches well below — which is the point of reporting one.
    assert p.mean == pytest.approx(10 / 11, rel=1e-6)
    assert p.low < 0.75


def test_more_evidence_narrows_the_posterior() -> None:
    small = beta_posterior(8, 10)
    large = beta_posterior(80, 100)
    assert (large.high - large.low) < (small.high - small.low)


def test_no_observations_returns_the_prior() -> None:
    p = beta_posterior(0, 0)
    # Uniform prior: mean 0.5, and it does not pretend to know anything.
    assert p.mean == pytest.approx(0.5)
    assert p.low < 0.1 and p.high > 0.9


def test_probability_better_is_decisive_when_the_gap_is_large() -> None:
    assert probability_better(9, 9, 1, 10) > 0.98


def test_probability_better_is_near_a_coin_flip_for_equal_arms() -> None:
    assert probability_better(5, 10, 5, 10) == pytest.approx(0.5, abs=0.05)


def test_probability_better_is_complementary() -> None:
    forward = probability_better(7, 10, 4, 10)
    backward = probability_better(4, 10, 7, 10)
    # Ties have probability zero for continuous posteriors, so the two
    # directions should sum to one.
    assert forward + backward == pytest.approx(1.0, abs=0.03)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def test_clustering_widens_the_interval() -> None:
    # Three clusters that each answer as a block: far less information
    # than nine independent probes.
    result = cluster_adjusted_wilson([(3, 3), (3, 3), (0, 3)])
    assert result["design_effect"] > 1.0
    assert result["effective_n"] < 9
    naive, adjusted = result["naive"], result["adjusted"]
    assert (adjusted.high - adjusted.low) > (naive.high - naive.low)


def test_uncorrelated_clusters_barely_widen_anything() -> None:
    # Every cluster splits the same way, so cluster membership carries no
    # information and the effective sample size is close to the real one.
    result = cluster_adjusted_wilson([(2, 4), (2, 4), (2, 4)])
    assert result["design_effect"] == pytest.approx(1.0, abs=0.2)


def test_a_single_cluster_cannot_be_adjusted() -> None:
    result = cluster_adjusted_wilson([(5, 10)])
    # No between-cluster information exists, and the function says so by
    # leaving the interval alone rather than inventing an adjustment. The
    # return shape is unchanged so callers never branch on it.
    assert result["design_effect"] == 1.0
    assert result["effective_n"] == 10
    assert set(result) == {"naive", "adjusted", "design_effect", "icc", "effective_n"}


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def test_a_perfectly_calibrated_forecaster_scores_zero_error() -> None:
    # Says 1.0 and is right; says 0.0 and is wrong.
    predictions = [(1.0, True)] * 5 + [(0.0, False)] * 5
    c = calibration(predictions)
    assert c.brier == pytest.approx(0.0)
    assert c.expected_error == pytest.approx(0.0)


def test_confident_and_wrong_is_caught() -> None:
    # The failure mode that matters: high confidence, poor accuracy. Plain
    # accuracy would report 60% and say nothing about the overclaim.
    predictions = [(0.9, True)] * 6 + [(0.9, False)] * 4
    c = calibration(predictions)
    assert c.expected_error == pytest.approx(0.3, abs=0.01)
    assert c.max_error >= 0.29


def test_underconfidence_is_also_a_calibration_error() -> None:
    predictions = [(0.3, True)] * 9 + [(0.3, False)]
    assert calibration(predictions).expected_error > 0.5


def test_bins_report_their_own_population() -> None:
    c = calibration([(0.1, False), (0.9, True), (0.9, True)], n_bins=5)
    assert sum(b["n"] for b in c.bins) == 3
    assert all(b["n"] > 0 for b in c.bins)


def test_impossible_confidence_is_rejected() -> None:
    with pytest.raises(ValueError):
        calibration([(1.5, True)])


def test_calibration_needs_predictions() -> None:
    with pytest.raises(ValueError):
        calibration([])
