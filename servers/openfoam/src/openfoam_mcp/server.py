"""FastMCP server wiring for the OpenFOAM tool set.

This file is deliberately thin — the work lives in ``tools.py``. The server
only exists to register tools and expose the MCP interface.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openfoam_mcp import tools

mcp = FastMCP(
    name="openfoam",
    instructions=(
        "Tools for driving OpenFOAM simulations. Browse the tutorials library "
        "with ``list_tutorials`` / ``read_tutorial_file`` to find case "
        "templates.\n"
        "\n"
        "Authoring order matters. FIRST call ``prepare_case(case_path)`` to "
        "create the work directory — the authoring tools (``write_dict`` / "
        "``copy_tutorial_dict``) require it to exist, and ``prepare_case`` "
        "refuses to clobber a prior attempt's directory unless you pass "
        "``overwrite=True``. Do NOT create the case directory by hand; use "
        "``prepare_case`` so that guard runs. Then: OpenFOAM utilities "
        "(including ``blockMesh`` "
        "and ``checkMesh``) read ``system/controlDict``, ``system/fvSchemes``, "
        "and ``system/fvSolution`` at startup — so author those (via "
        "``write_dict`` with the default ``subdir=\"system\"``) BEFORE the "
        "first ``run_blockmesh`` call. Also write ``constant/`` (via "
        "``write_dict`` with ``subdir=\"constant\"``: transportProperties, "
        "turbulenceProperties) and ``0/`` (``subdir=\"0\"``: U, p, k, omega, "
        "nut, ...) before solving.\n"
        "\n"
        "Mesh strategy depends on geometry. For structured Cartesian-block "
        "domains, use ``run_blockmesh``. For arbitrary CAD/STL geometry "
        "(airfoils, wings, full aircraft), use ``prepare_surface_mesh`` to "
        "drop an STL into ``constant/triSurface/`` and ``run_snappy_hex_mesh`` "
        "to carve the geometry out of a background blockMesh. ALWAYS run "
        "``check_mesh`` after either path — a converged solver on a bad mesh "
        "is still wrong. For cell counts > 1M (typical for 3D RANS), "
        "decompose with ``decompose_par`` (then ``run_solver`` with "
        "``n_procs > 1`` launches mpirun), and ``reconstruct_par`` after to "
        "stitch the time directories back together for postprocessing. "
        "Drive the solver with ``run_solver`` and monitor "
        "with ``get_residuals`` (default summary mode keeps your context "
        "small; only pass ``summary=False`` if you need the full "
        "trajectory). Render fields with ``export_field_image``.\n"
        "\n"
        "CRITICAL: narrate every meaningful step by calling ``record_step``. "
        "This writes to ``<case>/REPORT.md`` which the user watches live "
        "during the workshop. Record geometry choice, mesh stats, checkMesh "
        "outcome, BC setup, solver convergence, validation results, and "
        "post-processing. When you retry after a failure, record the fix "
        "with ``status=\"fixed\"`` and ``retry_of=\"<prior title>\"`` — the "
        "audit trail of \"tried X, hit Y, applied Z\" is the whole point.\n"
        "\n"
        "Whenever the step records a *decision* — choosing a mesh template, "
        "a scheme, a BC, a turbulence model, a solver — fill the four "
        "consultant fields on ``record_step``: ``decision`` (one line on "
        "what was chosen), ``why`` (the rationale; must cite a tutorial "
        "annotation or paper via ``citations=[...]``), ``alternatives`` "
        "(what else was considered + tradeoffs), and ``when_it_breaks`` "
        "(regimes where this choice would be wrong). Empty fields are "
        "rendered explicitly as ``_uncited choice_`` / ``_no alternatives "
        "surfaced_`` / ``_failure modes not characterized_`` and listed in "
        "the return as ``consultant_gaps`` — leaving a gap is sometimes "
        "honest, but never silent. Do not invent CFD wisdom to fill the "
        "fields; cite or flag. Each entry renders the decision in the open "
        "and folds why / alternatives / when-it-breaks into a ``<details>`` "
        "block (added for you). Write prose with literal ``<`` ``>`` ``&`` — "
        "do not HTML-escape them.\n"
        "\n"
        "Close the run with ``finalize_report(case_path)`` once, after "
        "validation. It adds a verdict banner near the top of REPORT.md and "
        "a compact one-line-per-decision index at the end (phase · decision "
        "· cites · gaps); the full reasoning stays in each step's collapsible "
        "block. Re-call it to refresh both after recording more steps.\n"
        "\n"
        "For human-in-the-loop work, use ``status=\"pending_review\"`` to "
        "propose a decision and wait for the researcher's approval before "
        "executing the next phase. The entry renders with a "
        "``[PENDING REVIEW]`` marker. Do not auto-retry on validation "
        "failure — stop, surface the failure with full consultant fields, "
        "and ask the researcher how to proceed.\n"
        "\n"
        "Every tool returns ``{success: bool, ...}``. Check ``success`` and "
        "read ``log_tail`` / ``reason`` on failure to diagnose.\n"
        "\n"
        "End-of-run handoff. When a case completes and the user is "
        "satisfied with the result, do NOT autonomously copy the case "
        "anywhere. Ask the user explicitly whether to: (a) archive the "
        "case to ``cases/examples/<name>/baseline/`` via "
        "``archive_case(case_path, archive_name)`` and/or (b) draft a "
        "tutorial annotation via ``consultant.draft_annotation_from_report"
        "(case_path, tutorial_path)``. Both default to NO. The user owns "
        "these promotions; both are reversible-by-rename but should never "
        "be invoked without explicit approval."
    ),
)

# Tool registration. FastMCP uses decorators, so we apply them here rather
# than scattering @mcp.tool across tools.py (which keeps tools.py testable
# without a server context).
mcp.tool()(tools.list_tutorials)
mcp.tool()(tools.read_tutorial_file)
mcp.tool()(tools.prepare_case)
mcp.tool()(tools.write_dict)
mcp.tool()(tools.copy_tutorial_dict)
mcp.tool()(tools.run_blockmesh)
mcp.tool()(tools.check_mesh)
mcp.tool()(tools.prepare_surface_mesh)
mcp.tool()(tools.run_snappy_hex_mesh)
mcp.tool()(tools.decompose_par)
mcp.tool()(tools.reconstruct_par)
mcp.tool()(tools.run_solver)
mcp.tool()(tools.get_residuals)
mcp.tool()(tools.export_field_image)
mcp.tool()(tools.record_step)
mcp.tool()(tools.finalize_report)
mcp.tool()(tools.archive_case)
