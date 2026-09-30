"""Corpus annotation lookup.

Corpus entries live at ``<repo>/corpus/<solver>/<case>.md`` mirroring
the OpenFOAM tutorial tree. Each file has YAML frontmatter followed by
a markdown body structured around the consultant schema.

This module locates the corpus directory (walks up from the package
location until ``corpus/`` is found, or uses the
``AGENTIC_OPENFOAM_ROOT`` env var as an override) and parses one file.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

# Heuristic: walk up from this file looking for a directory named
# ``corpus``. Works when the repo is laid out as ``<repo>/corpus/`` and
# ``<repo>/servers/consultant/src/consultant_mcp/annotations.py``.
ENV_ROOT_OVERRIDE = "AGENTIC_OPENFOAM_ROOT"
ANNOTATIONS_DIRNAME = "corpus"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class AnnotationNotFoundError(LookupError):
    """Raised when no annotation file exists for a tutorial path."""


@dataclass(frozen=True)
class Annotation:
    """A parsed tutorial annotation."""

    tutorial_path: str
    file_path: Path
    metadata: dict[str, Any]
    body: str


def find_repo_root() -> Path:
    """Locate the repo root by walking up for ``corpus/``.

    Honours ``AGENTIC_OPENFOAM_ROOT`` env var if set — useful for tests
    and unconventional install layouts.
    """
    override = os.environ.get(ENV_ROOT_OVERRIDE)
    if override:
        root = Path(override).resolve()
        if (root / ANNOTATIONS_DIRNAME).is_dir():
            return root
        raise FileNotFoundError(
            f"{ENV_ROOT_OVERRIDE}={override} is set but "
            f"{root / ANNOTATIONS_DIRNAME} does not exist."
        )

    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / ANNOTATIONS_DIRNAME).is_dir():
            return parent
    raise FileNotFoundError(
        f"Could not locate the {ANNOTATIONS_DIRNAME}/ directory by walking up "
        f"from {here}. Set {ENV_ROOT_OVERRIDE} to override."
    )


def annotation_path_for(tutorial_path: str, root: Path | None = None) -> Path:
    """Return the expected annotation file path for a tutorial.

    ``tutorial_path`` is the path relative to ``$FOAM_TUTORIALS``, e.g.
    ``"incompressible/icoFoam/cavity/cavity"``. Trailing slashes and
    a leading slash are tolerated.
    """
    clean = tutorial_path.strip().strip("/")
    if not clean:
        raise ValueError("tutorial_path must be a non-empty string")
    base = root if root is not None else find_repo_root()
    return base / ANNOTATIONS_DIRNAME / f"{clean}.md"


def read_annotation(tutorial_path: str, root: Path | None = None) -> Annotation:
    """Read and parse an annotation file.

    Raises:
        AnnotationNotFoundError: when no matching ``.md`` exists.
        ValueError: when the file exists but has malformed frontmatter.
    """
    file_path = annotation_path_for(tutorial_path, root=root)
    if not file_path.is_file():
        # Tutorials nest a case under a directory of the same name
        # (icoFoam/cavity/cavity). Agents often pass the directory
        # ("incompressible/icoFoam/cavity"); resolve that to the nested case
        # rather than report a miss that makes the run rediscover the setup.
        clean = tutorial_path.strip().strip("/")
        nested = f"{clean}/{clean.rsplit('/', 1)[-1]}"
        nested_path = annotation_path_for(nested, root=root)
        if nested_path.is_file():
            tutorial_path, file_path = nested, nested_path
    if not file_path.is_file():
        raise AnnotationNotFoundError(
            f"No annotation at {file_path}. Author one to cite this tutorial."
        )

    text = file_path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(
            f"{file_path}: missing YAML frontmatter (expected leading "
            f"'---' fences before the body)."
        )

    try:
        metadata = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(
            f"{file_path}: YAML frontmatter is malformed: {exc}"
        ) from exc

    if not isinstance(metadata, dict):
        raise ValueError(
            f"{file_path}: frontmatter must parse to a mapping, got "
            f"{type(metadata).__name__}."
        )

    body = text[m.end() :].lstrip("\n")
    return Annotation(
        tutorial_path=tutorial_path.strip().strip("/"),
        file_path=file_path,
        metadata=metadata,
        body=body,
    )
