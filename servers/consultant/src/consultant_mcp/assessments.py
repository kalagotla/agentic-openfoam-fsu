"""Mesh-quality thresholds and verdict logic.

Each verdict carries a citation for its *recommendation*. The band
*cutoffs* themselves vary in provenance: some equal a verified OpenFOAM
constant, some are CFD practice convention, and the residual-pattern
classifier is a bespoke heuristic. Every cutoff is classified
(source-verified / practice / heuristic) in
``docs/consultant-threshold-provenance.md``; citations resolve via
``CITATION_SOURCES`` and are archived offline under ``corpus/references/``.

References (cited inline as ``cites`` on each rule). The
authoritative text + locator for each tag lives in
``CITATION_SOURCES`` below — this list is the human-readable index and
must stay in sync with it. Every tag has been resolved against the
named source (OpenFOAM v2412 install for the source-code tags, fetched
doc pages / publisher TOCs for the rest):

- ``of_check_mesh_src`` : checkMesh default thresholds defined in
  ``$FOAM_SRC/OpenFOAM/meshes/primitiveMesh/primitiveMeshCheck/primitiveMeshCheck.C``
  (``aspectThreshold_=1000``, ``nonOrthThreshold_=70`` deg,
  ``skewThreshold_=4``).
- ``of_mesh_quality_dict`` : OpenFOAM's default mesh-quality controls in
  ``$WM_PROJECT_DIR/etc/caseDicts/meshQualityDict`` (``maxNonOrtho=65``,
  ``maxInternalSkewness=4``, ``maxBoundarySkewness=20``,
  ``maxConcave=80``) — backs the non-orthogonality 'acceptable' band.
- ``of_user_guide`` : OpenFOAM v2412 User Guide, Ch. 4 "Mesh
  generation and conversion" (mesh-quality controls).
- ``of_user_guide_urf`` : OpenFOAM v2412 User Guide, 6.3 "Solution and
  algorithm control" (relaxation factors, residualControl, solver
  tolerances).
- ``versteeg`` : Versteeg & Malalasekera (2007), *An Introduction to
  CFD: The Finite Volume Method*, 2nd ed. — Ch. 3 (turbulence / law of
  the wall), Ch. 5 (convection-diffusion schemes), Ch. 6 (SIMPLE &
  under-relaxation), Ch. 11 (non-orthogonal / complex geometry).
- ``wilcox`` : Wilcox (2006), *Turbulence Modeling for CFD*, 3rd ed. —
  law of the wall and near-wall y+ resolution.
- ``menter_sst`` : Menter, Kuntz & Langtry (2003), "Ten Years of
  Industrial Experience with the SST Turbulence Model" — kOmegaSST
  blended/automatic wall treatment.
- ``nasa_tmr`` : NASA Turbulence Modeling Resource — wall-integration
  RANS needs average min y+ < 1 (flat-plate grids page).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

Verdict = Literal["good", "acceptable", "marginal", "poor", "unknown"]
VERDICT_ORDER = ("good", "acceptable", "marginal", "poor", "unknown")


@dataclass(frozen=True)
class MeshThresholds:
    """Where each mesh metric's quality bands begin.

    The values are the shipped defaults, sourced in
    ``docs/consultant-threshold-provenance.md``; they are a dataclass
    rather than literals so a study can move the operating point without
    re-implementing the verdict logic somewhere else. That matters here:
    the evaluation's detection curve has to come from the same tested
    function an agent calls, or it measures a copy rather than the tool.

    Each field gives the three cut points separating good / acceptable /
    marginal / poor. ``degenerate_non_orthogonality`` is not a quality
    band — it is the angle at which checkMesh calls the cell broken — so
    it is held apart from the tunable three.
    """

    non_orthogonality: tuple[float, float, float] = (60.0, 70.0, 80.0)
    degenerate_non_orthogonality: float = 90.0
    skewness: tuple[float, float, float] = (1.0, 4.0, 10.0)
    aspect_ratio: tuple[float, float, float] = (10.0, 100.0, 1000.0)
    # Severe-face counts are judged as a fraction of the cell count, so
    # these are fractions rather than absolute counts.
    severe_face_fraction: tuple[float, float] = (0.001, 0.01)

    def scaled(self, factor: float) -> "MeshThresholds":
        """The same bands, tightened (< 1) or loosened (> 1) together.

        One scalar moves every metric's boundary in the same direction,
        which is what a detection curve needs: a family of operating
        points ordered from strict to permissive. The degenerate angle
        does not move — a 90-degree cell is broken at any strictness.
        """
        if factor <= 0:
            raise ValueError("factor must be positive")
        return MeshThresholds(
            non_orthogonality=_scale3(self.non_orthogonality, factor),
            degenerate_non_orthogonality=self.degenerate_non_orthogonality,
            skewness=_scale3(self.skewness, factor),
            aspect_ratio=_scale3(self.aspect_ratio, factor),
            severe_face_fraction=(
                self.severe_face_fraction[0] * factor,
                self.severe_face_fraction[1] * factor,
            ),
        )


def _scale3(band: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return (band[0] * factor, band[1] * factor, band[2] * factor)


DEFAULT_MESH_THRESHOLDS = MeshThresholds()


@dataclass(frozen=True)
class ResidualThresholds:
    """The cut points that separate one convergence pattern from another.

    Parameterised for the same reason the mesh bands are: a detection curve
    has to come from the same tested function an agent calls. The knob is
    `sensitivity` rather than a plain scale, because these cuts are not all
    oriented the same way. Lowering the oscillation cut flags *more*;
    lowering the stall cut flags *less*. A single multiplier would move
    them against each other and produce a curve that is not a curve.
    """

    converged: float = 1e-5
    # A converged run may still wobble; the tail is allowed this multiple
    # of the convergence threshold.
    converged_tail_factor: float = 2.0
    # Coefficient of variation over the window, above which a
    # non-monotonic history reads as oscillating.
    oscillating_cov: float = 0.3
    # ...and below which a history that never reached the threshold reads
    # as stalled rather than merely slow.
    stalled_cov: float = 0.05
    # Last value this multiple above the window's reference reads as
    # diverging.
    diverging_factor: float = 2.0
    # Drop over the window needed to call a run still-running rather than
    # unclassifiable.
    still_running_factor: float = 3.0
    window: int = 50

    def at_sensitivity(self, sensitivity: float) -> "ResidualThresholds":
        """The same classifier, more (>1) or less (<1) eager to flag.

        Every cut moves in the direction that raises detection, so recall
        is monotone in the parameter and the resulting curve is ordered.
        """
        if sensitivity <= 0:
            raise ValueError("sensitivity must be positive")
        return ResidualThresholds(
            # A stricter convergence bar leaves more runs unconverged.
            converged=self.converged / sensitivity,
            converged_tail_factor=self.converged_tail_factor / sensitivity,
            # Flag oscillation on a smaller wobble.
            oscillating_cov=self.oscillating_cov / sensitivity,
            # Call a flat history stalled at a larger wobble.
            stalled_cov=self.stalled_cov * sensitivity,
            # Call a rise divergence sooner.
            diverging_factor=self.diverging_factor / sensitivity,
            still_running_factor=self.still_running_factor,
            window=self.window,
        )


DEFAULT_RESIDUAL_THRESHOLDS = ResidualThresholds()


def _num(value: float) -> str:
    """Format a threshold for a band label without trailing noise."""
    return f"{value:g}"


@dataclass
class MetricVerdict:
    """One metric's verdict + rationale + suggested action."""

    metric: str
    value: float | None
    verdict: Verdict
    threshold_band: str            # e.g. "60–70 deg"
    recommendation: str            # what to do about it
    cites: list[str]               # short citation tags

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "verdict": self.verdict,
            "threshold_band": self.threshold_band,
            "recommendation": self.recommendation,
            "cites": list(self.cites),
        }


