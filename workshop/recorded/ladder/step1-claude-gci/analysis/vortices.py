"""Locate the primary vortex and test for lower-corner eddies via the streamfunction.

psi(x, y) = integral_0^y u dy' at fixed x (psi = 0 on the bottom wall). The
primary vortex has psi < 0 (clockwise); a counter-rotating corner eddy shows up
as a region of psi > 0. Assumes the uniform N x N blockMesh cell ordering
(i fastest, then j).
"""

import re
import sys

import numpy as np

for spec in sys.argv[1:]:
    case, n, t = spec.split(":")
    N = int(n)
    text = open(f"{case}/{t}/U").read()
    internal = text.split("internalField")[1].split("boundaryField")[0]
    vals = re.findall(r"\(([-\d.e+]+) ([-\d.e+]+) [-\d.e+]+\)", internal)
    U = np.array(vals, float)[: N * N].reshape(N, N, 2)
    h = 1.0 / N
    psi = np.cumsum(U[:, :, 0], axis=0) * h
    jc, ic = np.unravel_index(np.argmin(psi), psi.shape)
    print(f"{N}x{N}: primary core x={(ic + .5) * h:.3f} y={(jc + 1) * h:.3f} psi={psi.min():.4f}")
    for name, sl in [("bottom-left", (slice(0, N // 4), slice(0, N // 4))),
                     ("bottom-right", (slice(0, N // 3), slice(2 * N // 3, N)))]:
        p = psi[sl]
        print(f"  {name}: psi max {p.max():.2e}, cells with psi>0: {int((p > 0).sum())}")
