"""grid_convergence_index against Celik et al. (2008) and exact cases."""

import pytest

from validation_mcp.tools import grid_convergence_index


def test_celik_2008_worked_example():
    # Celik et al. (2008), Table 1, column phi = dimensionless reattachment
    # length: N = 18000 / 8000 / 4500 cells -> r21 = 1.5, r32 = 1.333.
    r = grid_convergence_index([1.0, 1.5, 2.0], [6.063, 5.972, 5.863])
    assert r["success"] and r["convergence"] == "monotonic"
    assert r["apparent_order"] == pytest.approx(1.53, abs=0.01)
    assert r["extrapolated"] == pytest.approx(6.1685, abs=0.001)
    assert r["gci_fine"] == pytest.approx(0.022, abs=0.001)


def test_exact_second_order_is_in_asymptotic_range():
    h = [0.05, 0.025, 0.0125]
    phi = [1 + 3 * x**2 for x in h]          # given coarse to fine
    r = grid_convergence_index(h, phi)
    assert r["apparent_order"] == pytest.approx(2.0, abs=1e-6)
    assert r["extrapolated"] == pytest.approx(1.0, abs=1e-9)
    assert r["asymptotic_ratio"] == pytest.approx(1.0, abs=0.01)


def test_profile_and_oscillation():
    h = [1 / 20, 1 / 40, 1 / 80]
    prof = [[1 + 2 * x**2, 2 - 5 * x**2] for x in h]
    r = grid_convergence_index(h, prof)
    assert r["summary"]["apparent_order_mean"] == pytest.approx(2.0, abs=1e-6)
    assert len(r["gci_fine"]) == 2
    osc = grid_convergence_index([1, 2, 4], [1.0, 1.1, 0.95])
    assert osc["convergence"] == "oscillatory"


def test_bad_input():
    assert grid_convergence_index([1, 2], [1, 2])["success"] is False
    assert grid_convergence_index([1, 1, 2], [1, 2, 3])["success"] is False
