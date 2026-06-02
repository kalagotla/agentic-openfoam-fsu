# Accelerating CFD Simulations with Agentic AI and OpenFOAM

AIAA Aviation 2026 • San Diego • 8–12 June • 90-minute session

## What you saw

A live CFD workflow driven by an AI agent through four MCP servers, validated against Ghia, Ghia & Shin (1982) at Re=400. The agent picked a structural template from `$FOAM_TUTORIALS`, cited the tutorial annotation, generated a mesh, ran simpleFoam, sampled centerline profiles, and compared to Ghia — within a 5 % L2 tolerance band. The same servers also run under a local Ollama model for ITAR-sensitive workflows.

## Take it home

```
https://github.com/kalagotla/agentic-openfoam
```

You do **not** need Claude Code. The repo ships a 300-line Python harness that drives the servers via the Anthropic API or local Ollama; Claude Desktop, Cursor, Continue.dev, and Cline also work. See [`runtime-options.md`](runtime-options.md).

Install in one of three ways: native (~5 min if OpenFOAM v2412 is already installed), Docker (~25 min one-time build), or VS Code Dev Container (~25 min one-time build). Commands in the README.

## Tool surface

33 tools across four servers, each returning `{success: bool, ...}`:

- **openfoam** (17) — `list_tutorials` / `read_tutorial_file` / `prepare_case` / `write_dict` / `copy_tutorial_dict` / `run_blockmesh` / `check_mesh` / `prepare_surface_mesh` / `run_snappy_hex_mesh` / `decompose_par` / `reconstruct_par` / `run_solver` / `get_residuals` / `export_field_image` / `record_step` / `finalize_report` / `archive_case`
- **validation** (6) — `list_references` / `read_reference` / `compare_profiles` / `compare_scalar` / `check_convergence` / `run_analysis`
- **consultant** (7) — `assess_mesh_quality` / `assess_residuals` / `assess_y_plus` / `get_tutorial_annotation` / `list_tutorial_annotations` / `draft_annotation_from_report` / `flag_uncited_claims`
- **research_assistant** (3) — `wmake_and_report` / `find_examples_of_base_class` / `discover_user_lib_path`

Full surface and per-tool signatures in [`architecture.md`](architecture.md).

## Scenarios shipped

| Scenario | Geometry | Reference | Laptop runtime |
|---|---|---|---|
| `lid-cavity.yaml` | blockMesh cavity | Ghia 1982 centerline profiles | < 1 min |
| `flat-plate.yaml` | blockMesh flat plate | qualitative (log-law, residual drop) | ~ 2 min |
| `pitz-daily.yaml` | blockMesh backward-facing step | Armaly 1983 reattachment length (x_r/h, laminar Re≈800) | ~ 1–2 min |
| `naca-0012.yaml` | STL + snappyHexMesh, 2-D | XFOIL Cl/Cd polar at Re=1e6 | ~ 10–15 min |
| `onera-m6.yaml` | STL + snappyHexMesh, 3-D swept wing | qualitative ranges (Cl, Cd, suction-peak) | ~ 30–45 min on 4 cores |

STL-driven cases ship procedural Python geometry generators (stdlib only) — fork for NACA 4412, a different M6 aspect ratio, etc.

## Design principles

- **Validation drives correction; agents do not anticipate.** First attempt uses the tutorial's choices verbatim outside what the scenario explicitly demands. Mesh resolution, schemes, URFs, turbulence model — left alone until a check fails. Each subsequent fix is a separate `record_step` citing the miss.
- **Validation failure never auto-retries.** The failure surfaces with full consultant fields; the researcher decides.
- **Decisions carry consultant fields.** Every `record_step` that records a choice fills *decision / why / alternatives / when-it-breaks*. Empty fields render as `_uncited choice_` so corpus gaps are visible.
- **Structured errors, not exceptions.** Tools return dicts; agents reason about `reason` and recover.
- **Context budget is finite.** Scalar summaries, sampled profiles, exported images — never raw fields.
- **Live audit trail.** `record_step` writes collapsible entries to `<case>/REPORT.md` (decision visible, reasoning one click away); `tail -f` during a run shows the chain unfold, and `finalize_report` caps it with a verdict banner and a compact decisions index.

## Extending

- **Custom OpenFOAM code.** [`cases/examples/custom-bc-example/`](../cases/examples/custom-bc-example/) compiles a parabolic inlet BC; [`how-to-extend-openfoam.md`](how-to-extend-openfoam.md) catalogues the five most common build failures.
- **HPC.** Asynchronous submit/poll/tail drops in by replacing `run_solver` with a job-queue wrapper; the rest of the agent loop is unchanged.
- **New reference data.** Drop a JSON under any case's `reference/`. No server edits.
- **New tutorial annotation.** Run the case, call `consultant.draft_annotation_from_report`, review and edit the `.draft.md`, rename to `.md` to promote.

## Citation

```bibtex
@misc{kalagotla2026agenticopenfoam,
  author       = {Kalagotla, Dilip},
  title        = {Accelerating {CFD} Simulations with Agentic {AI} and {OpenFOAM}},
  howpublished = {Workshop, AIAA Aviation Forum},
  year         = {2026},
  month        = jun,
  address      = {San Diego, CA, USA},
  note         = {8--12 June 2026}
}
```

## Contact

Dilip Kalagotla — dilip.kalagotla@gmail.com
