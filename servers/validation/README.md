# Validation MCP server

CFD benchmark reference data and case-agnostic comparison primitives. Anything physics-specific (reattachment lengths, Strouhal numbers, Nusselt correlations) lives next to the case it applies to, not here.

## Tools

| Tool | Purpose |
|------|---------|
| `list_references` | Enumerate datasets under any `reference/*.json` below `cases/` |
| `read_reference` | Fetch one dataset by name (filename stem) |
| `compare_profiles` | L2 / L∞ error between two arrays, with a tolerance gate |
| `check_convergence` | Classify a residual history: converged / diverged / stalled / still_running |
| `run_analysis` | Run an agent-authored analysis script and capture its metrics + plots |

All tools return `{"success": bool, ...}`.

## Analysis scripts (`run_analysis`)

A fixed set of comparison primitives can't span every CFD metric (Cd/Cl, Cp,
Cf, reattachment, Strouhal, …). So the agent authors a per-case Python script
— `<case>/analysis/validate.py` — that extracts the case-specific quantity
from solver output, plots overlays into `postProcessing/analysis/`, and
**scores via `compare_profiles`** (it does not re-implement the error norm).
`run_analysis(case_path)` runs it the same way in Claude Code and the bare
harness, so the archived artifact is identical and the validation replays.

The script's contract: cwd is the case dir; imports limited to stdlib + numpy
+ matplotlib + `validation_mcp`; load reference arrays via `read_reference`
(cwd-independent); read solver output **files directly** (this server is not
launched with OpenFOAM sourced, so `postProcess` is unavailable — sample via a
`controlDict` functionObject during the run instead); print `<<<ANALYSIS_RESULT>>>`
then one JSON line `{"metrics": {...}, "plots": [...]}` as the last output;
exit non-zero on any extraction failure.

**Execution is hardened, not sandboxed.** The script runs in its own process
group (killed as a unit on timeout, catching forked grandchildren), under
best-effort `RLIMIT_AS` / `RLIMIT_CPU` / `RLIMIT_FSIZE` caps, with a minimal
allow-listed environment (server secrets are not passed through) and headless
single-threaded numerics (`MPLBACKEND=Agg`, BLAS threads = 1). **Network is NOT
blocked** — the contract requires scripts not use it, and you are trusting the
script you authored. This is soft isolation for honest-mistake containment, not
a jail. Dependencies: numpy + matplotlib.

## Reference data shipped

| Name | Case | Source |
|------|------|--------|
| `ghia_1982` | `lid-cavity` | Ghia, Ghia & Shin, *JCP* 48 (1982) — cavity centerline u(y), v(x) at Re=100, 400 |
| `reattachment_length` | `examples/pitz-daily` | Armaly et al., *JFM* 127 (1983) — BFS x_r/h vs Re |
| `xfoil_polar` | `examples/naca-0012` | XFOIL v6.99 polar at Re_c = 1e6 |
| `agard_ar_138_qualitative` | `examples/onera-m6` | Qualitative Cl / Cd / Cp targets |

Each reference's content is the case's concern; the server discovers and serves the JSON.

## Running

```bash
uv sync --all-packages
uv run --package validation-mcp python -m validation_mcp
```

## Testing

```bash
uv run pytest servers/validation/tests
```

Pure numerical + filesystem checks — no OpenFOAM required.

## Extending

**New reference dataset.** Drop a JSON at `cases/<...>/reference/<name>.json`. The basename (without `.json`) is the reference name. Self-describing JSONs are the convention: include `primary_citation`, `description`, the arrays, units, and tolerance guidance. Worked examples: `cases/lid-cavity/reference/ghia_1982.json` (multi-dataset) and `cases/examples/pitz-daily/reference/reattachment_length.json` (single-dataset). No server edits.

**New comparison primitive.** Only if it's genuinely case-agnostic — works on arrays without knowing what they represent. Anything whose docstring needs a flow type or geometry to be intelligible belongs in the agent's inline reasoning or a case-specific script.