def assess_non_orthogonality(
    angle: float | None,
    thresholds: MeshThresholds = DEFAULT_MESH_THRESHOLDS,
) -> MetricVerdict:
    """Verdict on the maximum non-orthogonality angle (degrees).

    Non-orthogonality is the angle between the line connecting two
    adjacent cell centres and the face-normal vector between them.
    Higher angles increase the explicit non-orthogonal correction the
    pressure equation needs to converge cleanly. OpenFOAM's default
    severe-non-orthogonal threshold is 70 deg (``checkMesh`` source).
    """
    if angle is None:
        return MetricVerdict(
            metric="max_non_orthogonality",
            value=None,
            verdict="unknown",
            threshold_band="n/a",
            recommendation=(
                "checkMesh did not report a non-orthogonality value. "
                "Re-run check_mesh and inspect log.checkMesh."
            ),
            cites=[],
        )
    good_to, acceptable_to, marginal_to = thresholds.non_orthogonality
    if angle < good_to:
        return MetricVerdict(
            metric="max_non_orthogonality",
            value=angle,
            verdict="good",
            threshold_band=f"< {_num(good_to)} deg",
            recommendation=(
                "No corrector needed — standard fvSchemes settings are fine."
            ),
            cites=["of_check_mesh_src"],
        )
    if angle < acceptable_to:
        return MetricVerdict(
            metric="max_non_orthogonality",
            value=angle,
            verdict="acceptable",
            threshold_band=f"{_num(good_to)}–{_num(acceptable_to)} deg",
            recommendation=(
                "Set fvSolution.SIMPLE.nNonOrthogonalCorrectors = 1 "
                "(or PIMPLE for transient). Default 0 may slow convergence."
            ),
            cites=["of_check_mesh_src", "of_mesh_quality_dict"],
        )
    if angle < marginal_to:
        return MetricVerdict(
            metric="max_non_orthogonality",
            value=angle,
            verdict="marginal",
            threshold_band=f"{_num(acceptable_to)}–{_num(marginal_to)} deg",
            recommendation=(
                "Raise nNonOrthogonalCorrectors to 2–3 and use the "
                "``limited`` divergence/grad schemes (e.g. ``Gauss "
                "linear limited 0.5``). Inspect convergence carefully."
            ),
            cites=["of_user_guide", "versteeg"],
        )
    if angle < thresholds.degenerate_non_orthogonality:
        return MetricVerdict(
            metric="max_non_orthogonality",
            value=angle,
            verdict="poor",
            threshold_band=(
                f"{_num(marginal_to)}–"
                f"{_num(thresholds.degenerate_non_orthogonality)} deg"
            ),
            recommendation=(
                "Convergence is unreliable above 80 deg even with many "
                "non-orthogonal correctors. Recommend re-meshing the "
                "offending region (refine, or improve block topology)."
            ),
            cites=["of_user_guide", "versteeg"],
        )
    return MetricVerdict(
        metric="max_non_orthogonality",
        value=angle,
        verdict="poor",
        threshold_band=(
            f"≥ {_num(thresholds.degenerate_non_orthogonality)} deg"
        ),
        recommendation=(
            "checkMesh treats this as an outright failure. Re-mesh — "
            "no scheme can paper over a degenerate cell."
        ),
        cites=["of_check_mesh_src"],
    )


