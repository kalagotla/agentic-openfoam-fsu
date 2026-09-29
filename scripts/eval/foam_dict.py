"""A small OpenFOAM dictionary reader, in pure Python.

The narration audit compares what `REPORT.md` says was configured against
what the case files actually contain, which means reading those files.
`foamDictionary` would do it, but requiring a sourced OpenFOAM environment
to *score* a run would make the evaluation harder to run than the thing it
evaluates — and would make the parser untestable without a CFD install.

So this reads the dictionary syntax directly. It handles what OpenFOAM
dicts actually contain:

- ``key value;`` with multi-token values (``div(phi,U) Gauss linearUpwind grad(U);``)
- nested blocks, flattened to dotted keys (``divSchemes.div(phi,U)``)
- list values ``( ... )`` and ``[ ... ]`` dimensions, kept as one string
- ``//`` and ``/* */`` comments
- the ``FoamFile`` header, which is boilerplate and skipped

It is deliberately not a full parser. Macro expansion (``$var``,
``#include``, ``#calc``) is left as literal text rather than resolved,
because an unresolved macro is visible as such to a reader, whereas a
wrongly-resolved one is not. Anything it cannot parse is reported, never
guessed.
"""

from __future__ import annotations

import re
from pathlib import Path

# Files that are never dictionaries worth diffing.
SKIP_NAMES = frozenset({"case.foam"})
SKIP_DIRS = frozenset({"polyMesh", "processor", "postProcessing", "analysis"})

# The header block every dict carries. Its contents (version, format,
# location, object) are boilerplate that changes with the file's path, not
# with any decision, so diffing it produces noise.
HEADER_KEY = "FoamFile"

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def strip_comments(text: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))


def _tokenize(text: str) -> list[str]:
    """Split into tokens, keeping braces and semicolons as their own."""
    out: list[str] = []
    buf: list[str] = []
    depth_paren = 0
    for ch in text:
        if ch in "([" :
            depth_paren += 1
            buf.append(ch)
            continue
        if ch in ")]":
            depth_paren = max(0, depth_paren - 1)
            buf.append(ch)
            continue
        # Inside a list or dimension set, whitespace is part of the value.
        if depth_paren > 0:
            buf.append(ch)
            continue
        if ch in "{};":
            if buf:
                out.append("".join(buf))
                buf = []
            out.append(ch)
            continue
        if ch.isspace():
            if buf:
                out.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [t.strip() for t in out if t.strip()]


def parse_dict_text(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse dictionary text into flat dotted keys, plus anything unparsed.

    Returns ``(settings, problems)``. A malformed file yields whatever
    could be read and a note about the rest — the audit reports coverage,
    so a partial parse is data, not a failure.
    """
    tokens = _tokenize(strip_comments(text))
    settings: dict[str, str] = {}
    problems: list[str] = []
    scope: list[str] = []
    pending: list[str] = []

    for tok in tokens:
        if tok == "{":
            if not pending:
                problems.append("block with no name")
                scope.append("<anon>")
            else:
                scope.append(pending[0] if len(pending) == 1 else " ".join(pending))
            pending = []
            continue
        if tok == "}":
            if scope:
                scope.pop()
            else:
                problems.append("unbalanced closing brace")
            pending = []
            continue
        if tok == ";":
            if not pending:
                continue
            key, value = pending[0], " ".join(pending[1:])
            path = ".".join([*scope, key])
            settings[path] = value
            pending = []
            continue
        pending.append(tok)

    if pending:
        problems.append(f"trailing tokens: {' '.join(pending)[:60]}")
    if scope:
        problems.append(f"unclosed block(s): {'.'.join(scope)}")
    return settings, problems


def parse_dict_file(path: Path) -> tuple[dict[str, str], list[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {}, [f"unreadable: {exc}"]
    settings, problems = parse_dict_text(text)
    # Drop the boilerplate header: it tracks the file's own path, not any
    # decision, so diffing it manufactures changes nobody made.
    settings = {
        k: v for k, v in settings.items() if not k.startswith(f"{HEADER_KEY}.")
    }
    return settings, problems


def read_case_settings(
    case: Path, subdirs: tuple[str, ...] = ("system", "constant", "0")
) -> dict[str, dict[str, str]]:
    """Every dictionary in a case, keyed by path relative to the case."""
    out: dict[str, dict[str, str]] = {}
    for sub in subdirs:
        root = case / sub
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name in SKIP_NAMES:
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(case).parts):
                continue
            settings, _ = parse_dict_file(path)
            if settings:
                out[str(path.relative_to(case))] = settings
    return out


def flatten(settings: dict[str, dict[str, str]]) -> dict[tuple[str, str], str]:
    """``{(file, key): value}`` — the shape the changeset diff works on."""
    return {
        (file, key): value
        for file, keys in settings.items()
        for key, value in keys.items()
    }
