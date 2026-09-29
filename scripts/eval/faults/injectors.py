"""Fault injectors: known-bad artefacts with known ground truth.

Detection can only be measured against faults whose presence and identity
are known in advance, so each injector here takes a clean artefact and
returns a faulty one together with a label saying what it did. The label is
the ground truth; the assessor never sees it.

Two design choices worth stating.

**Probes are artefacts, not whole cases.** An assessment-only probe is
cheap precisely because the assessor reads a log or a dictionary, not a
mesh — so a probe is a small directory of text, checked in, that runs in
milliseconds. That is what makes N large enough for the detection arm to
carry real statistical power (`docs/evaluation-plan.md` §4).

**The clean baseline is a real log**, captured from an actual lid-cavity
run, not a hand-written one. A synthetic "clean" artefact risks being
detectably synthetic, which would let a detector score well by noticing
the wrong thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Detector that *should* catch each class. The split between tool and
# reasoning is the point of the taxonomy: it separates detection the
# engineering provides from detection the model provides, and only the
# second moves when you swap models.
TOOL_DETECTORS = frozenset(
    {"assess_mesh_quality", "assess_residuals", "assess_y_plus", "check_mesh"}
)


@dataclass
class Probe:
    """One probe: an artefact, and the truth about what is wrong with it."""

    probe_id: str
    fault_class: str            # mesh | numerics | physics | setup | none
    fault_present: bool
    expected_detector: str      # a tool name, or "reasoning"
    artefact: str               # file name written into the probe directory
    content: str
    localization: str = ""      # which metric or field carries the fault
    note: str = ""
    files: dict[str, str] = field(default_factory=dict)

    @property
    def tool_detectable(self) -> bool:
        return self.expected_detector in TOOL_DETECTORS

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        # The artefact may sit in a subdirectory the tool expects to find it
        # in — `constant/turbulenceProperties`, not a bare log at the root.
        artefact = directory / self.artefact
        artefact.parent.mkdir(parents=True, exist_ok=True)
        artefact.write_text(self.content, encoding="utf-8")
        for name, text in self.files.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return directory


def clean_checkmesh_log() -> str:
    return (FIXTURES / "log.checkMesh.clean").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Mesh-quality faults (assess_mesh_quality / check_mesh should catch these)
# ---------------------------------------------------------------------------


def _set_non_orthogonality(text: str, maximum: float, average: float = 12.0) -> str:
    return re.sub(
        r"Mesh non-orthogonality Max: [0-9.eE+\-]+ average: [0-9.eE+\-]+",
        f"Mesh non-orthogonality Max: {maximum} average: {average}",
        text,
    )


def _set_skewness(text: str, value: float) -> str:
    return re.sub(
        r"Max skewness = [0-9.eE+\-]+.*", f"Max skewness = {value} ***Max skewness", text
    )


def _set_aspect_ratio(text: str, value: float) -> str:
    return re.sub(
        r"Max aspect ratio = [0-9.eE+\-]+.*", f"Max aspect ratio = {value} OK.", text
    )


def _mark_failed(text: str, n_checks: int = 1) -> str:
    return text.replace("Mesh OK.", f"Failed {n_checks} mesh checks.")


def severe_non_orthogonality(value: float = 78.4) -> Probe:
    """Non-orthogonality inside the severe band, with the face count present."""
    text = _set_non_orthogonality(clean_checkmesh_log(), value)
    text = text.replace(
        "Mesh OK.",
        " *Number of severely non-orthogonal (> 70 degrees) faces: 312.\nFailed 1 mesh checks.",
    )
    return Probe(
        probe_id=f"mesh_nonortho_{value}",
        fault_class="mesh",
        fault_present=True,
        expected_detector="assess_mesh_quality",
        artefact="log.checkMesh",
        content=text,
        localization="max_non_orthogonality",
        note="A solve on this mesh converges and is still wrong.",
    )


def borderline_non_orthogonality(value: float = 67.0) -> Probe:
    """Above the mesh-quality dict's limit but below checkMesh's warning.

    A genuinely contested band. OpenFOAM's ``meshQualityDict`` caps
    non-orthogonality at 65 while ``primitiveMeshCheck`` only calls a face
    severe past 70, and the consultant's "acceptable" band spans 60-70 —
    source-verified against both constants. So the tool passing this mesh
    is the documented contract, not a miss.

    That makes it a **reasoning** probe rather than a tool one: noticing
    that a mesh clears checkMesh while sitting above the limit snappy and
    mesh motion accept is a judgement call, and whether an agent raises it
    is exactly the kind of detection no threshold can provide.
    """
    text = _set_non_orthogonality(clean_checkmesh_log(), value)
    return Probe(
        probe_id=f"mesh_nonortho_borderline_{value}",
        fault_class="mesh",
        fault_present=True,
        expected_detector="reasoning",
        artefact="log.checkMesh",
        content=text,
        localization="max_non_orthogonality",
        note=(
            "Passes checkMesh and the consultant's acceptable band; exceeds "
            "meshQualityDict maxNonOrtho = 65. Tests judgement, not a threshold."
        ),
    )


def high_skewness(value: float = 6.2) -> Probe:
    text = _mark_failed(_set_skewness(clean_checkmesh_log(), value))
    return Probe(
        probe_id=f"mesh_skewness_{value}",
        fault_class="mesh",
        fault_present=True,
        expected_detector="assess_mesh_quality",
        artefact="log.checkMesh",
        content=text,
        localization="max_skewness",
    )


def extreme_aspect_ratio(value: float = 4200.0) -> Probe:
    text = _set_aspect_ratio(clean_checkmesh_log(), value)
    return Probe(
        probe_id=f"mesh_aspect_{value}",
        fault_class="mesh",
        fault_present=True,
        expected_detector="assess_mesh_quality",
        artefact="log.checkMesh",
        content=text,
        localization="max_aspect_ratio",
        note="Typical of over-stretched boundary-layer cells.",
    )


def clean_mesh(tag: str = "1") -> Probe:
    """A negative control. Without these, recall is meaningless."""
    return Probe(
        probe_id=f"mesh_clean_{tag}",
        fault_class="none",
        fault_present=False,
        expected_detector="assess_mesh_quality",
        artefact="log.checkMesh",
        content=clean_checkmesh_log(),
    )


def clean_mesh_moderate(tag: str = "2") -> Probe:
    """Clean, but not pristine — a good mesh is not a perfect one.

    A detector tuned to flag anything non-zero would score full recall and
    be useless. This is the control that catches that.
    """
    text = _set_non_orthogonality(clean_checkmesh_log(), 42.0, 8.5)
    text = _set_skewness(text, 1.4).replace(" ***Max skewness", " OK.")
    text = _set_aspect_ratio(text, 18.0)
    return Probe(
        probe_id=f"mesh_clean_moderate_{tag}",
        fault_class="none",
        fault_present=False,
        expected_detector="assess_mesh_quality",
        artefact="log.checkMesh",
        content=text,
    )


# ---------------------------------------------------------------------------
# Residual faults (assess_residuals should catch these)
# ---------------------------------------------------------------------------

_LOG_HEADER = """\
/*---------------------------------------------------------------------------*\\
| =========                 |                                                 |
\\*---------------------------------------------------------------------------*/
Build  : v2412
Exec   : simpleFoam
Create mesh for time = 0

