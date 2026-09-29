"""Statistics for reporting evaluation results.

Small and deliberately conservative. Three things every table in
`docs/evaluation-plan.md` needs:

- an interval on a proportion, because "8 of 10" and "80 of 100" are not
  the same finding and a bare percentage hides which one you have;
- a paired test, because the informative comparisons here (consultant on
  vs off, corpus seeded vs empty) run the same cases through both arms and
  an unpaired test throws that away;
- a bootstrap interval on a difference, for the continuous outcomes.

Wilson rather than the normal approximation because the rates being
measured sit near 0 and 1, exactly where the normal interval misbehaves
and can even run outside [0, 1].
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

# 1.959964 = the two-sided normal quantile at 95%. Spelled out rather than
# imported so this module needs nothing beyond the standard library.
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    """A point estimate with a confidence interval."""

    point: float
    low: float
    high: float
    n: int

    def __str__(self) -> str:
        return f"{self.point:.3f} [{self.low:.3f}, {self.high:.3f}] (n={self.n})"


def wilson(successes: int, n: int, z: float = Z_95) -> Interval | None:
    """Wilson score interval for a proportion.

    Returns None for n = 0: a rate over no observations is not zero, it is
    absent, and reporting 0.0 there would read as a finding.
    """
    if n <= 0:
        return None
    if successes < 0 or successes > n:
        raise ValueError(f"{successes} successes out of {n} trials")
    p = successes / n
    denom = 1.0 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return Interval(point=p, low=max(0.0, centre - half), high=min(1.0, centre + half), n=n)


@dataclass(frozen=True)
class McNemarResult:
    """Paired comparison of two binary arms over the same items."""

    n_pairs: int
    only_a: int          # a succeeded, b failed
    only_b: int          # b succeeded, a failed
    statistic: float
    p_value: float

    @property
    def discordant(self) -> int:
        return self.only_a + self.only_b


def mcnemar(a: list[bool], b: list[bool]) -> McNemarResult:
    """Exact McNemar test on paired binary outcomes.

    Only the discordant pairs carry information: items both arms got right,
    or both got wrong, say nothing about which arm is better. The exact
    binomial form is used rather than the chi-square approximation because
    the discordant counts here are small.
    """
    if len(a) != len(b):
        raise ValueError(f"paired arms must be the same length: {len(a)} vs {len(b)}")
    only_a = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    only_b = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    n_disc = only_a + only_b
    if n_disc == 0:
        # No discordant pairs: the arms are indistinguishable on this data.
        return McNemarResult(len(a), 0, 0, 0.0, 1.0)

    k = min(only_a, only_b)
    tail = sum(math.comb(n_disc, i) for i in range(k + 1)) / (2**n_disc)
    p = min(1.0, 2.0 * tail)
    statistic = (abs(only_a - only_b) - 1) ** 2 / n_disc if n_disc else 0.0
    return McNemarResult(len(a), only_a, only_b, statistic, p)


def bootstrap_diff(
    a: list[float],
    b: list[float],
    *,
    n_resamples: int = 10000,
    seed: int = 20260822,
    z: float = Z_95,
) -> Interval:
    """Bootstrap interval on the paired mean difference ``a - b``.

    Paired: the same case appears in both arms, so resampling is over
    cases, not over each arm independently. The seed is fixed so a reported
    interval is reproducible.
    """
    if len(a) != len(b):
        raise ValueError(f"paired arms must be the same length: {len(a)} vs {len(b)}")
    if not a:
        raise ValueError("no observations")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    point = sum(diffs) / len(diffs)

    rng = random.Random(seed)
    means: list[float] = []
    n = len(diffs)
    for _ in range(n_resamples):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1.0 - 0.95) / 2.0 if z == Z_95 else (1.0 - math.erf(z / math.sqrt(2))) / 2.0
    lo = means[int(alpha * n_resamples)]
    hi = means[min(n_resamples - 1, int((1.0 - alpha) * n_resamples))]
    return Interval(point=point, low=lo, high=hi, n=n)


def detectable_difference(n_per_arm: int, baseline: float, power: float = 0.8) -> float:
    """Roughly the smallest difference in proportions this n can detect.

    A planning aid, not an analysis: it uses the normal approximation for
    two independent proportions. Its job is to keep a table from implying
    an effect it never had the power to see, so it is reported alongside
    any comparison that comes back inconclusive.
    """
    if n_per_arm <= 0:
        raise ValueError("n must be positive")
    z_beta = {0.8: 0.8416, 0.9: 1.2816}.get(power, 0.8416)
    var = 2.0 * baseline * (1.0 - baseline)
    return (Z_95 + z_beta) * math.sqrt(var / n_per_arm)


# ---------------------------------------------------------------------------
# Comparing many arms at once
# ---------------------------------------------------------------------------


def holm_bonferroni(p_values: dict[str, float], alpha: float = 0.05) -> dict[str, Any]:
    """Holm-Bonferroni correction over a family of tests.

    A benchmark this wide produces dozens of comparisons, and at alpha =
    0.05 roughly one in twenty of them is significant by accident. Holm
    controls the family-wise error rate without the crudeness of plain
    Bonferroni — it is uniformly more powerful and needs no extra
    assumptions.

    Only the plan's preregistered primary endpoints are confirmatory; this
    exists so the exploratory rest cannot quietly be read as findings.
    """
    if not p_values:
        return {"alpha": alpha, "n_tests": 0, "results": {}}
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    results: dict[str, Any] = {}
    previous_rejected = True
    for i, (name, p) in enumerate(ordered):
        threshold = alpha / (n - i)
        # Holm stops at the first failure: nothing weaker can be rejected.
        rejected = previous_rejected and p <= threshold
        previous_rejected = rejected
        results[name] = {
            "p_value": p,
            "threshold": threshold,
            "rank": i + 1,
            "significant": rejected,
        }
    return {"alpha": alpha, "n_tests": n, "results": results}


def cohens_h(p1: float, p2: float) -> float:
    """Effect size for a difference between two proportions.

    A p-value says a difference is unlikely to be chance; it says nothing
    about whether the difference matters. Cohen's h is the arcsine-
    transformed distance, which unlike a raw difference is comparable
    across the range — 0.45 to 0.50 and 0.90 to 0.95 are the same five
    points and very different findings.

    Conventional reading: 0.2 small, 0.5 medium, 0.8 large.
    """
    for p in (p1, p2):
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"proportions must lie in [0, 1], got {p}")
    return abs(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))


@dataclass(frozen=True)
class Agreement:
    """How much two judges agree beyond what chance would give."""

    observed: float
    expected: float
    kappa: float
    n: int


def cohens_kappa(a: list[bool], b: list[bool]) -> Agreement:
    """Chance-corrected agreement between two binary judges.

    Raw agreement flatters any pair of judges facing a lopsided task: two
    assessors that both say "no fault" to everything agree perfectly on a
    corpus that is mostly clean. Kappa subtracts the agreement their
    marginal rates would have produced by chance, which is what makes
    tool-versus-model agreement interpretable.
    """
    if len(a) != len(b):
        raise ValueError(f"judges must score the same items: {len(a)} vs {len(b)}")
    if not a:
        raise ValueError("no items")
    n = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    kappa = 1.0 if expected == 1.0 else (observed - expected) / (1.0 - expected)
    return Agreement(observed=observed, expected=expected, kappa=kappa, n=n)


def variance_components(
    observations: list[tuple[str, str, float]],
) -> dict[str, Any]:
    """Split variance in an outcome into case, model, and residual parts.

    Takes ``(case, model, value)`` triples. The question behind a
    benchmark table is usually not "which model is best" but "how much of
    what I am seeing is the model at all" — if case-to-case variation
    dwarfs model-to-model variation, a leaderboard built on a handful of
    cases is mostly reporting which cases were chosen.

    A one-pass moment estimator, not a fitted mixed model: it needs no
    dependencies and answers the question at the resolution the design can
    support. Reported as shares of total variance.
    """
    if not observations:
        return {"n": 0}
    values = [v for _c, _m, v in observations]
    grand = sum(values) / len(values)
    total = sum((v - grand) ** 2 for v in values) / len(values)

    def group_share(index: int) -> tuple[float, int]:
        groups: dict[str, list[float]] = {}
        for obs in observations:
            groups.setdefault(obs[index], []).append(obs[2])
        between = sum(
            len(vals) * ((sum(vals) / len(vals)) - grand) ** 2 for vals in groups.values()
        ) / len(observations)
        return between, len(groups)

    case_var, n_cases = group_share(0)
    model_var, n_models = group_share(1)
    residual = max(0.0, total - case_var - model_var)

    def share(x: float) -> float | None:
        return (x / total) if total > 0 else None

    return {
        "n": len(observations),
        "n_cases": n_cases,
        "n_models": n_models,
        "grand_mean": grand,
        "total_variance": total,
        "case_share": share(case_var),
        "model_share": share(model_var),
        "residual_share": share(residual),
        # The warning this function exists to raise.
        "dominated_by_case_choice": bool(total > 0 and case_var > model_var),
    }


def required_n(baseline: float, difference: float, power: float = 0.8) -> int:
    """Paired sample size needed to detect a difference in proportions.

    The inverse of :func:`detectable_difference`, for planning a run before
    spending compute on it rather than discovering afterwards that the arm
    was never powered.
    """
    if not 0.0 < baseline < 1.0:
        raise ValueError("baseline must lie strictly inside (0, 1)")
    if difference <= 0.0:
        raise ValueError("difference must be positive")
    z_beta = {0.8: 0.8416, 0.9: 1.2816}.get(power, 0.8416)
    var = 2.0 * baseline * (1.0 - baseline)
    return math.ceil(var * ((Z_95 + z_beta) / difference) ** 2)


# ---------------------------------------------------------------------------
# Small samples: posteriors instead of p-values
# ---------------------------------------------------------------------------


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


@dataclass(frozen=True)
class Posterior:
    """A Beta posterior over a rate."""

    alpha: float
    beta: float
    mean: float
    low: float
    high: float
    n: int


def beta_posterior(
    successes: int, n: int, *, prior_a: float = 1.0, prior_b: float = 1.0
) -> Posterior:
    """Posterior over a rate, with a credible interval.

    At the sample sizes a probe corpus supports, a p-value answers a
    question nobody asked — "how surprising would this be if the arms were
    identical" — while the question actually in front of a reader is "how
    likely is this arm better, and by how much". A Beta posterior answers
    that directly and degrades gracefully at n = 0, where it simply returns
    the prior instead of undefined.

    The default uniform prior is deliberately uninformative: it makes the
    posterior mean ``(k+1)/(n+2)``, which is Laplace's rule and slightly
    conservative about perfect scores — 9 for 9 becomes 0.91, not 1.0.
    """
    if n < 0 or successes < 0 or successes > n:
        raise ValueError(f"{successes} successes out of {n}")
    a = prior_a + successes
    b = prior_b + (n - successes)
    mean = a / (a + b)
    # Equal-tailed 95% interval by bisection on the regularised incomplete
    # beta, which avoids depending on scipy for one function.
    return Posterior(
        alpha=a,
        beta=b,
        mean=mean,
        low=_beta_quantile(a, b, 0.025),
        high=_beta_quantile(a, b, 0.975),
        n=n,
    )


def _beta_cdf(a: float, b: float, x: float, grid: int = 20000) -> float:
    """Regularised incomplete beta, by direct quadrature of the density.

    A series expansion would be faster and is easy to get subtly wrong —
    the first attempt here returned 0.82 where the closed form for
    Beta(10, 1) gives 0.69, which would have shipped over-confident
    credible intervals. Quadrature on a fine grid is slower, obviously
    correct, and verified against that closed form in the tests.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_norm = _log_beta(a, b)
    step = x / grid
    total = 0.0
    for i in range(grid + 1):
        t = i * step
        # The density diverges at the endpoints when a or b < 1; skip the
        # exact endpoints and let the interior carry the mass.
        if t <= 0.0 or t >= 1.0:
            continue
        density = math.exp((a - 1) * math.log(t) + (b - 1) * math.log1p(-t) - log_norm)
        weight = 0.5 if i in (0, grid) else 1.0
        total += weight * density * step
    return min(1.0, max(0.0, total))