def assess_skewness(
    skewness: float | None,
    thresholds: MeshThresholds = DEFAULT_MESH_THRESHOLDS,
) -> MetricVerdict:
    """Verdict on the maximum face skewness.

    Skewness measures how far a face-centre lies from the line joining
    its two cell-centres, scaled by the face area. OpenFOAM's
    ``checkMesh`` warns when skewness exceeds ``skewThreshold_`` = 4.0
    (``primitiveMeshCheck.C``). The ``< 1`` "good" boundary used below
    is a conservative practice convention, not a checkMesh threshold.
    """
    if skewness is None:
        return MetricVerdict(
            metric="max_skewness",
            value=None,
            verdict="unknown",
            threshold_band="n/a",
            recommendation=(
                "checkMesh did not report a skewness value. "
                "Re-run check_mesh and inspect log.checkMesh."
            ),
            cites=[],
        )
    good_to, acceptable_to, marginal_to = thresholds.skewness
    if skewness < good_to:
        return MetricVerdict(
            metric="max_skewness",
            value=skewness,
            verdict="good",
            threshold_band=f"< {_num(good_to)}",
            recommendation="No action — well within all solver tolerances.",
            cites=["of_check_mesh_src"],
        )
    if skewness < acceptable_to:
        return MetricVerdict(
            metric="max_skewness",
            value=skewness,
            verdict="acceptable",
            threshold_band=f"{_num(good_to)}–{_num(acceptable_to)}",
            recommendation=(
                "OK in practice; consider ``limited`` gradient schemes "
                "(``cellLimited Gauss linear 1``) if convergence slows."
            ),
            cites=["of_check_mesh_src", "of_mesh_quality_dict"],
        )
    if skewness < marginal_to:
        return MetricVerdict(
            metric="max_skewness",
            value=skewness,
            verdict="marginal",
            threshold_band=f"{_num(acceptable_to)}–{_num(marginal_to)}",
            recommendation=(
                "Above the checkMesh hex default fail (4). Either "
                "re-mesh the local region or accept the trade and use "
                "bounded schemes + tighter linear-solver tolerances."
            ),
            cites=["of_check_mesh_src", "versteeg"],
        )
    return MetricVerdict(
        metric="max_skewness",
        value=skewness,
        verdict="poor",
        threshold_band=f"≥ {_num(marginal_to)}",
        recommendation=(
            "Highly skewed faces — likely a snappyHexMesh artefact at "
            "geometry intersections. Re-meshing is the right call; "
            "tightening schemes only delays the inevitable."
        ),
        cites=["of_user_guide"],
    )


def assess_aspect_ratio(
    ratio: float | None,
    thresholds: MeshThresholds = DEFAULT_MESH_THRESHOLDS,
) -> MetricVerdict:
    """Verdict on the maximum cell aspect ratio.

    Aspect ratio is the ratio of a cell's longest dimension to its
    shortest. Wall-resolved meshes (y+ ~ 1) typically have aspect
    ratios in the hundreds; coarse bulk meshes are below 10.
    """
    if ratio is None:
        return MetricVerdict(
            metric="max_aspect_ratio",
            value=None,
            verdict="unknown",
            threshold_band="n/a",
            recommendation=(
                "checkMesh did not report an aspect ratio. "
                "Re-run check_mesh and inspect log.checkMesh."
            ),
            cites=[],
        )
    good_to, acceptable_to, marginal_to = thresholds.aspect_ratio
    if ratio < good_to:
        return MetricVerdict(
            metric="max_aspect_ratio",
            value=ratio,
            verdict="good",
            threshold_band=f"< {_num(good_to)}",
            recommendation=(
                "Cells are nearly isotropic — appropriate for bulk-flow "
                "regions or low-Re recirculating flows."
            ),
            cites=["versteeg"],
        )
    if ratio < acceptable_to:
        return MetricVerdict(
            metric="max_aspect_ratio",
            value=ratio,
            verdict="acceptable",
            threshold_band=f"{_num(good_to)}–{_num(acceptable_to)}",
            recommendation=(
                "Typical for moderately wall-resolved meshes. Watch "
                "the linear-solver iteration count near the wall."
            ),
            cites=["versteeg"],
        )
    if ratio < marginal_to:
        return MetricVerdict(
            metric="max_aspect_ratio",
            value=ratio,
            verdict="marginal",
            threshold_band=f"{_num(acceptable_to)}–{_num(marginal_to)}",
            recommendation=(
                "High aspect ratio — typical of y+ ~ 1 boundary layers. "
                "Use GAMG / PBiCG with tight tolerances; the pressure "
                "equation is sensitive here."
            ),
            cites=["of_user_guide"],
        )
    return MetricVerdict(
        metric="max_aspect_ratio",
        value=ratio,
        verdict="poor",
        threshold_band=f"≥ {_num(marginal_to)}",
        recommendation=(
            "Very high aspect ratio. Consider wall functions (relaxes "
            "y+ to ~30) instead of resolved y+ ~ 1, or accept slower "
            "convergence with tight solver tolerances."
        ),
        cites=["of_check_mesh_src", "versteeg"],
    )


