"""Reference-dataset discovery and loading.

Reference data lives next to its case under any ``reference/*.json``
directory below ``cases/``. The validation server does **not** maintain
a registry of registered datasets — adding a new benchmark is "drop a
JSON file", nothing else.

Naming convention: each reference file's basename (stem) is the reference
name. So ``cases/lid-cavity/reference/ghia_1982.json`` is the ``ghia_1982``
reference. The agent looks references up by name and reads the JSON
directly; what's in the JSON is the case's concern.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Resolved relative to this file at servers/validation/src/validation_mcp/reference_data.py
# (4 levels up from the repo root).
REPO_ROOT = Path(__file__).resolve().parents[4]
CASES_DIR = REPO_ROOT / "cases"


class ReferenceNotFoundError(Exception):
    """Raised when a requested reference name is not found on disk."""


class MalformedReferenceError(Exception):
    """Raised when a reference file exists but is not readable JSON."""


@dataclass(frozen=True)
class ReferenceEntry:
    """One reference dataset found on disk."""

    name: str          # basename (stem) of the JSON file
    case: str          # owning case directory name, e.g. "lid-cavity"
    path: Path         # absolute path to the JSON file


def discover_references(cases_dir: Path | None = None) -> list[ReferenceEntry]:
    """Return all reference datasets found under any ``reference/*.json``
    directory below ``<cases_dir>``.

    Default ``cases_dir`` is the repo's ``cases/`` directory, resolved
    relative to this module. Walks recursively, so cases nested under
    ``cases/examples/<name>/`` are discovered alongside top-level cases
    like ``cases/lid-cavity/``.
    """
    root = cases_dir if cases_dir is not None else CASES_DIR
    if not root.is_dir():
        return []
    entries: list[ReferenceEntry] = []
    for ref_dir in sorted(root.rglob("reference")):
        if not ref_dir.is_dir():
            continue
        # Skip authored/archived copies: a reference/ dir inside cases/work/
        # (a run in progress) or a .../baseline/ archive must not shadow or
        # collide with the canonical datasets under cases/<case>/reference/.
        rel_parts = ref_dir.relative_to(root).parts
        if "work" in rel_parts or "baseline" in rel_parts:
            continue
        case = ref_dir.parent.name
        for json_path in sorted(ref_dir.glob("*.json")):
            entries.append(ReferenceEntry(name=json_path.stem, case=case, path=json_path))
    return entries


def resolve_reference(name: str, cases_dir: Path | None = None) -> ReferenceEntry:
    """Find a reference dataset by name.

    Raises:
        ReferenceNotFoundError: if no JSON file with the given stem exists
            under any case's ``reference/`` directory.
    """
    matches = [e for e in discover_references(cases_dir) if e.name == name]
    if not matches:
        available = sorted({e.name for e in discover_references(cases_dir)})
        raise ReferenceNotFoundError(
            f"No reference named {name!r} found under any reference/ "
            f"directory below cases/. Available: {available}"
        )
    if len(matches) > 1:
        cases = sorted({e.case for e in matches})
        raise ReferenceNotFoundError(
            f"Reference name {name!r} is ambiguous across cases {cases}. "
            f"Rename one of the JSON files so the stem is unique."
        )
    return matches[0]


def read_reference_json(name: str, cases_dir: Path | None = None) -> dict[str, Any]:
    """Load and parse a reference JSON by name.

    Raises:
        ReferenceNotFoundError: if no JSON file with the given stem exists.
        MalformedReferenceError: if the file exists but cannot be read as JSON
            (truncated, hand-edited into invalid syntax, or unreadable).
    """
    entry = resolve_reference(name, cases_dir=cases_dir)
    try:
        with entry.path.open() as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise MalformedReferenceError(
            f"Reference {name!r} at {entry.path} is not readable JSON: {exc}"
        ) from exc
