"""Procedural generator for a NACA 0012 airfoil STL.

Writes an ASCII STL containing a thin 3-D extrusion of the symmetric
4-digit NACA 0012 airfoil — suitable for use as a snappyHexMesh
geometry in a 2-D CFD case (front and back faces become ``empty``
patches in the background blockMesh).

Run from the repo root:

    uv run python cases/examples/naca-0012/geometry/generate_naca0012.py

Regenerates ``naca0012.stl`` alongside this script. Stdlib only — no
external CAD dependency. Tweak chord, span, point count, or TE
closure by editing the constants below.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import NamedTuple

# NACA 4-digit symmetric airfoil parameters. For NACA 00XX the
# thickness in the formula below is XX / 100; the chord-line camber is
# zero. NACA 0012 → t = 0.12.
THICKNESS = 0.12

# Trailing-edge closure. The analytical NACA 4-digit thickness
# distribution does not vanish exactly at the trailing edge (y_t at
# x=1 is about -0.00126 t for the standard form), giving a small open
# wedge. snappyHexMesh prefers closed surfaces, so we force the
# trailing edge to close by replacing the last segment with a linear
# blend to y=0 at x=1.
CLOSE_TRAILING_EDGE = True


class Vec3(NamedTuple):
    x: float
    y: float
    z: float


def thickness_y(x: float, t: float = THICKNESS) -> float:
    """NACA 4-digit half-thickness y_t at chord-fraction x.

    Standard form (Abbott & von Doenhoff): the open-trailing-edge
    coefficients. We close it later if ``CLOSE_TRAILING_EDGE``.
    """
    return 5.0 * t * (
        0.2969 * math.sqrt(x)
        - 0.1260 * x
        - 0.3516 * x * x
        + 0.2843 * x * x * x
        - 0.1015 * x * x * x * x
    )


def cosine_spaced_x(n: int) -> list[float]:
    """``n`` chord-fraction stations from 0 to 1 with cosine clustering
    toward the leading and trailing edges."""
    return [0.5 * (1.0 - math.cos(math.pi * i / (n - 1))) for i in range(n)]


def airfoil_surface_points(
    n_chord: int,
    chord: float,
) -> tuple[list[Vec3], list[Vec3]]:
    """Return upper- and lower-surface point lists (2-D, z=0).

    Both lists go from leading edge (x=0) to trailing edge (x=chord).
    Trailing edge is closed when ``CLOSE_TRAILING_EDGE`` is True.
    """
    xs = cosine_spaced_x(n_chord)
    upper: list[Vec3] = []
    lower: list[Vec3] = []
    for x_frac in xs:
        yt = thickness_y(x_frac)
        if CLOSE_TRAILING_EDGE and x_frac > 0.99:
            # Linear blend the last 1% of chord to y=0 at TE.
            yt_at_99 = thickness_y(0.99)
            blend = (1.0 - x_frac) / 0.01
            yt = yt_at_99 * blend
        x_m = chord * x_frac
        upper.append(Vec3(x_m, chord * yt, 0.0))
        lower.append(Vec3(x_m, -chord * yt, 0.0))
    return upper, lower


def triangle_normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    """Outward normal of the triangle (a, b, c) by the right-hand rule."""
    ux, uy, uz = b.x - a.x, b.y - a.y, b.z - a.z
    vx, vy, vz = c.x - a.x, c.y - a.y, c.z - a.z
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag == 0:
        return Vec3(0.0, 0.0, 0.0)
    return Vec3(nx / mag, ny / mag, nz / mag)


def extrude_curve_to_quads(
    curve_front: list[Vec3],
    curve_back: list[Vec3],
    flip: bool = False,
) -> list[tuple[Vec3, Vec3, Vec3]]:
    """Build a quad strip between two parallel curves and triangulate it.

    Both curves must have the same length. Each quad is split into two
    triangles. ``flip`` reverses the winding so the surface normal
    points the other way (used for the lower surface so its normal
    points -y, and for the back end-cap so its normal points +z).
    """
    if len(curve_front) != len(curve_back):
        raise ValueError("curve lengths must match")
    tris: list[tuple[Vec3, Vec3, Vec3]] = []
    for i in range(len(curve_front) - 1):
        a = curve_front[i]
        b = curve_front[i + 1]
        c = curve_back[i + 1]
        d = curve_back[i]
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
    """Strip-triangulate the cap between upper and lower curves.

    Both lists go from LE (index 0) to TE (index -1). The LE and TE
    are shared between upper and lower (``upper[0] == lower[0]``,
    ``upper[-1] == lower[-1]``), so the LE and TE columns produce a
    single triangle each rather than a degenerate quad. Interior
    columns produce a clean quad split into two triangles.

    Winding is CCW viewed from +z (front face normal points +z). Pass
    ``flip=True`` for the back face so its normal points -z.
    """
    n = len(upper)
    tris: list[tuple[Vec3, Vec3, Vec3]] = []
    # Leading-edge triangle: LE is shared by upper[0] and lower[0].
    tris.append((upper[0], upper[1], lower[1]))
    # Interior columns.
    for i in range(1, n - 2):
        a, b = upper[i], upper[i + 1]
        c, d = lower[i + 1], lower[i]
        tris.append((a, b, c))
        tris.append((a, c, d))
    # Trailing-edge triangle: TE is shared by upper[-1] and lower[-1].
    tris.append((upper[n - 2], upper[n - 1], lower[n - 2]))
    if flip:
        tris = [(a, c, b) for (a, b, c) in tris]
    return tris


def write_ascii_stl(
    triangles: list[tuple[Vec3, Vec3, Vec3]],
    output_path: Path,
    solid_name: str,
) -> None:
    """Write triangles to an ASCII STL file."""
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


def build_naca0012_extrusion(
    chord: float = 1.0,
    span: float = 0.1,
    n_chord: int = 201,
) -> list[tuple[Vec3, Vec3, Vec3]]:
    """Return the full closed-extrusion triangle list."""
    upper_front, lower_front = airfoil_surface_points(n_chord, chord)
    # Translate to the back-plane z = +span/2; front plane is z = -span/2.
    z_front = -span / 2.0
    z_back = span / 2.0
    upper_front = [Vec3(p.x, p.y, z_front) for p in upper_front]
    lower_front = [Vec3(p.x, p.y, z_front) for p in lower_front]
    upper_back = [Vec3(p.x, p.y, z_back) for p in upper_front]
    lower_back = [Vec3(p.x, p.y, z_back) for p in lower_front]

    tris: list[tuple[Vec3, Vec3, Vec3]] = []

    # Upper surface — normal should point +y on average.
    tris.extend(extrude_curve_to_quads(upper_front, upper_back, flip=False))
    # Lower surface — normal should point -y on average. Flip the winding.
    tris.extend(extrude_curve_to_quads(lower_front, lower_back, flip=True))

    # End caps. Strip-triangulate between upper and lower curves at each
    # constant-z plane. Front cap (z = z_front, normal -z) uses flip=True;
    # back cap (z = z_back, normal +z) uses flip=False so both normals
    # point outward.
    tris.extend(strip_triangulate_cap(upper_front, lower_front, flip=True))
    tris.extend(strip_triangulate_cap(upper_back, lower_back, flip=False))

    return tris


def main() -> None:
    here = Path(__file__).resolve().parent
    output = here / "naca0012.stl"
    tris = build_naca0012_extrusion(chord=1.0, span=0.1, n_chord=201)
    write_ascii_stl(tris, output, solid_name="naca0012")
    print(f"Wrote {len(tris)} triangles to {output}")


if __name__ == "__main__":
    main()
