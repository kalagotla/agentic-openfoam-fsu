# Research-assistant MCP server

Build-loop and source-tree-discovery tools for researchers writing custom OpenFOAM C++ (boundary conditions, function objects, turbulence models, solvers). Does **not** generate code, choose designs, or auto-retry compile failures — the researcher stays in control of the C++; the agent handles the mechanical parts.

Operates on the user's `$WM_PROJECT_USER_DIR` (typically `~/OpenFOAM/<user>-v2412/`) and reads from `$FOAM_SRC` / `$FOAM_APP`. Does not vendor OpenFOAM source.

## Tools

- **`wmake_and_report(directory)`** — runs `wmake`, captures stdout+stderr, returns a structured parse: succeeded files, failed files, compiler/linker errors (file, line, type, message), and the log tail. Lets the agent iterate on a custom BC by reading structured errors instead of raw build output.

- **`find_examples_of_base_class(base_class, max_results=10)`** — greps `$FOAM_SRC` and `$FOAM_APP` for derivations of a base class (e.g. `fixedValueFvPatchVectorField`, `eddyViscosity<RASModel<BasicTurbulenceModel>>`). Returns the candidate `.H` files plus the derived class name parsed from each — the fastest way to model a new BC on the closest existing one.

- **`discover_user_lib_path()`** — returns `$FOAM_USER_LIBBIN`, `$FOAM_USER_APPBIN`, `$WM_PROJECT_USER_DIR`, `$WM_PROJECT_VERSION`. Tells the agent where a custom library will land and detects ESI vs Foundation fork before compiling (their `.so` files are not drop-in compatible).

## Running

```bash
uv sync --all-packages
uv run --package research-assistant-mcp python -m research_assistant_mcp
```

## Testing

```bash
uv run pytest servers/research_assistant/tests
```

End-to-end `wmake` tests skip when OpenFOAM isn't sourced; source it (`of2412`) to exercise them against `cases/examples/custom-bc-example/lib/`.

## Design rules

1. Every tool returns `{"success": bool, ...}`; never raise.
2. **Do not vendor OpenFOAM source.** Tools operate on `$WM_PROJECT_USER_DIR` and read from `$FOAM_SRC`.
3. **Researcher decides what to compile.** No code generation, no auto-retry on compile failure — report the structured error and let the researcher choose.
