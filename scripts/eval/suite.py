"""Load and validate the benchmark manifest (`suite.yaml`).

The manifest is the single place that says what the benchmark *is*: which
cases exist, what tier and novelty each carries, which reference dataset
scores it, and which load-bearing decisions a reader needs narrated. Every
other module reads it rather than hardcoding a case list.

Two conveniences the raw YAML cannot express on its own:

- **Flattening.** Checklists are spliced from reusable anchors
  (``[*core, *turbulence]``), which YAML merges as a list *of lists*.
  ``load_suite`` flattens them so a case's ``expected_decisions`` is always
  a flat list of ``{"key": ..., "any_of": [...]}``.
- **Honesty checks.** ``validate_suite`` refuses a manifest that claims a
  reference dataset the library does not hold without marking the case
  blocked, or that lists a scenario file that is not there. A benchmark
  whose manifest overstates what it can score is worse than no manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Statuses that mean "this case cannot produce a scoreable run yet".
BLOCKED_STATUSES = frozenset(
    {"planned", "blocked_on_reference", "blocked_on_case_mismatch", "disabled"}
)

VALID_NOVELTY = frozenset({"N0", "N1", "N2", "N3", "N4"})
VALID_REFERENCE_STATUS = frozenset(
    {"present", "missing", "qualitative_only", "not_applicable"}
)


@dataclass
class SuiteCase:
    """One benchmark case."""

    key: str
    tier: int
    novelty: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str | None:
        return self.raw.get("status")

    @property
    def runnable(self) -> bool:
        return self.status not in BLOCKED_STATUSES

    @property
    def scenario(self) -> str | None:
        return self.raw.get("scenario")

    @property
    def reference(self) -> str | None:
        return self.raw.get("reference")

    @property
    def reference_status(self) -> str:
        return self.raw.get("reference_status", "present")

    @property
    def expected_decisions(self) -> list[dict[str, Any]]:
        return list(self.raw.get("expected_decisions", []))

    @property
    def compute_weight(self) -> str:
        return self.raw.get("compute_weight", "light")

    def seeds(self, defaults: dict[str, Any]) -> int:
        return int(self.raw.get("seeds", defaults.get("seeds", 1)))


@dataclass
class Suite:
    path: Path
    version: int
    defaults: dict[str, Any]
    cases: list[SuiteCase]

    def case(self, key: str) -> SuiteCase:
        for c in self.cases:
            if c.key == key:
                return c
        raise KeyError(f"no case with key {key!r} in {self.path}")

    def runnable(self) -> list[SuiteCase]:
        return [c for c in self.cases if c.runnable]

    def by_tier(self, tier: int) -> list[SuiteCase]:
        return [c for c in self.cases if c.tier == tier]


def _flatten_expected(raw: Any) -> list[dict[str, Any]]:
    """Flatten a possibly-nested checklist into a list of dicts.

    ``expected_decisions: [*core, *turbulence]`` yields a list of lists;
    ``expected_decisions: *core`` yields a flat one. Both are valid input.
    Duplicate keys (a checklist fragment appearing twice) collapse to one,
    so a case that splices overlapping fragments is not scored against the
    same choice twice.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            key = str(node.get("key", "")).strip()
            if key and key not in seen:
                seen.add(key)
                out.append({"key": key, "any_of": list(node.get("any_of", [key]))})

    walk(raw)
    return out


def load_suite(path: str | Path) -> Suite:
    """Read and normalise the manifest."""
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cases: list[SuiteCase] = []
    for raw in data.get("cases", []):
        entry = dict(raw)
        entry["expected_decisions"] = _flatten_expected(entry.get("expected_decisions"))
        cases.append(
            SuiteCase(
                key=str(entry.get("key", "")),
                tier=int(entry.get("tier", 0)),
                novelty=str(entry.get("novelty", "")),
                raw=entry,
            )
        )
    return Suite(
        path=p,
        version=int(data.get("version", 0)),
        defaults=dict(data.get("defaults", {})),
        cases=cases,
    )


def validate_suite(suite: Suite, repo_root: Path) -> list[str]:
    """Return a list of manifest problems. Empty means the manifest is honest.

    Checks the things that would let the benchmark overstate itself: a
    duplicate or missing key, a scenario file that is not on disk, an
    unknown novelty label, a case claiming a reference the library does not
    hold while still presenting itself as runnable, or a runnable case with
    no checklist to score its decision coverage against.
    """
    problems: list[str] = []
    seen: set[str] = set()

    available = _available_references(repo_root)

    for c in suite.cases:
        if not c.key:
            problems.append("a case has no key")
            continue
        if c.key in seen:
            problems.append(f"{c.key}: duplicate key")
        seen.add(c.key)

        if c.novelty and c.novelty not in VALID_NOVELTY:
            problems.append(f"{c.key}: unknown novelty {c.novelty!r}")
        if c.reference_status not in VALID_REFERENCE_STATUS:
            problems.append(
                f"{c.key}: unknown reference_status {c.reference_status!r}"
            )

        if not c.runnable:
            continue

        if not c.scenario:
            problems.append(f"{c.key}: runnable but names no scenario")
        elif not (repo_root / c.scenario).is_file():
            problems.append(f"{c.key}: scenario not found at {c.scenario}")

        if not c.expected_decisions:
            problems.append(f"{c.key}: runnable but has no expected_decisions")

        if c.reference_status == "present":
            ref = c.reference
            if ref and available is not None and ref not in available:
                problems.append(
                    f"{c.key}: reference {ref!r} marked present but the "
                    "validation library does not hold it"
                )
    return problems


def _available_references(repo_root: Path) -> set[str] | None:
    """Names the validation library can actually resolve, or None if unknown."""
    try:
        from validation_mcp import tools as validation
    except ImportError:  # pragma: no cover - workspace dependency
        return None
    result = validation.list_references()
    if not result.get("success"):
        return None
    return {r["name"] for r in result.get("references", [])}
