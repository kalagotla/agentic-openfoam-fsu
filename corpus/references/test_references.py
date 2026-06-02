"""Structural validation of corpus/references/manifest.json.

Offline only -- no network. (The network boundary is fetch.py; the
consultant test suite owns the citation<->manifest sync check.) Run with:

    uv run pytest corpus/references/test_references.py
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

MANIFEST = Path(__file__).resolve().parent / "manifest.json"
_VALID_KINDS = {"source_code", "paper", "book", "report", "webpage"}
_VALID_METHODS = {"http", "foam_src", "manual"}


def _manifest() -> dict:
    with MANIFEST.open() as fh:
        return json.load(fh)


def _sources() -> list[dict]:
    return _manifest()["sources"]


def test_manifest_is_valid_json_with_sources() -> None:
    m = _manifest()
    assert isinstance(m.get("sources"), list) and m["sources"], "no sources"
    assert m.get("cache_dir") == "corpus/references/cache"


def test_ids_are_unique() -> None:
    ids = [s["id"] for s in _sources()]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate source ids: {sorted(dupes)}"


def test_every_source_has_required_fields() -> None:
    for s in _sources():
        for field in ("id", "kind", "citation", "used_by", "access", "download"):
            assert field in s, f"{s.get('id', '?')} missing '{field}'"
        assert s["kind"] in _VALID_KINDS, f"{s['id']}: bad kind {s['kind']}"
        assert isinstance(s["used_by"], list) and s["used_by"], f"{s['id']}: used_by empty"
        assert s["download"]["method"] in _VALID_METHODS, f"{s['id']}: bad method"


def test_fetchable_sources_declare_a_file() -> None:
    # http / foam_src downloads must name the cache file they write.
    for s in _sources():
        m = s["download"]["method"]
        if m in ("http", "foam_src"):
            assert s.get("file"), f"{s['id']}: method {m} but no 'file'"


def test_manual_sources_have_a_note() -> None:
    for s in _sources():
        if s["download"]["method"] == "manual":
            assert s["download"].get("note"), f"{s['id']}: manual without a note"


def test_urls_are_well_formed() -> None:
    for s in _sources():
        urls = []
        if "url" in s:
            urls.append(s["url"])
        if s["download"]["method"] == "http":
            urls.append(s["download"]["url"])
        for u in urls:
            parsed = urlparse(u)
            assert parsed.scheme in ("http", "https"), f"{s['id']}: bad URL {u}"
            assert parsed.netloc, f"{s['id']}: URL has no host: {u}"


def test_consultant_tags_are_unique() -> None:
    tags = [s["consultant_tag"] for s in _sources() if "consultant_tag" in s]
    dupes = {t for t in tags if tags.count(t) > 1}
    assert not dupes, f"duplicate consultant_tag values: {sorted(dupes)}"


def test_no_known_dead_hosts() -> None:
    # Regression guard: the old turbmodels.larc.nasa.gov host redirects away.
    for s in _sources():
        blob = json.dumps(s)
        assert "turbmodels.larc.nasa.gov" not in blob, (
            f"{s['id']} cites the dead turbmodels.larc.nasa.gov host"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
