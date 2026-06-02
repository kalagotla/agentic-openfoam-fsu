"""Download the cited literature into corpus/references/cache/ for offline reading.

Reads corpus/references/manifest.json and, for every source whose ``download``
method is fetchable, writes a local copy into ``corpus/references/cache/``
(gitignored). Copyrighted/paywalled sources (method == "manual") are
skipped and reported with their DOI/ISBN so you can obtain them yourself.

This is the "download from their links" half of the literature repo: the
manifest is the tracked index (like a Zotero library file), the cache is
the gitignored blob store.

Usage:
    uv run python corpus/references/fetch.py            # fetch everything fetchable
    uv run python corpus/references/fetch.py --list     # just print what would happen
    uv run python corpus/references/fetch.py --force     # re-download even if cached
    uv run python corpus/references/fetch.py <id> ...    # only the named source ids

Stdlib only -- no third-party dependencies, no network in the test suite
(this script is the network boundary; corpus/references/test_references.py only
validates the manifest structure offline).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
CACHE = HERE / "cache"
# A browser-ish UA: several hosts (openfoam.com) 403 the default urllib UA.
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppII corpus/references/fetch.py"
_TIMEOUT = 60


def _load_manifest() -> dict:
    with MANIFEST.open() as fh:
        return json.load(fh)


def _fetch_http(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        data = resp.read()
    dest.write_bytes(data)


def _fetch_foam_src(src_rel: str, dest: Path, base_env: str = "FOAM_SRC") -> None:
    base = os.environ.get(base_env)
    if not base:
        raise RuntimeError(
            f"{base_env} unset -- source OpenFOAM (e.g. `of2412`) before "
            f"fetching source-code citations, or skip this id."
        )
    src = Path(base) / src_rel
    if not src.is_file():
        raise FileNotFoundError(f"{src} not found in this OpenFOAM install")
    shutil.copyfile(src, dest)


def _process(source: dict, *, force: bool) -> tuple[str, str]:
    """Return (status, detail) for one source. Never raises."""
    sid = source["id"]
    dl = source.get("download", {})
    method = dl.get("method", "manual")

    if method == "manual":
        note = dl.get("note", "")
        return "manual", f"{sid}: manual -- {note[:100]}"

    fname = source.get("file")
    if not fname:
        return "error", f"{sid}: download method '{method}' but no 'file' set"
    dest = CACHE / fname

    if dest.exists() and not force:
        return "cached", f"{sid}: already in cache ({fname})"

    try:
        if method == "http":
            _fetch_http(dl["url"], dest)
        elif method == "foam_src":
            _fetch_foam_src(dl["src"], dest, dl.get("base", "FOAM_SRC"))
        else:
            return "error", f"{sid}: unknown download method '{method}'"
    except Exception as exc:  # noqa: BLE001 -- report, never crash the run
        # Clean up a partial/empty file so a retry is clean.
        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink()
        return "failed", f"{sid}: {type(exc).__name__}: {exc}"

    size = dest.stat().st_size
    return "fetched", f"{sid}: -> cache/{fname} ({size} bytes)"


def main(argv: list[str]) -> int:
    force = "--force" in argv
    list_only = "--list" in argv
    ids = [a for a in argv if not a.startswith("--")]

    manifest = _load_manifest()
    sources = manifest["sources"]
    if ids:
        wanted = set(ids)
        sources = [s for s in sources if s["id"] in wanted]
        missing = wanted - {s["id"] for s in sources}
        if missing:
            print(f"unknown source ids: {sorted(missing)}", file=sys.stderr)
            return 2

    CACHE.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for source in sources:
        if list_only:
            dl = source.get("download", {})
            print(f"{source['id']:32s} {dl.get('method','?'):9s} "
                  f"{source.get('file', '-')}")
            continue
        status, detail = _process(source, force=force)
        counts[status] = counts.get(status, 0) + 1
        marker = {
            "fetched": "OK  ", "cached": "skip", "manual": "man ",
            "failed": "FAIL", "error": "ERR ",
        }.get(status, "?   ")
        print(f"[{marker}] {detail}")

    if not list_only:
        print()
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"Summary: {summary}")
        print(f"Cache: {CACHE}")
        if counts.get("failed"):
            print("Some open sources failed (network/host issue). Re-run later; "
                  "manual sources are expected to stay un-fetched.")
    # Failures of *open* downloads are a soft error (exit 1); manual skips are fine.
    return 1 if counts.get("failed") or counts.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