"""


def _solver_log(series: dict[str, list[float]]) -> str:
    """Render residual histories as a solver log the parser will read."""
    n = len(next(iter(series.values())))
    out = [_LOG_HEADER]
    for i in range(n):
        out.append(f"Time = {i + 1}\n")
        for field_name, values in series.items():
            out.append(
                f"smoothSolver:  Solving for {field_name}, Initial residual = "
                f"{values[i]:.6e}, Final residual = {values[i] * 1e-3:.6e}, "
                "No Iterations 3\n"
            )
        out.append("ExecutionTime = 0.1 s\n\n")
    out.append("End\n")
    return "".join(out)


def _decay(start: float, factor: float, n: int) -> list[float]:
    return [start * factor**i for i in range(n)]


def converged_residuals(tag: str = "1") -> Probe:
    """A negative control: a clean five-order drop."""
    series = {
        "Ux": _decay(1.0, 0.90, 120),
        "Uy": _decay(0.99, 0.90, 120),
        "p": _decay(1.0, 0.89, 120),
    }
    return Probe(
        probe_id=f"residuals_converged_{tag}",
        fault_class="none",
        fault_present=False,
        expected_detector="assess_residuals",
        artefact="log.simpleFoam",
        content=_solver_log(series),
    )


def stalled_residuals() -> Probe:
    """Residuals flatten well above tolerance — the solve is going nowhere."""
    flat = [1e-3] * 60
    series = {
        "Ux": _decay(1.0, 0.85, 60) + flat,
        "Uy": _decay(1.0, 0.85, 60) + flat,
        "p": _decay(1.0, 0.85, 60) + [2e-3] * 60,
    }
    return Probe(
        probe_id="residuals_stalled",
        fault_class="numerics",
        fault_present=True,
        expected_detector="assess_residuals",
        artefact="log.simpleFoam",
        content=_solver_log(series),
        localization="p",
        note="Converged-looking to a reader who only checks the last value.",
    )


def diverging_residuals() -> Probe:
    series = {
        "Ux": _decay(1.0, 0.9, 20) + _decay(0.12, 1.35, 40),
        "Uy": _decay(1.0, 0.9, 20) + _decay(0.12, 1.30, 40),
        "p": _decay(1.0, 0.9, 20) + _decay(0.15, 1.40, 40),
    }
    return Probe(
        probe_id="residuals_diverging",
        fault_class="numerics",
        fault_present=True,
        expected_detector="assess_residuals",
        artefact="log.simpleFoam",
        content=_solver_log(series),
        localization="p",
    )


def oscillating_residuals() -> Probe:
    base = [1e-2 * (1.6 if i % 2 else 0.6) for i in range(80)]
    series = {"Ux": base, "Uy": list(base), "p": [v * 1.5 for v in base]}
    return Probe(
        probe_id="residuals_oscillating",
        fault_class="numerics",
        fault_present=True,
        expected_detector="assess_residuals",
        artefact="log.simpleFoam",
        content=_solver_log(series),
        localization="p",
        note="Under-relaxation too aggressive, or a genuinely unsteady flow.",
    )


def one_field_stalled() -> Probe:
    """Velocities converge, pressure does not.

    The failure a summary line hides: a run that looks converged unless you
    read every field.
    """
    series = {
        "Ux": _decay(1.0, 0.90, 120),
        "Uy": _decay(1.0, 0.90, 120),
        "p": _decay(1.0, 0.93, 40) + [5e-3] * 80,
    }
    return Probe(
        probe_id="residuals_one_field_stalled",
        fault_class="numerics",
        fault_present=True,
        expected_detector="assess_residuals",
        artefact="log.simpleFoam",
        content=_solver_log(series),
        localization="p",
    )


def clean_mesh_typical(tag: str = "3") -> Probe:
    """A realistic snappyHexMesh result: not pristine, not a problem."""
    text = _set_non_orthogonality(clean_checkmesh_log(), 54.0, 11.2)
    text = _set_skewness(text, 2.1).replace(" ***Max skewness", " OK.")
    text = _set_aspect_ratio(text, 45.0)
    return Probe(
        probe_id=f"mesh_clean_typical_{tag}",
        fault_class="none",
        fault_present=False,
        expected_detector="assess_mesh_quality",
        artefact="log.checkMesh",
        content=text,
    )


def clean_boundary_layer_mesh() -> Probe:
    """A wall-resolved boundary layer: high aspect ratio, and correct.

    Kept in the suite as a clean control even though the consultant flags
    it. Near-wall cells in a y+ ~ 1 mesh are deliberately stretched, and
    aspect ratios in the hundreds are the intended result — while the
    consultant's band calls 100-1000 "marginal", tracking checkMesh's own
    limit of 1000.

    Neither side is wrong: the tool flags for attention, and attention is
    reasonable. But it is a false alarm on a correct mesh, so it belongs in
    the false-alarm rate. Dropping it, or softening it to an aspect ratio
    the tool happens to like, would tune the benchmark to flatter the tool
    — which is the one thing a benchmark must not do.
    """
    text = _set_non_orthogonality(clean_checkmesh_log(), 48.0, 9.0)
    text = _set_skewness(text, 1.8).replace(" ***Max skewness", " OK.")
    text = _set_aspect_ratio(text, 320.0)
    return Probe(
        probe_id="mesh_clean_boundary_layer",
        fault_class="none",
        fault_present=False,
        expected_detector="assess_mesh_quality",
        artefact="log.checkMesh",
        content=text,
        note=(
            "Known false-alarm mode: aspect ratio 320 is intended in a "
            "wall-resolved mesh but lands in the consultant's marginal band."
        ),
    )


def still_running_residuals() -> Probe:
    """Dropping steadily, stopped early — unfinished, not broken.

    The control that separates "has not converged yet" from "will never
    converge". An assessor that treats every above-tolerance residual as a
    fault would flag every truncated run and be useless mid-solve.
    """
    series = {
        "Ux": _decay(1.0, 0.93, 45),
        "Uy": _decay(1.0, 0.93, 45),
        "p": _decay(1.0, 0.92, 45),
    }
    return Probe(
        probe_id="residuals_still_running",
        fault_class="none",
        fault_present=False,
        expected_detector="assess_residuals",
        artefact="log.simpleFoam",
        content=_solver_log(series),
        note="Residuals are still falling; the run was simply stopped early.",
    )


# ---------------------------------------------------------------------------
# Wall treatment: y+ against what the turbulence model assumes
# ---------------------------------------------------------------------------
#
# This class exists because it is the one an unaided model is least able to
# judge. Whether y+ = 12 is a defect is not a property of the number: it is
# wrong for a high-Re wall function, wrong for a low-Re model, and merely
# marginal for kOmegaSST's blended treatment. The fault is in the pairing,
# so a detector has to read the turbulence model and the wall data together.


def _turbulence_properties(ras_model: str) -> str:
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        "    class       dictionary;\n    object      turbulenceProperties;\n}\n"
        "\nsimulationType  RAS;\n\nRAS\n{\n"
        f"    RASModel        {ras_model};\n"
        "    turbulence      on;\n    printCoeffs     on;\n}\n"
    )


def _y_plus_dat(patches: dict[str, tuple[float, float, float]], time: float = 1000.0) -> str:
    header = (
        "# Wall y+\n"
        "# Time            patch           min             max             average\n"
    )
    rows = "".join(
        f"{time:<17g} {patch:<15s} {lo:<15g} {hi:<15g} {avg:<15g}\n"
        for patch, (lo, hi, avg) in patches.items()
    )
    return header + rows


def y_plus_probe(
    probe_id: str,
    ras_model: str,
    patches: dict[str, tuple[float, float, float]],
    *,
    fault_present: bool,
    localization: str = "",
    note: str = "",
) -> Probe:
    """One wall-treatment probe: a y+ table plus the model that has to live with it."""
    return Probe(
        probe_id=probe_id,
        fault_class="physics" if fault_present else "none",
        fault_present=fault_present,
        expected_detector="assess_y_plus",
        artefact="constant/turbulenceProperties",
        content=_turbulence_properties(ras_model),
        localization=localization,
        note=note,
        files={"postProcessing/yPlus/1000/yPlus.dat": _y_plus_dat(patches)},
    )


Y_PLUS_PROBES = (
    y_plus_probe(
        "yplus_wallfunction_in_sublayer",
        "kEpsilon",
        {"walls": (0.4, 2.1, 1.2)},
        fault_present=True,
        localization="walls",
        note=(
            "A high-Re wall function bridges the log layer. Landing the first "
            "cell in the viscous sublayer leaves it interpolating across a "
            "region it does not model."
        ),
    ),
    y_plus_probe(
        "yplus_wallfunction_buffer_layer",
        "kEpsilon",
        {"walls": (6.0, 18.4, 12.0)},
        fault_present=True,
        localization="walls",
        note="The buffer layer, where neither wall treatment is valid.",
    ),
    y_plus_probe(
        "yplus_wallfunction_far_outside_log_layer",
        "kEpsilon",
        {"walls": (120.0, 890.0, 410.0)},
        fault_present=True,
        localization="walls",
        note="Above the log layer; wall-shear fidelity is gone.",
    ),
    y_plus_probe(
        "yplus_lowre_model_on_wall_function_mesh",
        "SpalartAllmaras",
        {"aerofoil": (8.0, 41.0, 22.0)},
        fault_present=True,
        localization="aerofoil",
        note=(
            "The classic mismatch: a low-Re model integrating to the wall on "
            "a mesh built for wall functions."
        ),
    ),
    y_plus_probe(
        "yplus_sst_landed_in_buffer_layer",
        "kOmegaSST",
        {"airfoil": (3.0, 17.0, 9.0)},
        fault_present=True,
        localization="airfoil",
        note=(
            "kOmegaSST blends, so this degrades rather than breaks — the "
            "probe a detector tuned only for catastrophes will miss."
        ),
    ),
    y_plus_probe(
        "yplus_one_patch_of_three_wrong",
        "kEpsilon",
        {
            "lowerWall": (35.0, 96.0, 61.0),
            "upperWall": (40.0, 110.0, 72.0),
            "cylinder": (0.6, 3.4, 1.8),
        },
        fault_present=True,
        localization="cylinder",
        note=(
            "Two patches are fine and one is not. A detector that reports a "
            "single number for the case cannot localise this."
        ),
    ),
    y_plus_probe(
        "yplus_wallfunction_clean",
        "kEpsilon",
        {"walls": (38.0, 190.0, 95.0)},
        fault_present=False,
        note="Squarely in the log layer — what a wall-function mesh should look like.",
    ),
    y_plus_probe(
        "yplus_lowre_clean",
        "SpalartAllmaras",
        {"aerofoil": (0.12, 0.87, 0.4)},
        fault_present=False,
        note="Sublayer-resolved, as a low-Re model requires.",
    ),
    y_plus_probe(
        "yplus_sst_clean",
        "kOmegaSST",
        {"airfoil": (0.2, 0.94, 0.55)},
        fault_present=False,
        note="kOmegaSST at its best band.",
    ),
    y_plus_probe(
        "yplus_wallfunction_at_the_edge",
        "kEpsilon",
        {"walls": (31.0, 296.0, 140.0)},
        fault_present=False,
        note=(
            "Inside the band, but only just. A detector that flags this is "
            "raising a false alarm on an acceptable mesh."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Setup: a case that contradicts itself
# ---------------------------------------------------------------------------
#
# No consultant tool reads these. That is the point — the plan's taxonomy
# splits detection into what the engineering provides and what the model
# provides, and this class isolates the second. The tool arm reports them
# as not-run rather than as misses, so they never enter its recall
# denominator; only a model in the loop can answer them.
#
# Every fault here is a contradiction between two files that ship together,
# resolvable by reading them side by side and knowing what OpenFOAM does
# with each. None requires a mesh, a solve, or a reference.


def _control_dict(application: str, end_time: str, write_interval: str,
                  delta_t: str = "1") -> str:
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        "    class       dictionary;\n    object      controlDict;\n}\n\n"
        f"application     {application};\n"
        "startFrom       startTime;\nstartTime       0;\n"
        "stopAt          endTime;\n"
        f"endTime         {end_time};\n"
        f"deltaT          {delta_t};\n"
        "writeControl    timeStep;\n"
        f"writeInterval   {write_interval};\n"
        "purgeWrite      0;\nwriteFormat     ascii;\nwritePrecision  6;\n"
        "runTimeModifiable true;\n"
    )


def _fv_schemes(ddt: str) -> str:
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        "    class       dictionary;\n    object      fvSchemes;\n}\n\n"
        f"ddtSchemes\n{{\n    default         {ddt};\n}}\n\n"
        "gradSchemes\n{\n    default         Gauss linear;\n}\n\n"
        "divSchemes\n{\n    default         none;\n"
        "    div(phi,U)      bounded Gauss linearUpwind grad(U);\n}\n\n"
        "laplacianSchemes\n{\n    default         Gauss linear corrected;\n}\n"
    )


def _fv_solution(fields: tuple[str, ...]) -> str:
    blocks = "".join(
        f"    {f}\n    {{\n        solver          PBiCGStab;\n"
        "        preconditioner  DILU;\n        tolerance       1e-08;\n"
        "        relTol          0.1;\n    }\n"
        for f in fields
    )
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        "    class       dictionary;\n    object      fvSolution;\n}\n\n"
        f"solvers\n{{\n{blocks}}}\n\n"
        "SIMPLE\n{\n    nNonOrthogonalCorrectors 0;\n}\n"
    )


def _u_field(inlet: str, outlet: str) -> str:
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        "    class       volVectorField;\n    object      U;\n}\n\n"
        "dimensions      [0 1 -1 0 0 0 0];\n"
        "internalField   uniform (0 0 0);\n\n"
        "boundaryField\n{\n"
        f"    inlet\n    {{\n{inlet}    }}\n"
        f"    outlet\n    {{\n{outlet}    }}\n"
        "    walls\n    {\n        type            noSlip;\n    }\n}\n"
    )


def _p_field(inlet: str, outlet: str) -> str:
    return (
        "FoamFile\n{\n    version     2.0;\n    format      ascii;\n"
        "    class       volScalarField;\n    object      p;\n}\n\n"
        "dimensions      [0 2 -2 0 0 0 0];\n"
        "internalField   uniform 0;\n\n"
        "boundaryField\n{\n"
        f"    inlet\n    {{\n{inlet}    }}\n"
        f"    outlet\n    {{\n{outlet}    }}\n"
        "    walls\n    {\n        type            zeroGradient;\n    }\n}\n"
    )


def setup_probe(
    probe_id: str,
    artefact: str,
    content: str,
    files: dict[str, str],
    *,
    fault_present: bool,
    localization: str = "",
    note: str = "",
) -> Probe:
    return Probe(
        probe_id=probe_id,
        fault_class="setup" if fault_present else "none",
        fault_present=fault_present,
        expected_detector="reasoning",
        artefact=artefact,
        content=content,
        localization=localization,
        note=note,
        files=files,
    )


SETUP_PROBES = (
    setup_probe(
        "setup_steady_scheme_transient_solver",
        "system/controlDict",
        _control_dict("pimpleFoam", "10", "1", delta_t="0.001"),
        {"system/fvSchemes": _fv_schemes("steadyState")},
        fault_present=True,
        localization="ddtSchemes",
        note=(
            "A transient solver with the time derivative discretised away. "
            "pimpleFoam will march happily and every time directory will "
            "hold the same steady answer."
        ),
    ),
    setup_probe(
        "setup_transient_scheme_steady_solver",
        "system/controlDict",
        _control_dict("simpleFoam", "2000", "500"),
        {"system/fvSchemes": _fv_schemes("Euler")},
        fault_present=True,
        localization="ddtSchemes",
        note=(
            "The mirror image: a steady solver told to integrate in time, "
            "where its iteration counter is not a clock."
        ),
    ),
    setup_probe(
        "setup_write_interval_past_end_time",
        "system/controlDict",
        _control_dict("simpleFoam", "500", "1000"),
        {"system/fvSchemes": _fv_schemes("steadyState")},
        fault_present=True,
        localization="writeInterval",
        note=(
            "The run completes and writes nothing but the final time, so "
            "there is no history to judge convergence from."
        ),
    ),
    setup_probe(
        "setup_missing_solver_for_solved_field",
        "system/fvSolution",
        _fv_solution(("p", "U")),
        {
            "constant/turbulenceProperties": _turbulence_properties("kEpsilon"),
            "system/fvSchemes": _fv_schemes("steadyState"),
        },
        fault_present=True,
        localization="fvSolution",
        note=(
            "RAS k-epsilon is selected, so k and epsilon are solved for, and "
            "fvSolution has no entry for either. The run dies at startup."
        ),
    ),
    setup_probe(
        "setup_over_specified_inlet",
        "0/U",
        _u_field(
            "        type            fixedValue;\n"
            "        value           uniform (10 0 0);\n",
            "        type            fixedValue;\n"
            "        value           uniform (10 0 0);\n",
        ),
        {
            "0/p": _p_field(
                "        type            fixedValue;\n"
                "        value           uniform 0;\n",
                "        type            fixedValue;\n"
                "        value           uniform 0;\n",
            )
        },
        fault_present=True,
        localization="outlet",
        note=(
            "Velocity and pressure both fixed at both ends of an "
            "incompressible domain. The system is over-specified: nothing "
            "is left for the pressure equation to determine."
        ),
    ),
    setup_probe(
        "setup_no_pressure_reference",
        "0/p",
        _p_field(
            "        type            zeroGradient;\n",
            "        type            zeroGradient;\n",
        ),
        {
            "0/U": _u_field(
                "        type            fixedValue;\n"
                "        value           uniform (10 0 0);\n",
                "        type            zeroGradient;\n",
            )
        },
        fault_present=True,
        localization="p",
        note=(
            "The opposite failure: pressure is zeroGradient everywhere, so "
            "it is determined only up to a constant and the solve floats."
        ),
    ),
    setup_probe(
        "setup_clean_steady",
        "system/controlDict",
        _control_dict("simpleFoam", "2000", "100"),
        {
            "system/fvSchemes": _fv_schemes("steadyState"),
            "system/fvSolution": _fv_solution(("p", "U")),
        },
        fault_present=False,
        note="A steady case whose solver, scheme, and write controls agree.",
    ),
    setup_probe(
        "setup_clean_transient",
        "system/controlDict",
        _control_dict("pimpleFoam", "0.5", "50", delta_t="0.0001"),
        {
            "system/fvSchemes": _fv_schemes("Euler"),
            "system/fvSolution": _fv_solution(("p", "U")),
        },
        fault_present=False,
        note=(
            "A transient case with a small deltaT and a write interval "
            "counted in steps, not seconds — unusual-looking and correct."
        ),
    ),
    setup_probe(
        "setup_clean_write_once_at_the_end",
        "system/controlDict",
        _control_dict("simpleFoam", "1000", "1000"),
        {"system/fvSchemes": _fv_schemes("steadyState")},
        fault_present=False,
        note=(
            "writeInterval equal to endTime looks like the interval-past-end "
            "fault and is not: the run writes once, at the end, which is all "
            "a steady case needs. A detector that flags this is reading the "
            "shape of the numbers rather than what they do."
        ),
    ),
    setup_probe(
        "setup_clean_purged_history",
        "system/controlDict",
        _control_dict("pimpleFoam", "100", "10", delta_t="0.01").replace(
            "purgeWrite      0;", "purgeWrite      2;"
        ),
        {"system/fvSchemes": _fv_schemes("Euler")},
        fault_present=False,
        note=(
            "purgeWrite keeps only the last two time directories. It looks "
            "like losing the history and is the ordinary way to run a long "
            "transient without filling a disk."
        ),
    ),
    setup_probe(
        "setup_clean_inlet_outlet_pair",
        "0/U",
        _u_field(
            "        type            fixedValue;\n"
            "        value           uniform (10 0 0);\n",
            "        type            zeroGradient;\n",
        ),
        {
            "0/p": _p_field(
                "        type            zeroGradient;\n",
                "        type            fixedValue;\n"
                "        value           uniform 0;\n",
            )
        },
        fault_present=False,
        note=(
            "The standard incompressible pairing: velocity fixed where "
            "pressure floats, and the reverse at the outlet."
        ),
    ),
)


MESH_PROBES = (
    severe_non_orthogonality(),
    severe_non_orthogonality(85.0),
    borderline_non_orthogonality(),
    high_skewness(),
    high_skewness(4.6),
    extreme_aspect_ratio(),
    clean_mesh(),
    clean_mesh_moderate(),
    clean_mesh_typical(),
    clean_boundary_layer_mesh(),
)

RESIDUAL_PROBES = (
    stalled_residuals(),
    diverging_residuals(),
    oscillating_residuals(),
    one_field_stalled(),
    converged_residuals(),
    converged_residuals("2"),
    still_running_residuals(),
)

ALL_PROBES = MESH_PROBES + RESIDUAL_PROBES + Y_PLUS_PROBES + SETUP_PROBES
