# Pitz-Daily backward-facing step

Backward-facing step (BFS) case with Armaly 1983 reference data. Adapted directly from the OpenFOAM v2412 tutorial `incompressible/simpleFoam/pitzDaily`.

## Geometry

Imported directly from the OpenFOAM v2412 tutorial `incompressible/simpleFoam/pitzDaily`. Key dimensions (from `system/blockMeshDict`, `scale 0.001`):

- Inlet channel height H₁ = 25.4 mm
- Step height **h = 25.4 mm** (lower wall drops from y=0 to y=−25.4 mm at x=0)
- Expansion ratio H₂/H₁ = 2 (matches Armaly's experimental geometry)
- Domain extends to x = 290 mm with a downstream contraction (the "Pitz-Daily" combustor narrowing) — far enough from x=0 that it does not affect reattachment.

## Reynolds number

Tutorial defaults (kEpsilon RANS):

- U_inlet = 10 m/s, ν = 1×10⁻⁵ m²/s, h = H₁ = 25.4 mm
- Hydraulic diameter D = 2·H₁ = 0.0508 m
- **Re = U·D/ν ≈ 50,800** (Armaly's convention)

Well past Armaly's measured range (Re ≲ 8000) but firmly inside the fully-turbulent plateau where x_r/h ≈ 6 (Driver–Seegmiller 1985, Le–Moin–Kim DNS). Validate against the plateau value, not a specific measured point.

Lower Re isn't worth the trouble: pitzDaily's straight downstream channel is only ~8 step heights before the contraction at x = 206 mm. Armaly's laminar x_r/h ≈ 11.5 at Re=800 wouldn't fit; Re=6600 (x_r/h ≈ 6) does but needs custom inlet tuning. Tutorial defaults at Re ≈ 50,800 also give x_r/h ≈ 5–6 with kEpsilon and converge cleanly.

**Validation target:** x_r/h ≈ 6 ± 15%. kEpsilon under-predicts x_r/h by ~10–15% on BFS at fully-turbulent Re — known model deficiency, not setup error.

## Directory layout

```
pitz-daily/
├── README.md
├── reference/                       # Armaly 1983 (digitized)
│   ├── README.md
│   └── reattachment_length.json
├── baseline/                        # known-good case — read-only reference
│   ├── Allrun / Allclean
│   ├── 0/ constant/ system/
└── validation.py                    # headless validation against reference
```

`baseline/` is the known-good reference. The agent never copies from it; it authors a fresh case in `cases/work/<scenario>/` and is compared against both Armaly's data and the baseline solution.

## Run the baseline

```bash
of2412
cd cases/examples/pitz-daily/baseline
./Allrun
```

Expected: kEpsilon `simpleFoam` converges within `endTime`; `validation.py` reports x_r/h within ~15% of 6.

## Gotchas

- **Don't use `pisoFoam` for this case.** We solve it as steady-state RANS; `simpleFoam` is the right choice. `pisoFoam` will run forever and the agent may not notice.
- **The downstream channel contracts at x = 206 mm (x/h ≈ 8.1).** Sampling station x/h = 10 (x = 254 mm) is *inside* the contraction, so the velocity profile there reflects accelerating channel flow, not a clean BFS profile. We sample it for completeness but the validation gate checks x/h = 4 and the reattachment length only.
- **The included OpenFOAM tutorial is 2D, one cell thick in z.** Keep it that way — 3D adds cost without scientific payoff for this validation.
- **Armaly's experiment has a finite aspect ratio.** The 2D simulation is an idealization; expect ~5–10% error on reattachment length even in the laminar regime. Document this in the demo narration.
- **Armaly defines Re using D = 2·H₁, not the step height.** A step-height-based Re is exactly half the Armaly Re. Always cross-check which definition a reference uses before comparing — getting this wrong moves you across regime boundaries.