def assess_severe_non_orthogonal(
    n_faces: int | None,
    n_cells: int | None,
    thresholds: MeshThresholds = DEFAULT_MESH_THRESHOLDS,
) -> MetricVerdict:
    """Verdict on the count of severely non-orthogonal faces.

    checkMesh flags faces with non-orthogonality > 70 deg as severe.
    A handful (< 0.1% of cells) is usually harmless; many indicates a
    systematic meshing problem.
    """
    if n_faces is None:
        return MetricVerdict(
            metric="severe_non_orthogonal_faces",
            value=None,
            verdict="unknown",
            threshold_band="n/a",
            recommendation=(
                "checkMesh did not report a severe-face count. "
                "Re-run check_mesh."
            ),
            cites=[],
        )
    if n_faces == 0:
        return MetricVerdict(
            metric="severe_non_orthogonal_faces",
            value=float(n_faces),
            verdict="good",
            threshold_band="0",
            recommendation="No severe faces — no action.",
            cites=["of_check_mesh_src"],
        )
    if not n_cells or n_cells <= 0:
        # The severity bands are a fraction of the cell count; without a
        # valid n_cells we cannot judge whether the count is harmless or
        # systematic, so report unknown rather than condemning to "poor".
        return MetricVerdict(
            metric="severe_non_orthogonal_faces",
            value=float(n_faces),
            verdict="unknown",
            threshold_band="n/a (cell count unknown)",
            recommendation=(
                f"{n_faces} severe faces reported, but the cell count could "
                f"not be parsed, so severity (as a fraction of cells) can't "
                f"be assessed. Re-run check_mesh and inspect log.checkMesh."
            ),
            cites=[],
        )
    acceptable_to, marginal_to = thresholds.severe_face_fraction
    if n_faces / n_cells < acceptable_to:
        return MetricVerdict(
            metric="severe_non_orthogonal_faces",
            value=float(n_faces),
            verdict="acceptable",
            threshold_band=f"< {_num(acceptable_to * 100)}% of cells",
            recommendation=(
                "Small count — typically tolerable; ensure "
                "nNonOrthogonalCorrectors ≥ 1."
            ),
            cites=["of_check_mesh_src"],
        )
    if n_faces / n_cells < marginal_to:
        return MetricVerdict(
            metric="severe_non_orthogonal_faces",
            value=float(n_faces),
            verdict="marginal",
            threshold_band=(
                f"{_num(acceptable_to * 100)}–{_num(marginal_to * 100)}% of cells"
            ),
            recommendation=(
                "Non-trivial; consider local mesh refinement at the "
                "offending region. Use ``checkMesh -writeAllFields`` "
                "to visualise where they live."
            ),
            cites=["of_user_guide"],
        )
    return MetricVerdict(
        metric="severe_non_orthogonal_faces",
        value=float(n_faces),
        verdict="poor",
        threshold_band=(
            f"> {_num(marginal_to * 100)}% of cells (or many on small mesh)"
        ),
        recommendation=(
            "Systematic non-orthogonality. The mesh has a topology "
            "problem — re-mesh rather than band-aid with correctors."
        ),
        cites=["of_user_guide", "versteeg"],
    )


# Source references the verdicts cite back to. Each entry names the
# authoritative source AND a resolvable locator (a real file path in the
# OpenFOAM v2412 tree, a fetched doc URL, or a book + ISBN/chapter).
# Keep this in sync with the reference list in the module docstring.
CITATION_SOURCES: dict[str, str] = {
    "of_check_mesh_src": (
        "OpenFOAM v2412 checkMesh defaults — $FOAM_SRC/OpenFOAM/meshes/"
        "primitiveMesh/primitiveMeshCheck/primitiveMeshCheck.C "
        "(aspectThreshold_=1000, nonOrthThreshold_=70 deg, "
        "skewThreshold_=4; 'severe' non-ortho = faces above "
        "nonOrthThreshold_)."
    ),
    "of_mesh_quality_dict": (
        "OpenFOAM v2412 default mesh-quality controls — "
        "$WM_PROJECT_DIR/etc/caseDicts/meshQualityDict "
        "(maxNonOrtho=65 deg, maxInternalSkewness=4, "
        "maxBoundarySkewness=20, maxConcave=80 deg). These are the "
        "limits snappyHexMesh/mesh-motion treat as acceptable, which is "
        "why the consultant's non-orthogonality 'acceptable' band tops "
        "out near 65-70 deg and skewness 'acceptable' tops out at 4."
    ),
    "of_user_guide": (
        "OpenFOAM v2412 User Guide, Ch. 4 'Mesh generation and "
        "conversion' (mesh-quality controls) — "
        "https://www.openfoam.com/documentation/user-guide/"
        "4-mesh-generation-and-conversion"
    ),
    "of_user_guide_urf": (
        "OpenFOAM v2412 User Guide, 6.3 'Solution and algorithm control' "
        "(relaxationFactors, residualControl, linear-solver tolerances) — "
        "https://www.openfoam.com/documentation/user-guide/6-solving/"
        "6.3-solution-and-algorithm-control"
    ),
    "versteeg": (
        "Versteeg & Malalasekera (2007), An Introduction to CFD: The "
        "Finite Volume Method, 2nd ed. (ISBN 9780131274983) — Ch. 3 "
        "(turbulence & law of the wall), Ch. 5 (convection-diffusion "
        "schemes), Ch. 6 (SIMPLE & under-relaxation), Ch. 11 "
        "(non-orthogonal / complex geometry)."
    ),
    "wilcox": (
        "Wilcox, D.C. (2006), Turbulence Modeling for CFD, 3rd ed., DCW "
        "Industries (ISBN 9781928729082) — law of the wall and near-wall "
        "y+ resolution for wall-function vs wall-integration meshing."
    ),
    "menter_sst": (
        "Menter, Kuntz & Langtry (2003), 'Ten Years of Industrial "
        "Experience with the SST Turbulence Model', Turbulence, Heat and "
        "Mass Transfer 4, pp. 625-632 — kOmegaSST automatic/blended wall "
        "treatment (y+-insensitive near-wall formulation)."
    ),
    "nasa_tmr": (
        "NASA Turbulence Modeling Resource, flat-plate grids page: "
        "wall-integration RANS (no wall functions) needs average min "
        "y+ < 1 — https://tmbwg.github.io/turbmodels/flatplate_grids.html"
    ),
}


