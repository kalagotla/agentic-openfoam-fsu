"""FastMCP server wiring for the Validation tool set."""

from __future__ import annotations

from fastmcp import FastMCP

from validation_mcp import tools

mcp = FastMCP(
    name="validation",
    instructions=(
        "Reference-data lookup and case-agnostic comparison primitives. "
        "Use ``list_references`` to enumerate available benchmark datasets "
        "and ``read_reference`` to fetch one by name. ``compare_profiles`` "
        "takes raw arrays (sim and reference) and reports L2 / L_inf error "
        "vs a tolerance; ``compare_scalar`` does the same for a single "
        "coefficient (Cl/Cd, reattachment length, a peak value) where there "
        "is no profile to interpolate. ``check_convergence`` classifies a "
        "residual history. Every tool returns ``{success: bool, ...}``. Nothing here "
        "is physics-specific; case-specific metrics (reattachment, Strouhal, "
        "Nusselt, ...) are the agent's job using OpenFOAM postProcessing "
        "output plus inline math."
    ),
)

mcp.tool()(tools.list_references)
mcp.tool()(tools.read_reference)
mcp.tool()(tools.compare_profiles)
mcp.tool()(tools.compare_scalar)
mcp.tool()(tools.check_convergence)
mcp.tool()(tools.run_analysis)