def _beta_quantile(a: float, b: float, p: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _beta_cdf(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def probability_better(
    successes_a: int, n_a: int, successes_b: int, n_b: int, *, draws: int = 20000,
    seed: int = 20260824,
) -> float:
    """P(rate of A > rate of B), by sampling both posteriors.

    Reported alongside a p-value rather than instead of it. "There is a 93%
    chance this arm is better" is a statement a reader can act on; "p =
    0.12" at n = 9 mostly says the corpus is small.
    """
    pa = beta_posterior(successes_a, n_a)
    pb = beta_posterior(successes_b, n_b)
    rng = random.Random(seed)
    wins = 0
    for _ in range(draws):
        if rng.betavariate(pa.alpha, pa.beta) > rng.betavariate(pb.alpha, pb.beta):
            wins += 1
    return wins / draws


# ---------------------------------------------------------------------------
# Clustered samples
# ---------------------------------------------------------------------------


def cluster_adjusted_wilson(
    clusters: list[tuple[int, int]], z: float = Z_95
) -> dict[str, Any]:
    """A rate over clustered observations, widened by the design effect.

    Probes are not independent: several share an injector, so a model that
    understands one non-orthogonality probe probably gets all of them. A
    plain Wilson interval over 9 such probes claims more precision than 9
    independent observations would give, and the overstatement grows with
    how strongly outcomes cluster.

    Takes ``(successes, size)`` per cluster and reports both the naive
    interval and one on the effective sample size ``n / design_effect``.
    """
    total_n = sum(size for _s, size in clusters)
    total_k = sum(successes for successes, _n in clusters)
    naive = wilson(total_k, total_n, z)
    if naive is None or len(clusters) < 2:
        # One cluster carries no between-cluster information, so there is
        # nothing to adjust. The shape stays the same either way, so callers
        # never have to branch on it.
        return {
            "naive": naive,
            "adjusted": naive,
            "design_effect": 1.0,
            "icc": None,
            "effective_n": total_n,
        }

    p = total_k / total_n
    # One-way ANOVA estimate of the intracluster correlation.
    mean_size = total_n / len(clusters)
    between = sum(
        size * ((successes / size) - p) ** 2 for successes, size in clusters if size
    ) / max(1, len(clusters) - 1)
    within = p * (1 - p)
    icc = 0.0 if within <= 0 else max(0.0, min(1.0, (between - within) / (
        between + within * (mean_size - 1)
    ))) if (between + within * (mean_size - 1)) > 0 else 0.0
    design_effect = 1.0 + (mean_size - 1) * icc
    effective_n = max(1, int(total_n / design_effect))
    adjusted = wilson(round(p * effective_n), effective_n, z)
    return {
        "naive": naive,
        "adjusted": adjusted,
        "design_effect": design_effect,
        "icc": icc,
        "effective_n": effective_n,
    }


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Calibration:
    """How well stated confidence matches observed correctness."""

    brier: float
    expected_error: float
    max_error: float
    bins: list[dict[str, Any]]
    n: int


def calibration(
    predictions: list[tuple[float, bool]], n_bins: int = 5
) -> Calibration:
    """Brier score and expected calibration error.

    The plan's H4 asks whether the tool stays calibrated as it degrades —
    whether a run that reports PASS is actually right, and whether one that
    reports REVIEW is actually doubtful. Accuracy alone cannot answer that:
    a system can be right most of the time and still be confidently wrong
    exactly where it matters.

    Brier is the mean squared error of the stated probability. Expected
    calibration error bins predictions by confidence and measures the gap
    between claimed and observed accuracy in each, which is what exposes a
    system that says 0.9 and is right 0.6 of the time.
    """
    if not predictions:
        raise ValueError("no predictions")
    for p, _ in predictions:
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"confidence must lie in [0, 1], got {p}")

    brier = sum((p - float(outcome)) ** 2 for p, outcome in predictions) / len(
        predictions
    )
    bins: list[dict[str, Any]] = []
    total_gap = 0.0
    max_gap = 0.0
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        members = [
            (p, o)
            for p, o in predictions
            if (lo <= p < hi) or (i == n_bins - 1 and p == 1.0)
        ]
        if not members:
            continue
        confidence = sum(p for p, _ in members) / len(members)
        accuracy = sum(1 for _p, o in members if o) / len(members)
        gap = abs(confidence - accuracy)
        total_gap += gap * len(members)
        max_gap = max(max_gap, gap)
        bins.append(
            {
                "range": [lo, hi],
                "n": len(members),
                "mean_confidence": confidence,
                "observed_accuracy": accuracy,
                "gap": gap,
            }
        )
    return Calibration(
        brier=brier,
        expected_error=total_gap / len(predictions),
        max_error=max_gap,
        bins=bins,
        n=len(predictions),
    )