# ---------------------------------------------------------------------------
# Residual-pattern classification.
# ---------------------------------------------------------------------------

ResidualPattern = Literal[
    "converged",
    "still_running",
    "stalled",
    "oscillating",
    "diverging",
    "insufficient_data",
]


@dataclass
class ResidualVerdict:
    """One field's residual-pattern verdict."""

    field: str
    pattern: ResidualPattern
    verdict: Verdict
    last_value: float | None
    window_min: float | None
    window_max: float | None
    recommendation: str
    cites: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "pattern": self.pattern,
            "verdict": self.verdict,
            "last_value": self.last_value,
            "window_min": self.window_min,
            "window_max": self.window_max,
            "recommendation": self.recommendation,
            "cites": list(self.cites),
        }


def assess_residual_pattern(
    field: str,
    history: list[float],
    threshold: float | None = None,
    window: int | None = None,
    bands: ResidualThresholds = DEFAULT_RESIDUAL_THRESHOLDS,
) -> ResidualVerdict:
    """Classify the convergence pattern of one field's initial residuals.

    Operates on the LAST ``window`` values in ``history``. ``history``
    should be the per-iteration **initial** residuals (the value
    OpenFOAM prints as ``Initial residual = ...`` in SIMPLE / PIMPLE),
    not the final linear-solver residuals.

    PROVENANCE: the classification cutoffs below (the 1e-5 convergence
    level, the 50-iteration window, the CoV and factor-of-2/3 thresholds)
    are this tool's own heuristic for pattern detection — they are NOT
    drawn from a reference. The *remediation advice* each verdict carries
    (URF tuning, scheme order, corrector counts) IS cited
    (``of_user_guide_urf``, ``versteeg``); only the detection thresholds
    are bespoke. See ``docs/consultant-threshold-provenance.md``.

    Classification (in priority order — first match wins):

    - ``converged``: last value ≤ threshold AND all values in window ≤ threshold.
    - ``diverging``: a non-finite (NaN/Inf) value anywhere in the window
      (the solve blew up), OR last ≥ 2 × the window reference (the first
      value, falling back to the first positive value when the window
      starts at exactly 0).
    - ``oscillating``: coefficient of variation over window > 0.3 AND
      sequence is not monotonic.
    - ``stalled``: coefficient of variation over window < 0.05 AND
      last value > threshold.
    - ``still_running``: last < first by ≥ a factor of 3 (≈ half an
      order of magnitude) over the window; otherwise insufficient
      drop to claim still-running.
    - ``insufficient_data``: history has fewer than 5 entries — can't
      classify.
    """
    # `threshold` and `window` predate the bands object and callers still
    # pass them; an explicit argument wins over the band it corresponds to.
    threshold = bands.converged if threshold is None else threshold
    window = bands.window if window is None else window

    n = len(history)
    if n < 5:
        return ResidualVerdict(
            field=field,
            pattern="insufficient_data",
            verdict="unknown",
            last_value=history[-1] if history else None,
            window_min=None,
            window_max=None,
            recommendation=(
                "History too short to classify — run more iterations."
            ),
            cites=[],
        )

    window_values = history[-window:] if n >= window else list(history)
    last = window_values[-1]
    first = window_values[0]

    # --- Non-finite guard: NaN/Inf means the solve produced invalid
    # numbers (it blew up). NaN compares False to everything, so without
    # this it would fall through to "still_running"/"acceptable" and read
    # as healthy. Checked first, before the stats that NaN would poison.
    if any(not math.isfinite(v) for v in window_values):
        return ResidualVerdict(
            field=field,
            pattern="diverging",
            verdict="poor",
            last_value=last if math.isfinite(last) else None,
            window_min=None,
            window_max=None,
            recommendation=(
                f"{field} residual went non-finite (NaN/Inf) within the "
                f"window — the solution blew up. Drop to first-order "
                f"divergence schemes (Gauss upwind), reduce URFs "
                f"(p: 0.3, U: 0.5), and for transient runs cut deltaT to "
                f"keep Co < 1; check checkMesh for cells the solver can't "
                f"handle."
            ),
            cites=["of_user_guide_urf", "versteeg"],
        )

    w_min = min(window_values)
    w_max = max(window_values)
    mean = sum(window_values) / len(window_values)
    # Reference for the growth/drop ratio checks below. Falls back to the
    # first positive value if the window starts at exactly 0 (a field
    # initialised to 0), so a blow-up from 0 is still caught as diverging
    # rather than slipping past the `first > 0` guard.
    ref = first if first > 0 else next((v for v in window_values if v > 0), 0.0)

    # Coefficient of variation (variance / mean) — only meaningful if
    # mean > 0. Use the unbiased sample stddev relative to mean.
    if mean > 0 and len(window_values) > 1:
        variance = sum((v - mean) ** 2 for v in window_values) / (
            len(window_values) - 1
        )
        cov = (variance ** 0.5) / mean
    else:
        cov = 0.0

    # Monotonicity check — strictly decreasing or strictly increasing.
    strictly_dec = all(
        window_values[i] >= window_values[i + 1]
        for i in range(len(window_values) - 1)
    )
    strictly_inc = all(
        window_values[i] <= window_values[i + 1]
        for i in range(len(window_values) - 1)
    )

    # --- Converged: last value below threshold, with no recent spike.
    # Looking at the *tail* of the window matches the CFD reality (solvers
    # exit when residuals first reach the threshold and stay there); the
    # earlier strict "whole window below threshold" check missed clean
    # convergence cases where the run-up still had values around threshold.
    tail = window_values[-min(10, len(window_values)):]
    if last <= threshold and max(tail) <= bands.converged_tail_factor * threshold:
        return ResidualVerdict(
            field=field,
            pattern="converged",
            verdict="good",
            last_value=last,
            window_min=w_min,
            window_max=w_max,
            recommendation=(
                f"{field} residual converged below {threshold:.0e}; "
                f"the field's iteration loop is doing nothing useful — "
                f"accept and move on."
            ),
            cites=["of_user_guide_urf"],
        )

    # --- Oscillating: high coefficient of variation + non-monotonic.
    # Checked BEFORE diverging because an oscillating signal can have
    # last ≥ 2× first by chance (depending on which half of the cycle
    # it ends on), and oscillation is the more informative diagnosis.
    if cov > bands.oscillating_cov and not (strictly_dec or strictly_inc):
        return ResidualVerdict(
            field=field,
            pattern="oscillating",
            verdict="marginal",
            last_value=last,
            window_min=w_min,
            window_max=w_max,
            recommendation=(
                f"{field} residual oscillating in "
                f"[{w_min:.2e}, {w_max:.2e}] over last {len(window_values)} "
                f"iterations (CoV={cov:.2f}). Usually URFs too loose for "
                f"the regime — try p: 0.7→0.3-0.5, U: 0.9→0.5-0.7. For "
                f"transient runs in SIMPLE form, the case may actually "
                f"be unsteady — consider switching to a transient solver."
            ),
            cites=["of_user_guide_urf"],
        )

    # --- Diverging: last ≥ 2× the reference value over the window.
    if ref > 0 and last >= bands.diverging_factor * ref:
        return ResidualVerdict(
            field=field,
            pattern="diverging",
            verdict="poor",
            last_value=last,
            window_min=w_min,
            window_max=w_max,
            recommendation=(
                f"{field} residual grew from {ref:.2e} to {last:.2e}. "
                f"Try: (a) drop to first-order divergence schemes "
                f"(Gauss upwind), (b) reduce URFs (p: 0.3, U: 0.5), "
                f"(c) check checkMesh for cells the solver can't "
                f"handle. For transient runs, reduce deltaT to keep "
                f"Co < 1."
            ),
            cites=["of_user_guide_urf", "versteeg"],
        )

    # --- Stalled: low CoV but above threshold.
    if cov < bands.stalled_cov and last > threshold:
        return ResidualVerdict(
            field=field,
            pattern="stalled",
            verdict="marginal",
            last_value=last,
            window_min=w_min,
            window_max=w_max,
            recommendation=(
                f"{field} residual plateaued at ~{last:.2e} (CoV={cov:.2f}) "
                f"— iterating without further improvement. Common causes: "
                f"(a) linear-solver tolerances too loose — tighten "
                f"fvSolution {field}.tolerance and reduce relTol, "
                f"(b) mesh non-orthogonality — raise "
                f"nNonOrthogonalCorrectors, (c) the solution is as "
                f"converged as the discretisation permits — refine the "
                f"mesh or accept the plateau as the residual floor."
            ),
            cites=["of_user_guide_urf", "versteeg"],
        )

    # --- Still running: dropping, but not at threshold yet.
    if ref > 0 and last < ref / bands.still_running_factor:
        return ResidualVerdict(
            field=field,
            pattern="still_running",
            verdict="acceptable",
            last_value=last,
            window_min=w_min,
            window_max=w_max,
            recommendation=(
                f"{field} residual dropping from {ref:.2e} to "
                f"{last:.2e} over the window. Continue iterating — "
                f"convergence trajectory looks healthy."
            ),
            cites=["of_user_guide_urf"],
        )

    # --- Fall-through: no strong signal. Mark as still-running with
    # weaker confidence.
    return ResidualVerdict(
        field=field,
        pattern="still_running",
        verdict="acceptable",
        last_value=last,
        window_min=w_min,
        window_max=w_max,
        recommendation=(
            f"{field} residual at {last:.2e}, range "
            f"[{w_min:.2e}, {w_max:.2e}] over window — no clear pattern. "
            f"Continue iterating and re-assess; consider widening "
            f"window or running longer."
        ),
        cites=["of_user_guide_urf"],
    )


