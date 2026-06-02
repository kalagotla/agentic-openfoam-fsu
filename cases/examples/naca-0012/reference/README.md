# NACA 0012 reference data

`xfoil_polar.json` holds Cl and Cd vs angle of attack for the
NACA 0012 airfoil at Re_c = 1e6, M = 0.15.

## What's in here

A single dataset of 9 (α, Cl, Cd) tuples at α = 0, 2, 4, ..., 14, 15 deg.

## Convention

- Reynolds number: chord-based, Re_c = U_inf * c / ν.
- Coefficients are standard 2-D section coefficients,
  `Cl = lift / (0.5 ρ U_inf^2 c)`.
- α is in degrees, measured from the chord line.

## Tolerance

Suggested acceptance bands for a typical OpenFOAM RANS run:

- **Cl**: ±10% relative. A 2-D fully-turbulent k-ω-SST RANS at decent
  resolution matches XFOIL Cl within ~5% in the linear regime.
- **Cd**: ±30% relative. Drag is much more mesh-sensitive and
  fully-turbulent RANS over-predicts Cd vs XFOIL's transition-modelled
  result by 20–40% as a baseline. Tighten this if the RANS case
  includes a transition model.

## Provenance

Generated with XFOIL v6.99 on 2026-05-18 using default settings:

```
xfoil> NACA 0012
xfoil> OPER
xfoil> VISC 1000000
xfoil> M 0.15
xfoil> PACC polar.txt
xfoil> ASEQ 0 15 2
xfoil> ASEQ 15 15 1
xfoil> PACC
xfoil> QUIT
```

XFOIL's e^n transition model with `Ncrit=9` (default). To regenerate, install XFOIL (<https://web.mit.edu/drela/Public/web/xfoil/>) and run the commands above.

XFOIL is the appropriate reference for **subsonic, attached flow**
(roughly α ≲ 10°, where its viscous–inviscid coupling is accurate).
Approaching stall (α ≈ 15–16° for NACA 0012 at this Re) XFOIL's
panel/BL approach diverges from reality; in that regime compare
against experimental tunnel data instead. The canonical subsonic
NACA 0012 polar set is Ladson, C. L. (1988), *Effects of Independent
Variation of Mach and Reynolds Numbers on the Low-Speed Aerodynamic
Characteristics of the NACA 0012 Airfoil Section*, NASA TM-4074
(Cl_max ≈ 1.5 near α ≈ 16°). Note also that XFOIL under-predicts Cd
relative to experiment, so it is a weak reference for absolute drag.
