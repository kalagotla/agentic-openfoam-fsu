"""FastMCP server wiring for the Consultant tool set."""

from __future__ import annotations

from fastmcp import FastMCP

from consultant_mcp import tools

mcp = FastMCP(
    name="consultant",
    instructions=(
        "Reasoning over outputs from the OpenFOAM and Validation servers. "
        "This server does not drive OpenFOAM and does not compare against "
        "reference data — its job is to turn structured returns "
        "(checkMesh metrics, tutorial paths) into cited CFD-domain "
        "verdicts that fill the consultant schema on "
        "``openfoam.record_step`` (decision / why / alternatives / "
        "when_it_breaks).\n"
        "\n"
        "``assess_mesh_quality(case_path)`` parses ``log.checkMesh`` "
        "(written by ``openfoam.check_mesh``) and returns a per-metric "
        "verdict — good / acceptable / marginal / poor — for non-"
        "orthogonality, skewness, aspect ratio, and severe-face count. "
        "Each verdict carries a threshold band, a recommendation, and "
        "citation tags that resolve via ``citation_sources``. Use the "
        "``summary`` field directly in the ``why`` argument of "
        "``record_step``.\n"
        "\n"
        "``assess_residuals(case_path)`` reads the solver log and "
        "classifies each field's convergence pattern as converged / "
        "still_running / stalled / oscillating / diverging — with "
        "CFD-domain recommendations (URF tuning, scheme order, mesh "
        "quality). Call after a solver run to fill ``why`` on the "
        "convergence ``record_step``.\n"
        "\n"
        "``assess_y_plus(case_path, time)`` checks wall-patch y+ against "
        "the turbulence model's wall-treatment assumption (high-Re wall "
        "function vs low-Re resolved vs kOmegaSST hybrid). Reads "
        "``postProcessing/yPlus/<time>/yPlus.dat`` — if missing, the "
        "agent must first run ``<solver> -postProcess -func yPlus -time "
        "<time>`` via the OpenFOAM server. This tool does not invoke "
        "OpenFOAM itself.\n"
        "\n"
        "``get_tutorial_annotation(tutorial_path)`` fetches the hand-"
        "authored annotation for an $FOAM_TUTORIALS entry. Call it "
        "whenever you pick a tutorial as a structural template, and "
        "quote the body into the consultant fields. If no annotation "
        "exists, do NOT invent rationale — record the gap on the audit "
        "trail by leaving the consultant fields empty (record_step will "
        "render them as 'uncited choice'). ``list_tutorial_annotations`` "
        "lets you discover what's available.\n"
        "\n"
        "``draft_annotation_from_report(case_path, tutorial_path, ...)`` "
        "produces a candidate tutorial annotation from a completed "
        "case's REPORT.md. Parses the per-step decision entries (the full "
        "decision / why / alternatives / when-it-breaks + citations, not "
        "the compact index) into the decision table, and writes a "
        "``.draft.md`` under ``corpus/<tutorial_path>``. Fill the "
        "frontmatter you know via the optional args (``solver``, "
        "``physics``, ``geometry``, ``references``, and your proposed "
        "``suitable_for`` / ``not_suitable_for``) so the human reviews "
        "rather than fills blanks; omitted fields stay ``<fill in>`` "
        "placeholders. The ``.draft.md`` suffix keeps it out of "
        "``get_tutorial_annotation`` until a human confirms the proposals, "
        "generalises scenario-specific language, and renames it to "
        "``.md`` to promote.\n"
        "\n"
        "``flag_uncited_claims(case_path)`` is the end-of-run integrity "
        "audit: it scans REPORT.md (or a corpus entry via ``markdown_path``) "
        "for claims that appeal to outside authority ('the literature', "
        "'well-known'), state a regime boundary with a number (a transition / "
        "critical-Reynolds / Hopf value), or admit being uncited — while "
        "carrying no citation — and for citations that don't resolve to a "
        "``corpus/references/`` entry. It is a heuristic lint that surfaces "
        "candidates, not a judge. The standing rule it backs: a claimed fact "
        "(a number, threshold, regime boundary) must be EITHER cited OR "
        "derived from first principles — never asserted from unsourced recall. "
        "A citation must resolve to a source in ``corpus/references/`` (add "
        "any new source you actually use to "
        "``corpus/references/manifest.json``); if you have only unsourced "
        "recall, reason from first principles or drop the specific claim. Run "
        "it after ``finalize_report`` and resolve every flag (derive or "
        "cite).\n"
        "\n"
        "Every tool returns ``{success: bool, ...}``. On failure, read "
        "``reason`` and ``detail`` and recover."
    ),
)

mcp.tool()(tools.assess_mesh_quality)
mcp.tool()(tools.assess_residuals)
mcp.tool()(tools.assess_y_plus)
mcp.tool()(tools.get_tutorial_annotation)
mcp.tool()(tools.list_tutorial_annotations)
mcp.tool()(tools.draft_annotation_from_report)
mcp.tool()(tools.flag_uncited_claims)