# ---------------------------------------------------------------------------
# y+ band classification.
# ---------------------------------------------------------------------------

YPlusModelClass = Literal[
    "laminar",
    "high_re_wall_function",   # standard wall function: k-epsilon, realizableKE
    "low_re_resolved",         # Spalart-Allmaras, low-Re k-omega
    "hybrid",                  # kOmegaSST (continuous wall blending in v2412)
    "les",                     # subgrid models — wall-resolved
    "unknown",
]

# Map OpenFOAM RAS model names (case-insensitive substrings) to their
# wall-treatment class.
_MODEL_NAME_TO_CLASS: dict[str, YPlusModelClass] = {
    "kepsilon": "high_re_wall_function",
    "realizableke": "high_re_wall_function",
    "rngkepsilon": "high_re_wall_function",
    "laundersharmake": "low_re_resolved",  # low-Re k-epsilon variant
    "komegasst": "hybrid",
    "komegasstias": "hybrid",
    "komega": "low_re_resolved",  # default k-omega: low-Re by design
    "spalartallmaras": "low_re_resolved",
    "lien": "low_re_resolved",
    "smagorinsky": "les",
    "wale": "les",
    "dynamick": "les",
    "keqn": "les",
}


def _match_model_class(key: str) -> YPlusModelClass | None:
    """Return the wall-treatment class for a (lower-cased) model name.

    Matches the LONGEST needle first so a more specific name wins over a
    substring of it — e.g. ``komegasst`` -> hybrid rather than ``komega``
    -> low_re_resolved. This removes any dependence on dict insertion
    order. Returns None if no needle matches.
    """
    for needle in sorted(_MODEL_NAME_TO_CLASS, key=len, reverse=True):
        if needle in key:
            return _MODEL_NAME_TO_CLASS[needle]
    return None


