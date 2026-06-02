# Lid-driven cavity reference data

`ghia_1982.json` holds tabulated centerline velocity profiles for the
2-D lid-driven cavity at several Reynolds numbers, from the canonical
reference:

> Ghia, U., Ghia, K. N., & Shin, C. T. (1982).
> *High-Re solutions for incompressible flow using the Navier-Stokes
> equations and a multigrid method.*
> Journal of Computational Physics, **48**(3), 387-411.

## What's in here

| Dataset key | What it is |
|-------------|------------|
| `ghia_re_100_u_centerline` | `u(y)` along the vertical centerline `x = 0.5` at `Re = 100` |
| `ghia_re_100_v_centerline` | `v(x)` along the horizontal centerline `y = 0.5` at `Re = 100` |
| `ghia_re_400_u_centerline` | `u(y)` along the vertical centerline `x = 0.5` at `Re = 400` |
| `ghia_re_400_v_centerline` | `v(x)` along the horizontal centerline `y = 0.5` at `Re = 400` |
| `ghia_re_1000_u_centerline` | `u(y)` along the vertical centerline `x = 0.5` at `Re = 1000` |
| `ghia_re_1000_v_centerline` | `v(x)` along the horizontal centerline `y = 0.5` at `Re = 1000` |

Each dataset is sampled at the 17 non-uniform stations used by Ghia's
Tables I and II (clustered toward the walls). The `Re = 1000` columns
carry no suspected typo (unlike the `Re = 400` v-centerline; see below).

## Convention

- Coordinates and velocities are non-dimensional: cavity side `L = 1`,
  lid velocity `U_lid = 1`. So `u`, `v` ∈ [-1, 1] roughly, and `x`, `y`
  ∈ [0, 1].
- Reynolds number: `Re = U_lid * L / ν`.
- Top wall moves in +x at `U_lid`; the other three walls are no-slip.

The OpenFOAM `cavity` tutorial uses the same geometry but at `Re = 10`, so it can't be used as a validation reference directly. The shipped scenario picks `Re = 400` — high enough that the secondary corner vortices appear, low enough that a laminar simulation converges quickly.

## Tolerance

Default acceptance threshold is **5% relative L2 error** between the
simulated profile and the reference at the matching Re. This is
standard practice in the cavity-benchmark community.

The grid resolution that meets it is **not known in advance** — establish
it by refining the mesh until the centerline profiles stop changing and
converge toward this reference (a grid-convergence / mesh-independence
study), rather than assuming a cell count up front. The only sourced grid
anchor is Ghia, Ghia & Shin's own solution, computed on a **129×129
uniform mesh**; a converged 2nd-order solver should approach the 5% band
as the grid is refined toward that resolution. There is no published
source for a "known-good" cell count below that, so don't cite one —
demonstrate the convergence instead.

## Provenance

The Re=100, Re=400, and Re=1000 columns are hand-encoded from
reproductions of Ghia's Tables I and II that circulate in the
cavity-benchmark community. They reproduce Ghia's five-decimal precision
faithfully.

**Verified** against publicly mirrored transcriptions of Ghia's Tables I
and II (`gist.github.com/ivan-pi/3e9326d18a366ffe6a8e5bfda6353219` for
Table I u-velocity; `gist.github.com/ivan-pi/caa6c6737d36a9140fbcf2ea59c78b3c`
for Table II v-velocity): every value across the six shipped datasets
matches Ghia's printed tables to 5 decimal places. The Re=100/400 columns
were verified 2026-05-21; the Re=1000 columns added and verified
2026-05-28 against the same two gists.

**One suspected typo, shipped as-printed.** `ghia_re_400_v_centerline`
at `x = 0.9063` is `-0.23827` — exactly as Ghia's Table II prints it.
The transcription source annotates this value as *"probably wrong"*: it
is an outlier in the v(x) profile, sitting between `-0.44993` at
x=0.8594 and `-0.22847` at x=0.9453, where a smooth profile would put
it near `-0.34`. We ship Ghia's printed value unchanged rather than
substitute a smoothed guess, because **no published benchmark
re-tabulates Re=400 v-centerline data**: Botella & Peyret (1998) is
Re=1000 only, and Erturk, Corke & Gökçöl (2005) tabulates Re=1000-21000
only — neither covers Re=400, so neither can adjudicate the suspected
typo. Do **not** "correct" this to the smoothed value `-0.33827` that
circulates in some transcriptions: no published benchmark provides a
corrected Re=400 v-value, so that number is unsourced. If the single
suspected-typo point matters for your comparison, exclude the x=0.9063
station explicitly rather than relying on an unsourced value.

Re=100, Re=400, and Re=1000 columns are encoded; Ghia's higher-Re columns
(Re = 3200, 5000, 7500, 10000) are not included. The 2-D cavity eventually
loses steadiness at high Re — settling into time-periodic flow rather than a
steady state — so those higher columns increasingly stress the steady-laminar
assumption. The operational test is the solve itself: a steady solver there
stalls into a limit cycle instead of converging, which is the signal the
steady template is the wrong tool.
