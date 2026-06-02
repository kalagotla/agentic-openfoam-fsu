# OpenFOAM MCP server

OpenFOAM CLI and dictionary I/O wrapped as typed MCP tools.

## Tools

| Tool | Purpose |
|------|---------|
| `list_tutorials` | Browse `$FOAM_TUTORIALS` for case templates |
| `read_tutorial_file` | Read a single dictionary from a tutorial |
| `prepare_case` | Create the work directory; refuses to clobber a prior attempt unless `overwrite=True` |
| `write_dict` | Write a dictionary or field into `system/`, `constant/`, or `0/` (`subdir` argument) |
| `run_blockmesh` | Generate a structured mesh from `system/blockMeshDict` |
| `check_mesh` | Run `checkMesh`, return parsed quality metrics |
| `prepare_surface_mesh` | Drop STL into `constant/triSurface/` + run `surfaceCheck` |
| `run_snappy_hex_mesh` | Run `snappyHexMesh`, return per-phase outcomes + cell count |
| `decompose_par` | Write `decomposeParDict` + decompose for parallel run |
| `reconstruct_par` | Reassemble time directories after a parallel run |
| `run_solver` | Run a solver — serial (`n_procs=1`) or `mpirun -np N` |
| `get_residuals` | Parse residual history (summary mode by default) |
| `export_field_image` | Render a field to PNG |
| `record_step` | Append a timestamped entry to `<case>/REPORT.md` (decision visible, reasoning in a collapsible `<details>` block) |
| `finalize_report` | Cap the run with a top verdict banner and a compact one-line-per-decision index; refreshes both on re-call |
| `archive_case` | Copy case inputs to `cases/examples/<name>/baseline/` (skips time dirs, mesh, logs) |

All tools return `{"success": bool, ...}` and never raise on OpenFOAM failures — the agent reads `reason` and `log_tail` and recovers.

## Running

```bash
uv sync --all-packages
uv run --package openfoam-mcp python -m openfoam_mcp
```

Stdio transport — what Claude Code, Claude Desktop, and other MCP clients expect by default.

## Testing

```bash
uv run pytest servers/openfoam/tests
```

OpenFOAM-dependent tests skip when `blockMesh` isn't on PATH; source it (`of2412`) to exercise them.

## Extending

1. Write the function in `src/openfoam_mcp/tools.py` — return a dict, never raise.
2. Register it in `src/openfoam_mcp/server.py` with `mcp.tool()(tools.your_new_tool)`.
3. Add a test in `tests/test_tools.py`.

Tool docstrings drive agent selection — keep them tight. A docstring that needs scrollbars means the tool is too big and should be split.