def classify_turbulence_model(
    simulation_type: str, ras_model: str | None = None,
    les_model: str | None = None,
) -> YPlusModelClass:
    """Map turbulenceProperties contents to a wall-treatment class."""
    st = simulation_type.strip().lower()
    if st == "laminar":
        return "laminar"
    if st == "les":
        if les_model:
            matched = _match_model_class(les_model.strip().lower())
            if matched is not None:
                return matched
        return "les"
    if st == "ras":
        if not ras_model:
            return "unknown"
        matched = _match_model_class(ras_model.strip().lower())
        return matched if matched is not None else "unknown"
    return "unknown"


@dataclass
class YPlusVerdict:
    """One wall patch's y+ verdict."""

    patch: str
    y_plus_min: float | None
    y_plus_max: float | None
    y_plus_avg: float | None
    verdict: Verdict
    band: str
    recommendation: str
    cites: list[str]
    model_class: YPlusModelClass

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch": self.patch,
            "y_plus_min": self.y_plus_min,
            "y_plus_max": self.y_plus_max,
            "y_plus_avg": self.y_plus_avg,
            "verdict": self.verdict,
            "band": self.band,
            "recommendation": self.recommendation,
            "cites": list(self.cites),
            "model_class": self.model_class,
        }


def assess_y_plus(
    patch: str,
    y_plus_min: float | None,
    y_plus_max: float | None,
    y_plus_avg: float | None,
    model_class: YPlusModelClass,
) -> YPlusVerdict:
    """Verdict for one wall patch's y+ given the turbulence-model class.

    Bands (source differs by wall treatment — see ``CITATION_SOURCES``):

    - ``high_re_wall_function`` (k-epsilon family): need y+ in the log
      layer [30, 300]. Below 30 the buffer/viscous sublayer isn't
      modelled by the wall function; above 300 you've lost wall-shear
      fidelity. Law-of-the-wall basis: ``versteeg`` (Ch. 3), ``wilcox``.
    - ``low_re_resolved`` (Spalart-Allmaras, low-Re k-omega): need
      y+ < 1 to resolve the viscous sublayer; > 1 starts losing
      shear-stress accuracy. Basis: ``nasa_tmr`` (flat-plate grids).
    - ``hybrid`` (kOmegaSST with v2412's continuous wall blending):
      best at y+ < 1, acceptable < 5, marginal 5-30, poor > 30. Basis:
      ``menter_sst`` (automatic wall treatment).
    - ``laminar``: y+ is undefined.
    """
    if model_class == "laminar":
        return YPlusVerdict(
            patch=patch,
            y_plus_min=y_plus_min,
            y_plus_max=y_plus_max,
            y_plus_avg=y_plus_avg,
            verdict="unknown",
            band="not_applicable",
            recommendation=(
                "Laminar simulation — y+ does not apply (there is no "
                "turbulent boundary layer to characterise). Skip this "
                "check."
            ),
            cites=[],
            model_class=model_class,
        )

    if y_plus_max is None:
        return YPlusVerdict(
            patch=patch,
            y_plus_min=y_plus_min,
            y_plus_max=y_plus_max,
            y_plus_avg=y_plus_avg,
            verdict="unknown",
            band="not_reported",
            recommendation=(
                "y+ max not reported for this patch. Re-run yPlus "
                "function object."
            ),
            cites=[],
            model_class=model_class,
        )

    y = y_plus_max

    if model_class == "high_re_wall_function":
        if 30.0 <= y <= 300.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="good",
                band="30 ≤ y+ ≤ 300",
                recommendation=(
                    "In the log-law region — standard wall-function "
                    "treatment is valid."
                ),
                cites=["versteeg", "wilcox"],
                model_class=model_class,
            )
        if y < 11.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="poor",
                band="y+ < 11 (viscous sublayer; wall function invalid)",
                recommendation=(
                    "Mesh is too fine for a high-Re wall function. "
                    "Either coarsen the first wall cell to land in "
                    "[30, 300], or switch to a low-Re-capable model "
                    "(kOmegaSST or Spalart-Allmaras)."
                ),
                cites=["versteeg", "wilcox"],
                model_class=model_class,
            )
        if 11.0 <= y < 30.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="marginal",
                band="11 ≤ y+ < 30 (buffer layer)",
                recommendation=(
                    "First wall cell lands in the buffer layer where "
                    "neither the log-law nor the viscous sublayer is "
                    "an accurate model. Mesh slightly coarser (target "
                    "y+ ≥ 30) or switch to a hybrid/low-Re model."
                ),
                cites=["versteeg", "wilcox"],
                model_class=model_class,
            )
        return YPlusVerdict(  # y > 300
            patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
            y_plus_avg=y_plus_avg, verdict="marginal",
            band="y+ > 300 (outside log layer)",
            recommendation=(
                "First wall cell is so coarse it sits outside the "
                "log layer. Refine — target y+ ≤ 300."
            ),
            cites=["versteeg", "wilcox"],
            model_class=model_class,
        )

    if model_class in ("low_re_resolved", "les"):
        if y <= 1.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="good", band="y+ ≤ 1",
                recommendation=(
                    "Viscous sublayer resolved — appropriate for this "
                    "model."
                ),
                cites=["nasa_tmr", "versteeg"],
                model_class=model_class,
            )
        if y <= 5.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="marginal",
                band="1 < y+ ≤ 5",
                recommendation=(
                    "Slightly under-resolved at the wall. Refine the "
                    "first-cell height by ~2× to push y+ ≤ 1."
                ),
                cites=["nasa_tmr"],
                model_class=model_class,
            )
        return YPlusVerdict(
            patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
            y_plus_avg=y_plus_avg, verdict="poor", band="y+ > 5",
            recommendation=(
                "Wall mesh far too coarse for a low-Re-resolving "
                "model. Refine the boundary layer by ~5–10× or switch "
                "to a high-Re wall-function model."
            ),
            cites=["nasa_tmr"],
            model_class=model_class,
        )

    if model_class == "hybrid":
        if y < 1.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="good", band="y+ < 1",
                recommendation=(
                    "Wall-resolved — kOmegaSST's low-Re branch is active."
                ),
                cites=["menter_sst", "nasa_tmr"],
                model_class=model_class,
            )
        if y < 5.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="acceptable",
                band="1 ≤ y+ < 5",
                recommendation=(
                    "kOmegaSST's continuous wall treatment handles "
                    "this range, but y+ < 1 is preferred for force/"
                    "skin-friction quantities."
                ),
                cites=["menter_sst"],
                model_class=model_class,
            )
        if y < 30.0:
            return YPlusVerdict(
                patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
                y_plus_avg=y_plus_avg, verdict="marginal",
                band="5 ≤ y+ < 30 (buffer-layer landing)",
                recommendation=(
                    "First cell in the buffer layer — kOmegaSST's "
                    "blending mitigates it but Cf accuracy suffers. "
                    "Refine to y+ < 1 if forces matter."
                ),
                cites=["menter_sst", "nasa_tmr"],
                model_class=model_class,
            )
        return YPlusVerdict(
            patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
            y_plus_avg=y_plus_avg, verdict="poor", band="y+ ≥ 30",
            recommendation=(
                "Effectively running kOmegaSST as a wall-function model. "
                "Either accept that (it works) and verify Cf isn't a "
                "deliverable, or refine the boundary layer."
            ),
            cites=["menter_sst"],
            model_class=model_class,
        )

    # unknown
    return YPlusVerdict(
        patch=patch, y_plus_min=y_plus_min, y_plus_max=y_plus_max,
        y_plus_avg=y_plus_avg, verdict="unknown",
        band="model class not recognised",
        recommendation=(
            "Could not match the turbulence model name to a known "
            "wall-treatment class. Report the model in REPORT.md and "
            "consult the model's documentation for required y+."
        ),
        cites=[],
        model_class=model_class,
    )


def aggregate_verdict(
    verdicts: list[MetricVerdict] | list[ResidualVerdict] | list[YPlusVerdict],
) -> Verdict:
    """Reduce a list of per-item verdicts to a single overall verdict.

    Conservative: the overall verdict is the *worst* individual verdict
    that isn't ``unknown``. ``unknown`` is ignored unless every verdict
    is unknown.
    """
    known = [v.verdict for v in verdicts if v.verdict != "unknown"]
    if not known:
        return "unknown"
    # Take the worst rank.
    return max(known, key=lambda v: VERDICT_ORDER.index(v))
