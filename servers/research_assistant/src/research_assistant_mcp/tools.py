"""Tools for the Research-assistant MCP server.

Same rules as the other servers (see ``docs/architecture.md``):

1. Every tool returns ``{"success": bool, ...}``. Never raise.
2. Operate on ``$WM_PROJECT_USER_DIR`` and read from ``$FOAM_SRC`` /
   ``$FOAM_APP``. **Do not vendor OpenFOAM source into the repo.**
3. The researcher decides what to compile and how to fix errors —
   these tools surface structured information, not decisions.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ToolResult = dict[str, Any]

# Tail length for log returns. Keep it small — large logs blow context.
_LOG_TAIL_LINES = 80
_WMAKE_TIMEOUT_SEC = 600


# ---------------------------------------------------------------------------
# Compile-error patterns.
# ---------------------------------------------------------------------------

# "fatal error: someHeader.H: No such file or directory"
_MISSING_HEADER = re.compile(
    r"^(?P<file>[^\s:]+):(?P<line>\d+):(?:\d+:)?\s*fatal error:\s+"
    r"(?P<missing>\S+):\s*No such file or directory"
)
# "error: 'X' was not declared in this scope"
_NOT_DECLARED = re.compile(
    r"^(?P<file>[^\s:]+):(?P<line>\d+):(?:\d+:)?\s*error:\s+(?P<message>.*)"
)
# Linker undefined reference.
_LD_UNDEFINED = re.compile(
    r"undefined reference to\s+`(?P<symbol>[^`]+)'"
)
# Linker symbol not found at runtime.
_LD_CANNOT_FIND = re.compile(r"cannot find -l(?P<lib>\S+)")
# Output line: "...-o /path/to/libfoo.so" — the library wmake just built.
_BUILT_LIB = re.compile(
    r"-o\s+(?P<path>\S+/lib[^/\s]+\.so)\b"
)
_BUILT_BIN = re.compile(
    r"-o\s+(?P<path>\S+/bin/[^/\s]+)\b"
)


def _tail(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _decode_streams(*streams: str | bytes | None) -> str:
    """Concatenate subprocess stdout/stderr streams, coercing bytes to str."""
    parts: list[str] = []
    for s in streams:
        if s is None:
            continue
        parts.append(s.decode(errors="replace") if isinstance(s, bytes) else s)
    return "".join(parts)


def _parse_wmake_output(text: str) -> dict[str, Any]:
    """Pull structured info from a wmake stdout/stderr stream."""
    errors: list[dict[str, str]] = []
    seen: set[tuple[Any, ...]] = set()
    libraries_built: list[str] = []
    binaries_built: list[str] = []

    key: tuple[Any, ...]
    for line in text.splitlines():
        m = _MISSING_HEADER.match(line)
        if m:
            key = ("missing_header", m.group("file"), m.group("missing"))
            if key not in seen:
                seen.add(key)
                errors.append(
                    {
                        "type": "missing_header",
                        "file": m.group("file"),
                        "line": m.group("line"),
                        "missing": m.group("missing"),
                        "raw": line.strip(),
                        "hint": (
                            "Add -I$(LIB_SRC)/<module>/lnInclude to "
                            "EXE_INC in Make/options."
                        ),
                    }
                )
            continue

        m = _LD_CANNOT_FIND.search(line)
        if m:
            key = ("missing_library", m.group("lib"))
            if key not in seen:
                seen.add(key)
                errors.append(
                    {
                        "type": "missing_library",
                        "library": m.group("lib"),
                        "raw": line.strip(),
                        "hint": (
                            "Library not on linker path. Either it's "
                            "misspelled, or you need a corresponding "
                            "-I include path under LIB_SRC."
                        ),
                    }
                )
            continue

        m = _LD_UNDEFINED.search(line)
        if m:
            key = ("undefined_symbol", m.group("symbol"))
            if key not in seen:
                seen.add(key)
                errors.append(
                    {
                        "type": "undefined_symbol",
                        "symbol": m.group("symbol"),
                        "raw": line.strip(),
                        "hint": (
                            "Linker can't resolve this symbol. Common "
                            "causes: missing -l flag in LIB_LIBS, "
                            "ESI/Foundation ABI mismatch, or a "
                            "constructor/method declared but not defined."
                        ),
                    }
                )
            continue

        # Generic 'error:' — last so missing-header etc. take priority.
        m = _NOT_DECLARED.match(line)
        if m and "error:" in line:
            key = ("compile_error", m.group("file"), m.group("line"), m.group("message"))
            if key not in seen:
                seen.add(key)
                errors.append(
                    {
                        "type": "compile_error",
                        "file": m.group("file"),
                        "line": m.group("line"),
                        "message": m.group("message"),
                        "raw": line.strip(),
                        "hint": "",
                    }
                )

    for line in text.splitlines():
        m = _BUILT_LIB.search(line)
        if m and m.group("path") not in libraries_built:
            libraries_built.append(m.group("path"))
            continue
        m = _BUILT_BIN.search(line)
        if m and m.group("path") not in binaries_built:
            binaries_built.append(m.group("path"))

    return {
        "errors": errors,
        "libraries_built": libraries_built,
        "binaries_built": binaries_built,
    }


# ---------------------------------------------------------------------------
# wmake_and_report
# ---------------------------------------------------------------------------


def wmake_and_report(directory: str, target: str = "libso") -> ToolResult:
    """Run ``wmake`` and return a structured parse of the result.

    The directory must contain a ``Make/`` subdirectory with ``files``
    and ``options``. Common targets:

    - ``"libso"`` — shared library (default for custom BCs / function
      objects).
    - ``""`` (empty string) — application / executable.
    - ``"libo"`` — static library (rare).

    On compile or link failure, the returned ``errors`` list groups
    common error types with hints:

    - ``"missing_header"`` (fatal error: X.H: No such file) — hint
      points at ``EXE_INC`` in ``Make/options``.
    - ``"missing_library"`` (ld: cannot find -lX) — likewise for
      ``LIB_LIBS``.
    - ``"undefined_symbol"`` (ld: undefined reference) — common
      causes listed in the hint.
    - ``"compile_error"`` (generic g++ ``error:`` lines).

    Args:
        directory: Absolute path to the source directory containing
            ``Make/files`` and ``Make/options``.
        target: wmake target. Defaults to ``"libso"`` (shared library).
            Use ``""`` (empty) for an executable target.

    Returns:
        On success: ``{"success": True, "returncode": 0,
        "libraries_built": [str], "binaries_built": [str], "errors":
        [], "log_tail": str}``.

        On failure (non-zero wmake exit): ``{"success": False,
        "returncode": int, "errors": [{...}], "libraries_built": [str],
        "binaries_built": [str], "log_tail": str}``. ``errors`` may be
        empty if wmake failed for a reason this parser didn't
        recognise — the ``log_tail`` is the fallback.

        On infrastructure failure: ``{"success": False, "reason": str,
        "detail": str}`` where ``reason`` is ``"invalid_directory"``,
        ``"make_dir_missing"``, ``"wmake_not_on_path"``,
        ``"timeout"``.
    """
    src = Path(directory)
    if not src.is_dir():
        return {
            "success": False,
            "reason": "invalid_directory",
            "detail": f"{src} does not exist or is not a directory.",
        }
    if not (src / "Make").is_dir():
        return {
            "success": False,
            "reason": "make_dir_missing",
            "detail": (
                f"{src / 'Make'} not found. wmake needs Make/files and "
                f"Make/options."
            ),
        }

    if shutil.which("wmake") is None:
        return {
            "success": False,
            "reason": "wmake_not_on_path",
            "detail": (
                "wmake CLI not found. Source OpenFOAM "
                "(e.g. `of2412` or `source .../etc/bashrc`)."
            ),
        }

    cmd = ["wmake"]
    if target:
        cmd.append(target)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(src),
            capture_output=True,
            text=True,
            timeout=_WMAKE_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial_text = _decode_streams(exc.stdout, exc.stderr)
        return {
            "success": False,
            "reason": "timeout",
            "detail": f"wmake exceeded {_WMAKE_TIMEOUT_SEC}s.",
            "log_tail": _tail(partial_text, _LOG_TAIL_LINES),
        }

    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    parsed = _parse_wmake_output(combined)
    return {
        "success": result.returncode == 0,
        "returncode": result.returncode,
        "directory": str(src),
        "target": target or "(executable)",
        "errors": parsed["errors"],
        "libraries_built": parsed["libraries_built"],
        "binaries_built": parsed["binaries_built"],
        "log_tail": _tail(combined, _LOG_TAIL_LINES),
    }


# ---------------------------------------------------------------------------
# find_examples_of_base_class
# ---------------------------------------------------------------------------

# Pull "class FooBar : public BaseClass" or with "<...>" template args.
# We only match the FIRST listed inheritance — that's the canonical pattern
# for OpenFOAM derived BCs / function objects / turbulence models.
_CLASS_DECL = re.compile(
    r"class\s+(?P<name>\w+)\s*(?:final\s*)?:\s*public\s+(?P<base>[\w<>,\s:]+?)\s*[{,]",
    re.DOTALL,
)


def _resolve_search_roots() -> list[Path]:
    roots: list[Path] = []
    for env_var in ("FOAM_SRC", "FOAM_APP"):
        val = os.environ.get(env_var)
        if val:
            p = Path(val)
            if p.is_dir():
                roots.append(p)
    return roots


def find_examples_of_base_class(
    base_class: str, max_results: int = 10
) -> ToolResult:
    """Find derivations of an OpenFOAM base class in $FOAM_SRC / $FOAM_APP.

    The fastest way to write a custom BC, function object, or
    transport model is to find the closest existing example and copy
    its skeleton. This tool greps the OpenFOAM source tree for
    ``class X : public <base_class>`` declarations and returns the
    candidate header paths plus the derived class names.

    The base-class match is a simple substring — pass the bare class
    name (e.g. ``"fixedValueFvPatchVectorField"``) without template
    arguments to get the broadest match. Pass with arguments
    (e.g. ``"RASModel<BasicTurbulenceModel>"``) to narrow it.

    Args:
        base_class: Name of the base class. Substring match.
        max_results: Cap on the returned list. Default 10.

    Returns:
        On success: ``{"success": True, "base_class": str, "examples":
        [{"derived_class": str, "header_path": str, "base_match": str},
        ...]}``. Sorted by header path.

        On failure: ``{"success": False, "reason":
        "foam_src_not_set"}`` (neither ``$FOAM_SRC`` nor ``$FOAM_APP``
        is a directory).
    """
    base_class = base_class.strip()
    if not base_class:
        return {
            "success": False,
            "reason": "empty_base_class",
            "detail": "base_class must be a non-empty string",
        }

    roots = _resolve_search_roots()
    if not roots:
        return {
            "success": False,
            "reason": "foam_src_not_set",
            "detail": (
                "$FOAM_SRC and $FOAM_APP are both unset or point at "
                "non-existent directories. Source OpenFOAM first."
            ),
        }

    examples: list[dict[str, str]] = []
    seen_paths: set[Path] = set()
    for root in roots:
        # Stop early if we've collected enough.
        if len(examples) >= max_results * 4:
            break
        for header in root.rglob("*.H"):
            if header in seen_paths:
                continue
            # Skip the lnInclude symlink trees — they're duplicates of
            # the real headers in the parent module.
            if "lnInclude" in header.parts:
                continue
            try:
                text = header.read_text(errors="replace")
            except OSError:
                continue
            for m in _CLASS_DECL.finditer(text):
                base = " ".join(m.group("base").split())
                if base_class in base:
                    examples.append(
                        {
                            "derived_class": m.group("name"),
                            "header_path": str(header),
                            "base_match": base,
                        }
                    )
                    seen_paths.add(header)
                    break  # only first matching declaration per file

    examples.sort(key=lambda e: e["header_path"])
    return {
        "success": True,
        "base_class": base_class,
        "examples": examples[:max_results],
        "n_total_matches": len(examples),
        "searched_roots": [str(r) for r in roots],
    }


# ---------------------------------------------------------------------------
# discover_user_lib_path
# ---------------------------------------------------------------------------


def discover_user_lib_path() -> ToolResult:
    """Report the researcher's user-dir layout so the agent doesn't guess.

    Returns the values of ``FOAM_USER_LIBBIN``, ``FOAM_USER_APPBIN``,
    ``WM_PROJECT_USER_DIR``, and ``WM_PROJECT_VERSION`` from the
    environment. Call this before scaffolding or building so the agent
    knows (a) where the library / executable will land, (b) which
    OpenFOAM fork is active. ESI ``v2412`` and Foundation ``12``/``13``
    are *not* drop-in compatible — the version string is the first
    check before reusing a previously-built `.so`.

    Returns:
        ``{"success": True, "wm_project_version": str|None,
        "wm_project_user_dir": str|None, "foam_user_libbin": str|None,
        "foam_user_appbin": str|None, "fork": str}`` — ``fork`` is one
        of ``"esi"``, ``"foundation"``, ``"unknown"`` based on the
        version string format.

        ``{"success": False, "reason": "openfoam_not_sourced"}`` if
        ``WM_PROJECT_VERSION`` is unset.
    """
    version = os.environ.get("WM_PROJECT_VERSION")
    if not version:
        return {
            "success": False,
            "reason": "openfoam_not_sourced",
            "detail": (
                "WM_PROJECT_VERSION is unset. Source OpenFOAM "
                "(e.g. `of2412` or `source .../etc/bashrc`)."
            ),
        }

    # ESI versions look like "v2412", "v2406". Foundation versions
    # look like "12", "13", or "12.0".
    if version.lower().startswith("v"):
        fork = "esi"
    elif re.match(r"^\d+(\.\d+)?$", version):
        fork = "foundation"
    else:
        fork = "unknown"

    return {
        "success": True,
        "wm_project_version": version,
        "wm_project_user_dir": os.environ.get("WM_PROJECT_USER_DIR"),
        "foam_user_libbin": os.environ.get("FOAM_USER_LIBBIN"),
        "foam_user_appbin": os.environ.get("FOAM_USER_APPBIN"),
        "fork": fork,
    }
