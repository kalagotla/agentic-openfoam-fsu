"""Procedural generator for an ONERA-M6-planform wing STL.

Writes an ASCII STL of a half-span wing with the iconic ONERA M6
planform (sweep, taper, aspect ratio) using NACA 0010 sections as a
workshop-friendly approximation to the real M6 section.

**Geometry caveat (important).** The actual ONERA M6 wing uses a
custom symmetric ~9.8 %-thick ONERA section, NOT a NACA series. The
real ordinates are published in AGARD AR-138 and on NASA's Turbulence
Modeling Resource (tmbwg.github.io/turbmodels/onerawingnumerics_val.html).
NACA 0010 at 10 % thickness is close enough (within ~0.4 % thickness
ratio) to reproduce the qualitative aerodynamics — suction peak,
shock location at transonic conditions, lift slope — but quantitative
AGARD-AR-138 Cp comparisons require the real section.

To run with the real M6 section: replace the ``thickness_y`` function
below with a piecewise-linear interpolation over the AGARD M6 ordinates,
or download the published IGES/STL from NASA TMR and skip this
generator entirely.

Planform parameters below match the published ONERA M6 dimensions,
non-dimensionalized to root chord = 1.0:

- Root chord: 1.0
- Tip chord:  0.5626 (taper ratio 0.5626)
- Semi-span:  1.4846
- Leading-edge sweep: 30 deg
- Trailing-edge sweep: 15.8 deg
- Aspect ratio (full wing): 3.8

Run from the repo root:

    uv run python cases/examples/onera-m6/geometry/generate_m6_wing.py
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import NamedTuple

# ---------- M6 planform (non-dimensional; root chord = 1) ----------
ROOT_CHORD = 1.0
TIP_CHORD = 0.5626
SEMI_SPAN = 1.4846
LE_SWEEP_DEG = 30.0
TE_SWEEP_DEG = 15.8  # implied by chord & span; not used directly

# Section approximation: NACA 4-digit symmetric, thickness ratio.
SECTION_THICKNESS = 0.10

# Discretization.
N_CHORD = 121          # chord-wise stations per section
N_SPAN = 41            # span-wise sections to loft between
CLOSE_TRAILING_EDGE = True


class Vec3(NamedTuple):
    x: float
    y: float
    z: float


def thickness_y(x: float, t: float = SECTION_THICKNESS) -> float:
    """NACA 4-digit half-thickness y_t at chord-fraction x."""
    return 5.0 * t * (
        0.2969 * math.sqrt(x)
        - 0.1260 * x
        - 0.3516 * x * x
        + 0.2843 * x * x * x
        - 0.1015 * x * x * x * x
    )


def cosine_spaced_x(n: int) -> list[float]:
    return [0.5 * (1.0 - math.cos(math.pi * i / (n - 1))) for i in range(n)]


def section_at_span(z_frac: float, n_chord: int) -> tuple[list[Vec3], list[Vec3]]:
    """Return upper- and lower-surface points for the section at the given
    spanwise fraction (0 = root, 1 = tip).

    The section is scaled to the local chord, swept back by the LE sweep
    angle, and positioned at the correct spanwise location.
    """
    chord_local = ROOT_CHORD + z_frac * (TIP_CHORD - ROOT_CHORD)
    z_local = z_frac * SEMI_SPAN
    le_x_local = z_local * math.tan(math.radians(LE_SWEEP_DEG))

    xs = cosine_spaced_x(n_chord)
    upper: list[Vec3] = []
    lower: list[Vec3] = []
    for x_frac in xs:
        yt = thickness_y(x_frac)
        if CLOSE_TRAILING_EDGE and x_frac > 0.99:
            yt_at_99 = thickness_y(0.99)
            yt = yt_at_99 * (1.0 - x_frac) / 0.01
        x_world = le_x_local + chord_local * x_frac
        y_world = chord_local * yt
        upper.append(Vec3(x_world, y_world, z_local))
        lower.append(Vec3(x_world, -y_world, z_local))
    return upper, lower


def triangle_normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    ux, uy, uz = b.x - a.x, b.y - a.y, b.z - a.z
    vx, vy, vz = c.x - a.x, c.y - a.y, c.z - a.z
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag == 0:
        return Vec3(0.0, 0.0, 0.0)
    return Vec3(nx / mag, ny / mag, nz / mag)


def strip_triangulate_between(
    line_a: list[Vec3],
    line_b: list[Vec3],
    flip: bool = False,
) -> list[tuple[Vec3, Vec3, Vec3]]:
    """Quad-strip between two parallel curves of equal length."""
    if len(line_a) != len(line_b):
        raise ValueError("curves must have equal length")
    tris: list[tuple[Vec3, Vec3, Vec3]] = []
    for i in range(len(line_a) - 1):
        a = line_a[i]
        b = line_a[i + 1]
        c = line_b[i + 1]
        d = line_b[i]
        if flip:
            tris.append((a, c, b))
            tris.append((a, d, c))
        else:
            tris.append((a, b, c))
            tris.append((a, c, d))
    return tris


def strip_triangulate_cap(
    upper: list[Vec3],
    lower: list[Vec3],
    flip: bool = False,
) -> list[tuple[Vec3, Vec3, Vec3]]:
    """Strip-triangulate an end cap between upper and lower section curves.

    Identical algorithm to the NACA 0012 cap routine: collapse the LE
    and TE columns to single triangles since both curves share their
    endpoints there.
    """
    n = len(upper)
    tris: list[tuple[Vec3, Vec3, Vec3]] = []
    tris.append((upper[0], upper[1], lower[1]))
    for i in range(1, n - 2):
        a, b = upper[i], upper[i + 1]
        c, d = lower[i + 1], lower[i]
        tris.append((a, b, c))
        tris.append((a, c, d))
    tris.append((upper[n - 2], upper[n - 1], lower[n - 2]))
    if flip:
        tris = [(a, c, b) for (a, b, c) in tris]
    return tris


def write_ascii_stl(
    triangles: list[tuple[Vec3, Vec3, Vec3]],
    output_path: Path,
    solid_name: str,
) -> None:
    with output_path.open("w") as f:
        f.write(f"solid {solid_name}\n")
        for a, b, c in triangles:
            n = triangle_normal(a, b, c)
            f.write(f"  facet normal {n.x:.6e} {n.y:.6e} {n.z:.6e}\n")
            f.write("    outer loop\n")
            for v in (a, b, c):
                f.write(f"      vertex {v.x:.6e} {v.y:.6e} {v.z:.6e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write(f"endsolid {solid_name}\n")


def build_m6_wing() -> list[tuple[Vec3, Vec3, Vec3]]:
    """Loft the wing between root and tip and close root/tip caps."""
    # Pre-compute every spanwise section.
    sections_upper: list[list[Vec3]] = []
    sections_lower: list[list[Vec3]] = []
    for i in range(N_SPAN):
        z_frac = i / (N_SPAN - 1)
        upper, lower = section_at_span(z_frac, N_CHORD)
        sections_upper.append(upper)
        sections_lower.append(lower)

    tris: list[tuple[Vec3, Vec3, Vec3]] = []

    # Loft upper surface (quad strip between adjacent spanwise sections,
    # winding so the surface normal points +y on average).
    for i in range(N_SPAN - 1):
        tris.extend(
            strip_triangulate_between(
                sections_upper[i], sections_upper[i + 1], flip=False
            )
        )

    # Loft lower surface (normal -y; flip winding).
    for i in range(N_SPAN - 1):
        tris.extend(
            strip_triangulate_between(
                sections_lower[i], sections_lower[i + 1], flip=True
            )
        )

    # Root cap (at z = 0). Normal points -z (outward from the half-span
    # wing model when paired with a symmetry plane on the full aircraft).
    tris.extend(
        strip_triangulate_cap(
            sections_upper[0], sections_lower[0], flip=True
        )
    )

    # Tip cap (at z = SEMI_SPAN). Normal points +z.
    tris.extend(
        strip_triangulate_cap(
            sections_upper[-1], sections_lower[-1], flip=False
        )
    )

    return tris


def main() -> None:
    here = Path(__file__).resolve().parent
    output = here / "m6_wing.stl"
    tris = build_m6_wing()
    write_ascii_stl(tris, output, solid_name="m6_wing")
    print(f"Wrote {len(tris)} triangles to {output}")


if __name__ == "__main__":
    main()
