"""Tests for the benchmark manifest and its loader.

The manifest is checked in, so these tests double as a guard on the
benchmark itself: if a case claims a reference dataset the validation
library does not hold, or points at a scenario file that was renamed, the
suite test goes red rather than the claim surviving into a results table.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from suite import BLOCKED_STATUSES, _flatten_expected, load_suite, validate_suite

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_PATH = REPO_ROOT / "scripts" / "eval" / "suite.yaml"


@pytest.fixture
def suite():
    return load_suite(SUITE_PATH)


def test_shipped_manifest_is_valid(suite) -> None:
    assert validate_suite(suite, REPO_ROOT) == []


def test_manifest_has_both_tiers(suite) -> None:
    assert len(suite.by_tier(1)) >= 8
    assert len(suite.by_tier(2)) >= 6


def test_spliced_checklists_are_flattened(suite) -> None:
    naca = suite.case("naca-0012")
    # The YAML splices [*core, *turbulence, *snappy]; the loader must hand
    # back a flat list of dicts, not a list of lists.
    assert all(isinstance(d, dict) for d in naca.expected_decisions)
    keys = {d["key"] for d in naca.expected_decisions}
    assert {"structural_template", "turbulence_model", "layer_addition"} <= keys


def test_flatten_deduplicates_overlapping_fragments() -> None:
    flat = _flatten_expected(
        [
            [{"key": "a", "any_of": ["x"]}, {"key": "b", "any_of": ["y"]}],
            [{"key": "a", "any_of": ["z"]}],
        ]
    )
    assert [d["key"] for d in flat] == ["a", "b"]


def test_blocked_cases_are_not_runnable(suite) -> None:
    blocked = [c for c in suite.cases if c.status in BLOCKED_STATUSES]
    assert blocked, "the manifest should be honest about unbuilt cases"
    assert all(not c.runnable for c in blocked)


def test_every_runnable_case_can_actually_be_scored(suite) -> None:
    # A runnable case must have a scenario on disk, a checklist to score
    # decision coverage against, and a reference the library holds.
    for c in suite.runnable():
        assert (REPO_ROOT / c.scenario).is_file(), c.key
        assert c.expected_decisions, c.key
        assert c.reference_status == "present", c.key


def test_missing_reference_marks_the_case_blocked(suite) -> None:
    # ONERA M6 ships only a qualitative dataset, which cannot produce an L2
    # verdict. It must be flagged, not quietly counted as part of the
    # benchmark.
    for key in ("onera-m6",):
        c = suite.case(key)
        assert c.reference_status != "present"
        assert not c.runnable


def test_a_case_claiming_a_missing_reference_is_caught(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "cases": [
                    {
                        "key": "invented",
                        "tier": 1,
                        "novelty": "N1",
                        "scenario": "cases/scenarios/lid-cavity.yaml",
                        "reference": "a_dataset_that_does_not_exist",
                        "reference_status": "present",
                        "expected_decisions": [{"key": "k", "any_of": ["k"]}],
                    }
                ],
            }
        )
    )
    problems = validate_suite(load_suite(bad), REPO_ROOT)
    assert any("does not hold" in p for p in problems)


def test_duplicate_keys_are_caught(tmp_path: Path) -> None:
    bad = tmp_path / "dup.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "cases": [
                    {"key": "x", "tier": 1, "novelty": "N1", "status": "planned"},
                    {"key": "x", "tier": 2, "novelty": "N1", "status": "planned"},
                ],
            }
        )
    )
    assert any("duplicate" in p for p in validate_suite(load_suite(bad), REPO_ROOT))
