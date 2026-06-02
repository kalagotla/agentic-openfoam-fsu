# ONERA M6 wing — reference data

`agard_ar_138_qualitative.json` — qualitative validation targets for the half-span swept-tapered-wing case. **Not** the AGARD AR-138 experimental Cp data.

## Geometry caveat

**This is:** a half-span wing with the M6 planform (sweep, taper, aspect ratio matching M6 specs), section approximated as NACA 0010 to keep the case laptop-runnable. Exercises 3-D snappyHexMesh, prism-layer addition on swept geometry, and force-coefficient extraction.

**This isn't:** AGARD AR-138 / Schmitt-Charpin 1979. That test article uses the real ONERA "D" section (symmetric, ~9.8 % thick, distinct upper-surface curvature). Quantitative Cp comparison against the six AGARD stations (y/b = 0.20, 0.44, 0.65, 0.80, 0.90, 0.95) requires the real section.

## To use the real ONERA M6

1. Download the AGARD AR-138 ordinates from
   <https://tmbwg.github.io/turbmodels/onerawingnumerics_val.html> or
   from the original AGARD report.
2. Replace `thickness_y` in
   `cases/examples/onera-m6/geometry/generate_m6_wing.py` with a
   piecewise-linear interpolation over the ONERA section ordinates,
   or use NASA TMR's published IGES geometry directly via a CAD
   converter to STL.
3. Add a `agard_ar_138_cp.json` next to this README with the six
   stations' Cp(x/c) tabulated.
4. The scenario YAML's `validation` block then switches from
   qualitative ranges to quantitative `compare_profiles` against
   each station.

## Qualitative target ranges

For the subsonic case (M=0.3, Re_root=1e6, α=5°); full table in the JSON.

| Metric | Expected range |
|---|---|
| Cl | 0.25 – 0.45 |
| Cd | 0.010 – 0.030 |
| Residual drop | ≥ 3 orders |
| Cp suction-peak location | x/c = 0.01 – 0.15 |

Bands are deliberately loose — they catch gross setup failures (wrong α direction, missing turbulence model, under-resolution) without forcing match to an experimental point with a section the case doesn't simulate.

## Citation (real AGARD reference)

Schmitt, V. & Charpin, F. (1979).
*Pressure Distributions on the ONERA-M6-Wing at Transonic Mach
Numbers.* AGARD AR-138, Experimental Data Base for Computer Program
Assessment.
