"""Qualitative vortex checks on the latest 80x80 uniform-grid U field.

Primary vortex core: interior cell with minimum |U|.
Corner eddies: the clockwise primary vortex drives u < 0 along the bottom
wall, so cells in the first row with u > 0 near a bottom corner mark a
counter-rotating corner eddy.
"""

import re
import sys
from pathlib import Path

import numpy as np

N = 80
time = sys.argv[1] if len(sys.argv) > 1 else "374"
text = Path(time, "U").read_text()
start = text.index("(", text.index("\n", text.index("internalField")))
body = text[start + 1 : text.index(")\n;", start)]
U = np.array(
    [list(map(float, v.split())) for v in re.findall(r"\(([^)]+)\)", body)]
).reshape(N, N, 3)  # [j, i] with x varying fastest
xc = (np.arange(N) + 0.5) / N

mag = np.linalg.norm(U[..., :2], axis=2)
inner = slice(N // 8, N - N // 8)
j, i = np.unravel_index(np.argmin(mag[inner, inner]), mag[inner, inner].shape)
print(f"primary core ~ x={xc[i + N // 8]:.3f} y={xc[j + N // 8]:.3f}")

row = U[0, :, 0]
left, right = row[: N // 2], row[N // 2 :]
for name, seg, xs in (("left", left, xc[: N // 2]), ("right", right, xc[N // 2 :])):
    pos = xs[seg > 0]
    if pos.size:
        print(f"{name} corner eddy: u>0 over x in [{pos.min():.3f}, {pos.max():.3f}], max u={seg.max():.2e}")
    else:
        print(f"{name} corner eddy: none resolved in first cell row")
