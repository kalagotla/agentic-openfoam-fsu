"""FastMCP server wiring for the Research-assistant tool set."""

from __future__ import annotations

from fastmcp import FastMCP

from research_assistant_mcp import tools

mcp = FastMCP(
    name="research_assistant",
    instructions=(
        "Tools for the OpenFOAM source-code research loop. Use when "
        "the researcher wants to author custom C++ (boundary "
        "conditions, function objects, turbulence models, solvers) "
        "and compile it. These tools do NOT generate code or decide "
        "what to extend — the researcher writes the C++; the tools "
        "make the build loop fast and the OpenFOAM source-tree "
        "examples discoverable.\n"
        "\n"
        "Typical flow:\n"
        "1. ``discover_user_lib_path()`` to confirm OpenFOAM is "
        "sourced and learn the fork (ESI v2412 / Foundation 12+13 "
        "have ABI-incompatible libraries — check before reusing a "
        "previously-built .so).\n"
        "2. ``find_examples_of_base_class(base)`` to locate the "
        "closest existing derivation in $FOAM_SRC / $FOAM_APP. Read "
        "its header via the OpenFOAM server's ``read_tutorial_file`` "
        "or by passing the path to Read directly. Model the new "
        "class on it.\n"
        "3. Author the .H, .C, Make/files, Make/options via the "
        "OpenFOAM server's ``write_dict`` (or Write) — this server "
        "does not own dictionary-writing.\n"
        "4. ``wmake_and_report(directory)`` — runs wmake, parses "
        "errors into structured returns (missing_header, "
        "missing_library, undefined_symbol, compile_error) with "
        "hints. On failure, surface the structured errors to the "
        "researcher with a record_step entry; do NOT auto-retry "
        "without the researcher's input.\n"
        "\n"
        "Every tool returns ``{success: bool, ...}``. On failure, "
        "read ``reason`` and ``detail`` (or the ``errors`` list on a "
        "wmake failure) and recover."
    ),
)

mcp.tool()(tools.wmake_and_report)
mcp.tool()(tools.find_examples_of_base_class)
mcp.tool()(tools.discover_user_lib_path)
